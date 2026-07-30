"""
Parsera FastAPI service for n8n integration.

This version uses raznem/parsera directly with Playwright and configurable
LangChain LLM providers: Gemini, OpenAI or Ollama.
"""

import inspect
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

from config import settings, validate_llm_config

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


class ScrapeRequest(BaseModel):
    url: str = Field(..., description="URL to scrape")
    extraction_rules: str = Field(..., description="Extraction rules for the LLM")
    wait_selector: Optional[str] = Field(
        None,
        description="Kept for API compatibility. Currently not used by Parsera integration.",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if len(value) > settings.MAX_URL_LENGTH:
            raise ValueError(f"URL exceeds max length of {settings.MAX_URL_LENGTH}")

        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")

        return value

    @field_validator("extraction_rules")
    @classmethod
    def validate_extraction_rules(cls, value: str) -> str:
        if len(value) > settings.MAX_EXTRACTION_RULES_LENGTH:
            raise ValueError(
                f"Extraction rules exceed max length of "
                f"{settings.MAX_EXTRACTION_RULES_LENGTH}"
            )

        if not value.strip():
            raise ValueError("Extraction rules cannot be empty")

        return value


class ScrapeResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    provider: str
    processing_time_ms: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    parsera_available: bool
    llm_configured: bool


def _filter_supported_kwargs(callable_obj: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Pass only kwargs supported by the installed Parsera version.

    This makes the service more robust if Parsera changes optional constructor
    or method parameters between releases.
    """
    try:
        signature = inspect.signature(callable_obj)
        parameters = signature.parameters

        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
            return kwargs

        return {key: value for key, value in kwargs.items() if key in parameters}
    except Exception:
        return {}


def build_llm_model() -> Any:
    """
    Build a LangChain chat model for Parsera.

    Parsera documents custom models via Parsera(model=llm), so we use the
    LangChain integrations instead of a custom Parsera extractor.
    """
    provider = settings.LLM_PROVIDER.lower()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            api_key=settings.GEMINI_API_KEY,
            temperature=0,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0,
            timeout=settings.REQUEST_TIMEOUT,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=0,
        )

    raise ValueError(f"Unknown LLM provider: {settings.LLM_PROVIDER}")


def build_parsera() -> Any:
    """
    Create a Parsera instance with supported kwargs only.

    Known Parsera docs show Parsera(model=llm). Some versions also support
    optional Playwright settings such as stealth/custom_cookies. We pass those
    only if the installed version supports them.
    """
    from parsera import Parsera

    llm = build_llm_model()

    kwargs = {
        "model": llm,
        "stealth": settings.PLAYWRIGHT_STEALTH,
        "custom_cookies": settings.CUSTOM_COOKIES,
    }

    supported_kwargs = _filter_supported_kwargs(Parsera, kwargs)
    return Parsera(**supported_kwargs)


async def run_parsera(parser: Any, request: ScrapeRequest) -> Any:
    """
    Run Parsera using its documented arun(url, elements=...) style API.

    The service accepts free-form extraction rules from n8n. Parsera expects an
    elements dictionary with field names and descriptions, so we map the user's
    rules into a single generic field called "data".
    """
    elements = {
        "data": request.extraction_rules.strip(),
    }

    kwargs = {
        "url": request.url,
        "elements": elements,
        "scrolls_limit": settings.PARSERA_SCROLLS_LIMIT,
    }

    supported_kwargs = _filter_supported_kwargs(parser.arun, kwargs)

    # If the installed Parsera version does not expose scrolls_limit, the safe
    # filtered fallback will still call arun(url=..., elements=...).
    return await parser.arun(**supported_kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Parsera n8n service using raznem/parsera")

    is_valid, error = validate_llm_config()
    if not is_valid:
        logger.error("LLM configuration invalid: %s", error)
        raise RuntimeError(error)

    yield

    logger.info("Shutting down Parsera n8n service")


app = FastAPI(
    title="Parsera n8n Service",
    description="FastAPI wrapper for raznem/parsera with configurable LangChain LLMs",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        import parsera  # noqa: F401

        parsera_available = True
    except Exception as exc:
        logger.warning("Parsera import failed: %s", exc)
        parsera_available = False

    llm_configured, _ = validate_llm_config()

    return HealthResponse(
        status="healthy" if parsera_available and llm_configured else "unhealthy",
        parsera_available=parsera_available,
        llm_configured=llm_configured,
    )


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest) -> ScrapeResponse:
    start_time = time.time()
    provider = settings.LLM_PROVIDER.lower()

    try:
        logger.info("Starting scrape request for URL: %s", request.url)

        parser = build_parsera()
        result = await run_parsera(parser, request)

        processing_time_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "Scrape request completed successfully in %sms",
            processing_time_ms,
        )

        return ScrapeResponse(
            success=True,
            data=result,
            error=None,
            provider=provider,
            processing_time_ms=processing_time_ms,
        )

    except Exception as exc:
        processing_time_ms = int((time.time() - start_time) * 1000)

        logger.exception("Scrape request failed: %s", exc)

        return ScrapeResponse(
            success=False,
            data=None,
            error=str(exc),
            provider=provider,
            processing_time_ms=processing_time_ms,
        )
