"""
Parsera FastAPI service for n8n integration.

Orchestrates browser automation via Browserless and data extraction via LLMs
(Gemini, OpenAI, or Ollama).
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from config import settings, validate_llm_config


# Configure structured logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class ScrapeRequest(BaseModel):
    """Request model for scraping and extraction."""
    url: str = Field(..., description="URL to scrape")
    extraction_rules: str = Field(
        ..., 
        description="Extraction rules/prompt for the LLM"
    )
    wait_selector: Optional[str] = Field(
        None, 
        description="Optional CSS selector to wait for before extraction"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if len(v) > settings.MAX_URL_LENGTH:
            raise ValueError(f"URL exceeds max length of {settings.MAX_URL_LENGTH}")
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("extraction_rules")
    @classmethod
    def validate_extraction_rules(cls, v: str) -> str:
        if len(v) > settings.MAX_EXTRACTION_RULES_LENGTH:
            raise ValueError(
                f"Extraction rules exceed max length of {settings.MAX_EXTRACTION_RULES_LENGTH}"
            )
        if not v.strip():
            raise ValueError("Extraction rules cannot be empty")
        return v


class ScrapeResponse(BaseModel):
    """Response model for scraping results."""
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    provider: str
    processing_time_ms: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    browserless_available: bool
    llm_configured: bool


# ============================================================================
# LLM Providers
# ============================================================================

class LLMProvider:
    """Base class for LLM providers."""

    async def extract(self, content: str, rules: str) -> dict[str, Any]:
        """Extract structured data from content using LLM."""
        raise NotImplementedError


def _strip_code_fence(text: str) -> str:
    """Strip common Markdown code fence wrappers from LLM output.

    Handles leading ```json, leading ``` and trailing ``` plus surrounding
    whitespace. Centralizes logic so all providers behave consistently.
    """
    if not isinstance(text, str):
        return ""
    t = text.strip()
    if t.startswith("```json"):
        t = t[7:]
    if t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


