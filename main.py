import inspect
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

from config import settings


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("main")


def patch_parsera_to_use_chromium() -> None:
    """
    Ensures that Parsera uses Playwright Chromium inside this container.
    Only Chromium is installed during the Docker image build.
    """
    try:
        import parsera.page as parsera_page
    except Exception as exc:
        logger.warning("Could not import parsera.page for Chromium patch: %s", exc)
        return

    async def new_browser_chromium(self: Any) -> None:
        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-setuid-sandbox",
        ]

        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=launch_args,
        )

    patched_classes: list[str] = []

    for class_name, klass in inspect.getmembers(parsera_page, inspect.isclass):
        if klass.__module__ != parsera_page.__name__:
            continue

        if hasattr(klass, "new_browser"):
            setattr(klass, "new_browser", new_browser_chromium)
            patched_classes.append(class_name)

    if patched_classes:
        logger.info("Patched Parsera browser launcher to Chromium for: %s", patched_classes)
    else:
        logger.warning("No Parsera class with new_browser found. Chromium patch was not applied.")


patch_parsera_to_use_chromium()


class ScrapeRequest(BaseModel):
    url: HttpUrl = Field(..., description="URL to scrape")

    elements: dict[str, str] | None = Field(
        default=None,
        description="Parsera element mapping, for example {'title': 'Page title'}",
    )

    extraction_rules: str | None = Field(
        default=None,
        description="Compatibility field. Used only when elements is not provided.",
    )

    wait_selector: str | None = Field(
        default=None,
        description="Optional CSS selector to wait for before extraction.",
    )

    wait_timeout_ms: int | None = Field(
        default=None,
        ge=1000,
        le=120000,
        description="Timeout for wait_selector in milliseconds.",
    )

    scrolls: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description="Optional scroll count if supported by the installed Parsera version.",
    )


class ScrapeResponse(BaseModel):
    success: bool
    url: str
    result: Any | None = None
    error: str | None = None
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str
    playwright_browser: str
    playwright_browsers_path: str | None
    llm_provider: str
    llm_configured: bool


app = FastAPI(
    title="Parsera n8n Service",
    description="Self-hosted Parsera service for n8n using internal Playwright Chromium.",
    version="2.0.0",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_provider() -> str:
    return settings.llm_provider.lower().strip()


def is_llm_configured() -> bool:
    provider = normalized_provider()

    if provider == "parsera":
        return bool(settings.parsera_api_key or os.getenv("PARSERA_API_KEY"))

    if provider == "openai":
        return bool(settings.openai_api_key or os.getenv("OPENAI_API_KEY"))

    if provider == "gemini":
        return bool(settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))

    if provider == "ollama":
        return bool(settings.ollama_base_url and settings.ollama_model)

    return False


def build_llm_model() -> Any | None:
    provider = normalized_provider()

    if provider == "parsera":
        if settings.parsera_api_key:
            os.environ["PARSERA_API_KEY"] = settings.parsera_api_key
        return None

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key

        kwargs: dict[str, Any] = {
            "model": settings.openai_model,
            "temperature": 0.0,
            "timeout": settings.request_timeout_seconds,
        }

        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url

        return ChatOpenAI(**kwargs)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if settings.gemini_api_key:
            os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            temperature=0.0,
            timeout=settings.request_timeout_seconds,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0.0,
        )

    raise ValueError("Unsupported LLM_PROVIDER. Use one of: parsera, openai, gemini, ollama.")


def build_elements(request: ScrapeRequest) -> dict[str, str]:
    if request.elements:
        return request.elements

    if request.extraction_rules:
        return {
            "data": request.extraction_rules,
        }

    raise ValueError("Either 'elements' or 'extraction_rules' must be provided.")


def build_wait_script(request: ScrapeRequest):
    if not request.wait_selector:
        return None

    selector = request.wait_selector
    timeout_ms = request.wait_timeout_ms or settings.default_wait_timeout_ms

    async def wait_script(page):
        await page.wait_for_selector(selector, timeout=timeout_ms)
        return page

    return wait_script


async def run_parsera(request: ScrapeRequest) -> Any:
    from parsera import Parsera

    model = build_llm_model()

    if model is None:
        parser = Parsera()
    else:
        parser = Parsera(model=model)

    supported_kwargs: dict[str, Any] = {
        "url": str(request.url),
        "elements": build_elements(request),
    }

    playwright_script = build_wait_script(request)

    if playwright_script is not None:
        supported_kwargs["playwright_script"] = playwright_script

    if request.scrolls is not None:
        supported_kwargs["scrolls"] = request.scrolls

    signature = inspect.signature(parser.arun)

    filtered_kwargs = {
        key: value
        for key, value in supported_kwargs.items()
        if key in signature.parameters
    }

    logger.info("Calling Parsera with kwargs: %s", list(filtered_kwargs.keys()))

    return await parser.arun(**filtered_kwargs)


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Starting Parsera n8n service")
    logger.info("LLM provider: %s", settings.llm_provider)
    logger.info("Playwright browser: chromium")
    logger.info("Playwright browser path: %s", os.getenv("PLAYWRIGHT_BROWSERS_PATH"))


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service=settings.service_name,
        timestamp=now_iso(),
        playwright_browser="chromium",
        playwright_browsers_path=os.getenv("PLAYWRIGHT_BROWSERS_PATH"),
        llm_provider=settings.llm_provider,
        llm_configured=is_llm_configured(),
    )


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest) -> JSONResponse:
    logger.info("Starting scrape request for URL: %s", request.url)

    try:
        result = await run_parsera(request)

        response = ScrapeResponse(
            success=True,
            url=str(request.url),
            result=result,
            error=None,
            timestamp=now_iso(),
        )

        return JSONResponse(
            status_code=200,
            content=response.model_dump(mode="json"),
        )

    except Exception as exc:
        logger.exception("Scrape request failed: %s", exc)

        response = ScrapeResponse(
            success=False,
            url=str(request.url),
            result=None,
            error=str(exc),
            timestamp=now_iso(),
        )

        return JSONResponse(
            status_code=500,
            content=response.model_dump(mode="json"),
        )
