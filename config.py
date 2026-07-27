"""
Configuration and environment variables for Parsera service.
"""
import json
from typing import Optional
from pydantic_settings import BaseSettings


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
    VALIDATE_JSON_OUTPUT: bool = True
    
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