class GeminiProvider(LLMProvider):
    """Google Gemini API provider.

    This class is implemented against the new googleapis/python-genai SDK (`google.genai`) and
    expects that package to be installed (PyPI package `google-genai`). It uses the
    Client.models.generate_content API to request generations and accommodates
    the most common response shapes.
    """

    def __init__(self):
        try:
            import google.genai as genai

            # Use explicit API key when provided, otherwise rely on ADC/env
            if settings.GEMINI_API_KEY:
                self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
            else:
                self.client = genai.Client()

            # prefer model name from settings if provided, default to gemini-pro
            self.model_name = getattr(settings, "GEMINI_MODEL", "gemini-pro")

        except Exception as e:
            logger.error(f"Failed to initialize Gemini (google.genai client): {e}")
            raise

    async def extract(self, content: str, rules: str) -> dict[str, Any]:
        """Extract data using Gemini via google.genai.Client.models.generate_content."""
        prompt = f"""You are a data extraction expert. Extract information from the following content based on the rules provided.

CONTENT:
{content}

EXTRACTION RULES:
{rules}

Return ONLY valid JSON with the extracted data. Do not include markdown formatting or any other text."""

        try:
            # Run blocking SDK call in a thread
            response = await asyncio.to_thread(
                lambda: self.client.models.generate_content(model=self.model_name, contents=[prompt])
            )

            # The response shape differs across SDK versions; attempt to extract text robustly
            result_text = None

            # Common: response.candidates -> list with message/content
            if hasattr(response, "candidates"):
                try:
                    c = response.candidates
                    if isinstance(c, (list, tuple)) and c:
                        first = c[0]
                        # candidate may be a Message object with 'content' attribute
                        result_text = getattr(first, "content", None) or getattr(first, "text", None) or str(first)
                except Exception:
                    result_text = None

            # Some versions expose 'output' or 'content' directly
            if not result_text and hasattr(response, "output"):
                out = getattr(response, "output")
                try:
                    if isinstance(out, (list, tuple)) and out:
                        first = out[0]
                        if isinstance(first, dict):
                            result_text = first.get("content") or first.get("text")
                        else:
                            result_text = str(first)
                    elif isinstance(out, str):
                        result_text = out
                except Exception:
                    result_text = None

            # Some responses may have a top-level 'text' attr
            if not result_text:
                result_text = getattr(response, "text", None)

            # Fallback to stringifying the whole response
            if not result_text:
                result_text = str(response)

            result_text = _strip_code_fence(result_text)
            data = json.loads(result_text)
            return data

        except json.JSONDecodeError as e:
            logger.error(f"Gemini returned invalid JSON: {e}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            raise


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI: {e}")
            raise

    async def extract(self, content: str, rules: str) -> dict[str, Any]:
        """Extract data using OpenAI."""
        prompt = f"""You are a data extraction expert. Extract information from the following content based on the rules provided.

CONTENT:
{content}

EXTRACTION RULES:
{rules}

Return ONLY valid JSON with the extracted data. Do not include markdown formatting or any other text."""

        try:
            # OpenAI client call is blocking — run in a thread
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            result_text = _strip_code_fence(response.choices[0].message.content)
            data = json.loads(result_text)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"OpenAI returned invalid JSON: {e}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
        except Exception as e:
            logger.error(f"OpenAI extraction failed: {e}")
            raise


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL

    async def extract(self, content: str, rules: str) -> dict[str, Any]:
        """Extract data using Ollama."""
        prompt = f"""You are a data extraction expert. Extract information from the following content based on the rules provided.

CONTENT:
{content}

EXTRACTION RULES:
{rules}

Return ONLY valid JSON with the extracted data. Do not include markdown formatting or any other text."""

        try:
            async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                result = response.json()
                result_text = _strip_code_fence(result.get("response", ""))
                data = json.loads(result_text)
                return data
        except json.JSONDecodeError as e:
            logger.error(f"Ollama returned invalid JSON: {e}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
        except httpx.HTTPError as e:
            logger.error(f"Ollama connection failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Ollama extraction failed: {e}")
            raise


# ============================================================================
# Service State
# ============================================================================

llm_provider: Optional[LLMProvider] = None
http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global llm_provider, http_client
    
    # Startup
    logger.info(f"Starting Parsera service with LLM provider: {settings.LLM_PROVIDER}")
    
    # Validate LLM config
    is_valid, error_msg = validate_llm_config()
    if not is_valid:
        logger.error(f"LLM configuration error: {error_msg}")
        raise RuntimeError(f"Invalid LLM configuration: {error_msg}")
    
    # Initialize LLM provider
    try:
        provider_name = settings.LLM_PROVIDER.lower()
        if provider_name == "gemini":
            llm_provider = GeminiProvider()
        elif provider_name == "openai":
            llm_provider = OpenAIProvider()
        elif provider_name == "ollama":
            llm_provider = OllamaProvider()
        else:
            raise ValueError(f"Unknown LLM provider: {provider_name}")
        logger.info(f"LLM provider initialized: {provider_name}")
    except Exception as e:
        logger.error(f"Failed to initialize LLM provider: {e}")
        raise
    
    # Initialize HTTP client
    http_client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
    
    yield
    
    # Shutdown
    logger.info("Shutting down Parsera service")
    if http_client:
        await http_client.aclose()


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="Parsera",
    description="Orchestrated web scraping and data extraction service for n8n",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    browserless_available = await check_browserless_availability()
    is_valid, _ = validate_llm_config()
    
    return HealthResponse(
        status="healthy" if browserless_available and is_valid else "degraded",
        browserless_available=browserless_available,
        llm_configured=is_valid,
    )


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest) -> ScrapeResponse:
    """
    Scrape and extract data from a URL.
    
    Args:
        request: ScrapeRequest containing URL, extraction rules, and optional wait_selector
        
    Returns:
        ScrapeResponse with extracted data or error information
    """
    start_time = time.time()
    
    try:
        logger.info(f"Scrape request: {request.url}")
        
        # Fetch content from Browserless
        logger.debug(f"Fetching content from Browserless: {request.url}")
        content = await fetch_content_from_browserless(
            request.url,
            wait_selector=request.wait_selector,
        )
        
        if not content:
            return ScrapeResponse(
                success=False,
                error="Failed to fetch content from Browserless",
                provider=settings.LLM_PROVIDER,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )
        
        logger.debug(f"Content fetched, length: {len(content)} chars")
        
        # Integrate parsera: try to parse HTML into structured output and send that to LLM.
        content_for_llm = content
        try:
            from parsera import Parsera
            logger.debug("Parsera available, attempting to parse HTML content")
            parser = Parsera(html=content)
            # parser.parse() is blocking; run it in a thread to avoid blocking FastAPI event loop
            parsed = await asyncio.to_thread(parser.parse)
            if isinstance(parsed, (dict, list)):
                content_for_llm = json.dumps(parsed)
            else:
                content_for_llm = str(parsed)
            logger.debug(f"Parsera produced content_for_llm length={len(content_for_llm)}")
        except Exception as e:
            logger.info(f"Parsera not available or parsing failed, falling back to raw HTML: {e}")
            content_for_llm = content
        
        # Extract data using LLM
        logger.debug(f"Extracting data using {settings.LLM_PROVIDER}")
        data = await llm_provider.extract(content_for_llm, request.extraction_rules)
        
        logger.info(f"Scrape successful: {request.url}")
        
        return ScrapeResponse(
            success=True,
            data=data,
            provider=settings.LLM_PROVIDER,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )
    
    except httpx.HTTPError as e:
        error_msg = f"HTTP error: {e}"
        logger.error(error_msg)
        return ScrapeResponse(
            success=False,
            error=error_msg,
            provider=settings.LLM_PROVIDER,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )
    except ValueError as e:
        error_msg = f"Extraction error: {e}"
        logger.error(error_msg)
        return ScrapeResponse(
            success=False,
            error=error_msg,
            provider=settings.LLM_PROVIDER,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(error_msg, exc_info=True)
        return ScrapeResponse(
            success=False,
            error=error_msg,
            provider=settings.LLM_PROVIDER,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )


# ============================================================================
# Helper Functions
# ============================================================================

async def check_browserless_availability() -> bool:
    """Check if Browserless is available."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{settings.BROWSERLESS_URL}/")
            return response.status_code < 500
    except Exception as e:
        logger.warning(f"Browserless health check failed: {e}")
        return False


async def fetch_content_from_browserless(
    url: str,
    wait_selector: Optional[str] = None,
) -> Optional[str]:
    """
    Fetch rendered HTML content from Browserless.
    
    Args:
        url: URL to fetch
        wait_selector: Optional CSS selector to wait for
        
    Returns:
        HTML content or None if fetch failed
    """
    if not http_client:
        logger.error("HTTP client not initialized")
        return None
    
    payload = {
        "url": url,
        "rejectResourceTypes": ["image", "media", "font"],
        "waitForSelector": wait_selector,
    }
    
    for attempt in range(settings.BROWSERLESS_RETRIES + 1):
        try:
            logger.debug(f"Fetching from Browserless (attempt {attempt + 1}): {url}")
            response = await http_client.post(
                f"{settings.BROWSERLESS_URL}/content",
                json=payload,
                timeout=settings.BROWSERLESS_TIMEOUT,
            )
            response.raise_for_status()
            content = response.text
            logger.debug(f"Content fetched successfully, size: {len(content)} bytes")
            return content
        except httpx.TimeoutException as e:
            logger.warning(f"Browserless timeout (attempt {attempt + 1}): {e}")
            if attempt < settings.BROWSERLESS_RETRIES:
                await asyncio.sleep(1)
        except httpx.HTTPStatusError as e:
            logger.error(f"Browserless HTTP error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Browserless fetch error: {e}")
            return None
    
    logger.error(f"Failed to fetch from Browserless after {settings.BROWSERLESS_RETRIES + 1} attempts")
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
