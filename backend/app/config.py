"""Application settings, read from the environment and the repo-root `.env` file."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    orbit_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://orbit:orbit@localhost:5432/orbit"
    test_database_url: str = "postgresql+asyncpg://orbit:orbit@localhost:5432/orbit_test"
    db_connect_timeout_s: float = 5.0
    db_command_timeout_s: float = 30.0

    # False (the safe default) means Inngest Cloud: requests must be signed.
    inngest_dev: bool = False
    inngest_signing_key: SecretStr | None = None
    inngest_event_key: SecretStr | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
