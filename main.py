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


def _extract_response_text(response) -> str:
    """Extract the generated text from a google-genai response object.

    This targets the modern google-genai Client response shape (response.text,
    or response.candidates[0].content[0].text). If the expected attributes are
    missing, fall back to the raw _result or str(response).
    """
    # Preferred shortcut
    text = getattr(response, "text", None)
    if text:
        return text

    # Try common nested shapes
    try:
        candidates = getattr(response, "candidates", None)
        if candidates and len(candidates) > 0:
            first = candidates[0]
            content = getattr(first, "content", None)
            if content and len(content) > 0:
                part = content[0]
                t = getattr(part, "text", None)
                if t:
                    return t
            t = getattr(first, "text", None)
            if t:
                return t
    except Exception:
        pass

    # Fallback to raw result dict or string
    raw = getattr(response, "_result", None)
    if raw is not None:
        try:
            return json.dumps(raw)
        except Exception:
            return str(raw)
    return str(response)


class GeminiProvider(LLMProvider):
    """Google Gemini API provider using the modern google-genai Client API."""

    def __init__(self):
        try:
            # Modern google-genai exposes a Client via `from google import genai`.
            # We explicitly migrate to this API surface.
            from google import genai

            # Allow the client to pick up the key from environment if GEMINI_API_KEY is None.
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY or None)
        except Exception as e:
            logger.error(f"Failed to initialize Gemini (google-genai Client): {e}")
            raise

    async def extract(self, content: str, rules: str) -> dict[str, Any]:
        """Extract data using Gemini (google-genai Client).

        Uses the modern generate_content signature: client.generate_content(model=..., prompt=...)
        """
        prompt = f"""You are a data extraction expert. Extract information from the following content based on the rules provided.

CONTENT:
{content}

EXTRACTION RULES:
{rules}

Return ONLY valid JSON with the extracted data. Do not include markdown formatting or any other text."""

        try:
            # Call the blocking client in a thread to avoid blocking the event loop
            response = await asyncio.to_thread(
                self.client.generate_content,
                model="gemini-pro",
                prompt=prompt,
            )

            result_text = _strip_code_fence(_extract_response_text(response))
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
