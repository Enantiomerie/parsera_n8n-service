"""
Parsera FastAPI service for n8n integration.

This version uses only Parsera "elements" in the POST body.
"""

import inspect
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator, model_validator

from config import settings, validate_llm_config

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


class ScrapeRequest(BaseModel):
    url: str = Field(..., description="URL to scrape")

    elements: dict[str, str] = Field(
        ...,
        description="Parsera elements dictionary",
    )

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

    @field_validator("elements")
    @classmethod
    def validate_elements(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("elements cannot be empty")

        cleaned_elements: dict[str, str] = {}

        for key, description in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("element names must be non-empty strings")

            if not isinstance(description, str) or not description.strip():
                raise ValueError(
                    f"element '{key}' must have a non-empty string description"
                )

            cleaned_elements[key.strip()] = description.strip()

        return cleaned_elements

    @model_validator(mode="after")
    def validate_extraction_input(self) -> "ScrapeRequest":
        if not self.elements:
            raise ValueError("'elements' must be provided and cannot be empty")

        return self


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


def _filter_supported_kwargs(
    callable_obj: Any,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """
    Pass only kwargs supported by the installed Parsera version.
    """
    try:
        signature = inspect.signature(callable_obj)
        parameters = signature.parameters

        if any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in parameters.values()
        ):
            return kwargs

        return {key: value for key, value in kwargs.items() if key in parameters}
    except Exception:
        return kwargs


def build_llm_model() -> Any:
    """
    Build a LangChain chat model for Parsera.
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
    """
    from parsera import Parsera

    llm = build_llm_model()
    custom_cookies = getattr(settings, "CUSTOM_COOKIES", None)

    kwargs = {
        "model": llm,
        "stealth": settings.PLAYWRIGHT_STEALTH,
        "custom_cookies": custom_cookies,
    }

    supported_kwargs = _filter_supported_kwargs(Parsera, kwargs)
    return Parsera(**supported_kwargs)


async def run_parsera(parser: Any, request: ScrapeRequest) -> Any:
    """
    Run Parsera using arun(url=..., elements=...).
    """
    kwargs = {
        "url": request.url,
        "elements": request.elements,
        "scrolls_limit": settings.PARSERA_SCROLLS_LIMIT,
    }

    supported_kwargs = _filter_supported_kwargs(parser.arun, kwargs)
    return await parser.arun(**supported_kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Parsera n8n service")

    is_valid, error = validate_llm_config()
    if not is_valid:
        logger.error("LLM configuration invalid: %s", error)
        raise RuntimeError(error)

    yield

    logger.info("Shutting down Parsera n8n service")


app = FastAPI(
    title="Parsera n8n Service",
    description="FastAPI wrapper for Parsera with elements-only support",
    version="1.2.0",
    lifespan=lifespan,
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "Parsera n8n Service",
        "status": "running",
        "health": "/health",
        "scrape": "/scrape",
        "mode": "elements-only",
    }


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
