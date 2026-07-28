"""
Configuration and environment variables for Parsera service.
"""
import json
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # Service configuration
    SERVICE_NAME: str = "parsera"
    LOG_LEVEL: str = "INFO"
    
    # Browserless configuration
    BROWSERLESS_URL: str = "http://browserless:3000"
    BROWSERLESS_TIMEOUT: int = 30  # seconds
    BROWSERLESS_RETRIES: int = 1
    
    # LLM configuration
    LLM_PROVIDER: str = "gemini"  # gemini, openai, ollama
    
    # Gemini configuration
    GEMINI_API_KEY: Optional[str] = None
    
    # OpenAI configuration
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-3.5-turbo"
    
    # Ollama configuration
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama2"
    
    # Request configuration
    REQUEST_TIMEOUT: int = 60  # seconds
    MAX_URL_LENGTH: int = 2000
    MAX_EXTRACTION_RULES_LENGTH: int = 5000
    
    # Validation
    VALIDATE_JSON_OUTPUT: bool = true

    @field_validator("VALIDATE_JSON_OUTPUT", mode="before")
    @classmethod
    def _parse_validate_json_output(cls, v):
        """Coerce common boolean-like environment values into a Python bool.

        Accepts: true/false, 1/0, yes/no, on/off (case-insensitive).
        Raises a clear ValueError for anything else so startup fails with a helpful message.
        """
        # If not provided, let pydantic use the default defined on the field
        if v is None:
            return v
        # Already a bool
        if isinstance(v, bool):
            return v
        # Coerce common string forms
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("1", "true", "t", "yes", "y", "on"):
                return True
            if s in ("0", "false", "f", "no", "n", "off"):
                return False
        raise ValueError(
            f"VALIDATE_JSON_OUTPUT must be a boolean-like value (true/false/1/0), got: {v!r}"
        )

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()


def validate_llm_config() -> tuple[bool, str]:
    """
    Validate that the configured LLM provider has required credentials.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
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
