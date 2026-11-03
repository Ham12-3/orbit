"""Application settings, read from the environment and the repo-root `.env` file."""

import uuid
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
        env_ignore_empty=True,  # `KEY=` in .env means "use the default", not ""
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

    # Single-user mode: no sign-in. The dashboard (through the Next.js server) and scripts send
    # LOCAL_API_TOKEN, and everything belongs to LOCAL_USER_ID. The token keeps the API closed
    # even though the dev tunnel makes the backend reachable from the internet.
    local_api_token: SecretStr | None = None
    local_user_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

    # Public HTTPS origin of this backend (the ngrok domain in dev). Sandboxes call it.
    public_base_url: str = ""

    anthropic_api_key: SecretStr | None = None
    anthropic_upstream_url: str = "https://api.anthropic.com"
    llm_upstream_connect_timeout_s: float = 10.0
    llm_upstream_read_timeout_s: float = 600.0
    default_model: str = "claude-sonnet-5-5"
    # Pinned as the CLI's "haiku" model, which it uses for background calls.
    background_model: str = "claude-haiku-5-5"

    run_token_secret: SecretStr | None = None
    run_timeout_s: int = 1800
    run_token_margin_s: int = 600
    run_wait_slice_s: int = 120
    default_max_turns: int = 50
    default_daily_token_budget: int = 2_000_000

    e2b_api_key: SecretStr | None = None
    e2b_template: str = "orbit-bot"
    # Pushed into the sandbox at every run start, so runner fixes reach existing bots
    # (template changes only reach sandboxes created after the rebuild).
    runner_script_path: Path = REPO_ROOT / "sandbox-template" / "runner.py"
    e2b_request_timeout_s: float = 60.0
    # "filesystem" drops RAM on pause (each run starts a fresh runner anyway).
    sandbox_pause_mode: Literal["filesystem", "full"] = "filesystem"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("run_token_secret")
    @classmethod
    def _long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("RUN_TOKEN_SECRET must be at least 32 characters")
        return value

    @field_validator("public_base_url", "anthropic_upstream_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
