"""
Parsera FastAPI service for n8n integration.

Supports direct Parsera "elements" in the POST body and keeps
"extraction_rules" as a backwards-compatible fallback.

Example POST body:

{
  "url": "https://example.com/products",
  "elements": {
    "title": "Product title",
    "price": "Product price including currency",
    "availability": "Availability status"
  }
}
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

    elements: Optional[dict[str, str]] = Field(
        None,
        description=(
            "Parsera elements dictionary. Example: "
            "{'title': 'Product title', 'price': 'Product price'}"
        ),
    )

    extraction_rules: Optional[str] = Field(
        None,
        description=(
            "Free-form extraction rules. Used only if elements is not provided."
        ),
    )

    wait_selector: Optional[str] = Field(
        None,
        description=(
            "Kept for API compatibility. Currently not used by Parsera integration."
        ),
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
    def validate_elements(
        cls,
        value: Optional[dict[str, str]],
    ) -> Optional[dict[str, str]]:
        if value is None:
            return value

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

    @field_validator("extraction_rules")
    @classmethod
    def validate_extraction_rules(
        cls,
        value: Optional[str],
    ) -> Optionalif value is None:
            return value

        if len(value) > settings.MAX_EXTRACTION_RULES_LENGTH:
            raise ValueError(
                f"Extraction rules exceed max length of "
                f"{settings.MAX_EXTRACTION_RULES_LENGTH}"
            )

        if not value.strip():
            raise ValueError("extraction_rules cannot be empty")

        return value.strip()

    @model_validator(mode="after")
    def validate_extraction_input(self) -> "ScrapeRequest":
        if not self.elements and not self.extraction_rules:
            raise ValueError("Either 'elements' or 'extraction_rules' must be provided")

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

    This makes the service more robust if Parsera changes optional constructor
    or method parameters between releases.
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
        return {}


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

    Preferred:
    {
      "url": "https://example.com",
      "elements": {
        "title": "Product title",
        "price": "Product price"
      }
    }

    Fallback:
    {
      "url": "https://example.com",
      "extraction_rules": "Extract title and price"
    }
    """
    if request.elements:
        elements = request.elements
    else:
        elements = {
            "data": request.extraction_rules.strip(),
        }

    kwargs = {
        "url": request.url,
        "elements": elements,
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
    description="FastAPI wrapper for Parsera with direct elements support",
    version="1.1.0",
    lifespan=lifespan,
)


@app.get("/", response_model=dict)
async def root() -> dict[str, str]:
    return {
        "service": "Parsera n8n Service",
        "status": "running",
        "health": "/health",
        "scrape": "/scrape",
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
