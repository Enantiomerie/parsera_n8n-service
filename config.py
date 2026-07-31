from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = Field(default="parsera-n8n-service", alias="SERVICE_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    llm_provider: str = Field(default="parsera", alias="LLM_PROVIDER")

    parsera_api_key: str | None = Field(default=None, alias="PARSERA_API_KEY")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    ollama_base_url: str = Field(default="http://ollama:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama2", alias="OLLAMA_MODEL")

    request_timeout_seconds: int = Field(default=60, alias="REQUEST_TIMEOUT_SECONDS")
    default_wait_timeout_ms: int = Field(default=15000, alias="DEFAULT_WAIT_TIMEOUT_MS")

    max_url_length: int = Field(default=2000, alias="MAX_URL_LENGTH")
    max_extraction_rules_length: int = Field(default=5000, alias="MAX_EXTRACTION_RULES_LENGTH")
    validate_json_output: bool = Field(default=True, alias="VALIDATE_JSON_OUTPUT")
    parsera_scrolls_limit: int = Field(default=0, alias="PARSERA_SCROLLS_LIMIT")

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
