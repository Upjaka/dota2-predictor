from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    cors_origins: str = "http://localhost:5173"
    batru_base_url: str = "https://batru.gg"
    batru_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    batru_max_retries: int = Field(default=2, ge=0, le=5)
    batru_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=10)
    opendota_base_url: str = "https://api.opendota.com/api"
    opendota_api_key: SecretStr | None = None
    opendota_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    opendota_max_retries: int = Field(default=2, ge=0, le=5)
    opendota_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=10)
    worker_poll_interval_seconds: float = Field(default=30.0, ge=10, le=86400)
    worker_max_details_per_cycle: int = Field(default=10, ge=1, le=100)
    worker_details_recheck_seconds: float = Field(default=3600.0, ge=60, le=604800)
    worker_job_stale_seconds: float = Field(default=300.0, ge=30, le=86400)
    worker_job_max_attempts: int = Field(default=3, ge=1, le=10)
    prediction_model_name: str = Field(default="default", min_length=1, max_length=100)

    @field_validator("prediction_model_name")
    @classmethod
    def normalize_prediction_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prediction_model_name must not be empty.")
        return normalized

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
