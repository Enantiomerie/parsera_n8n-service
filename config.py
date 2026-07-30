"""
Configuration and environment variables for Parsera n8n service.
"""

import json
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Service configuration
    SERVICE_NAME: str = "parsera"
    LOG_LEVEL: str = "INFO"

    # Parsera / Playwright configuration
    PLAYWRIGHT_STEALTH: bool = True
    CUSTOM_COOKIES_JSON: Optional[str] = None
    PARSERA_SCROLLS_LIMIT: int = 0

    # LLM provider: gemini, openai, ollama
    LLM_PROVIDER: str = "gemini"

    # Gemini configuration
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # OpenAI configuration
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Ollama configuration
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama2"

    # Request configuration
    REQUEST_TIMEOUT: int = 60
    MAX_URL_LENGTH: int = 2000
    MAX_EXTRACTION_RULES_LENGTH: int = 5000

    # Output validation switch kept for compatibility
    VALIDATE_JSON_OUTPUT: bool = True

    @property
    def CUSTOM_COOKIES(self):
        if not self.CUSTOM_COOKIES_JSON:
            return None

        try:
            return json.loads(self.CUSTOM_COOKIES_JSON)
        except Exception:
            return None

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
