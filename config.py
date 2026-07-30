"""
Configuration and environment variables for Parsera service.
"""

import json
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "parsera"
    LOG_LEVEL: str = "INFO"

    PLAYWRIGHT_STEALTH: bool = True
    CUSTOM_COOKIES_JSON: Optional[str] = None

    LLM_PROVIDER: str = "gemini"

    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: Optional[str] = None

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-3.5-turbo"

    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama2"

    REQUEST_TIMEOUT: int = 60

    MAX_URL_LENGTH: int = 2000
    MAX_EXTRACTION_RULES_LENGTH: int = 5000

    VALIDATE_JSON_OUTPUT: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()


def validate_llm_config() -> tuple[bool, str]:
    provider = settings.LLM_PROVIDER.lower()

    if provider == "gemini":
        if not settings.GEMINI_API_KEY:
            return False, "GEMINI_API_KEY is not set"

    elif provider == "openai":
        if not settings.OPENAI_API_KEY:
            return False, "OPENAI_API_KEY is not set"

    elif provider == "ollama":
        if not settings.OLLAMA_BASE_URL:
            return False, "OLLAMA_BASE_URL is not set"

    else:
        return False, f"Unknown LLM provider: {provider}"

    return True, ""


try:
    CUSTOM_COOKIES = (
        json.loads(settings.CUSTOM_COOKIES_JSON)
        if settings.CUSTOM_COOKIES_JSON
        else None
    )
except Exception:
    CUSTOM_COOKIES = None
