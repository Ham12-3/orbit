import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.llm_proxy.pricing import SUPPORTED_MODELS
from app.models.enums import BotStatus, RunStatus


def _known_model(value: str | None) -> str | None:
    if value is not None and value not in SUPPORTED_MODELS:
        raise ValueError(f"model must be one of {sorted(SUPPORTED_MODELS)}")
    return value


ModelName = Annotated[str | None, AfterValidator(_known_model)]


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    avatar_emoji: str = Field(default="🤖", min_length=1, max_length=16)
    job_description: str = Field(min_length=1, max_length=4000)
    instructions: str = Field(default="", max_length=20_000)
    model: ModelName = None
    max_turns_per_run: int | None = Field(default=None, ge=1, le=500)
    daily_token_budget: int | None = Field(default=None, ge=1_000)


class BotUpdate(BaseModel):
    """Fields to change. They reach the bot's CLAUDE.md at the start of its next run."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    avatar_emoji: str | None = Field(default=None, min_length=1, max_length=16)
    job_description: str | None = Field(default=None, min_length=1, max_length=4000)
    instructions: str | None = Field(default=None, max_length=20_000)
    model: ModelName = None
    max_turns_per_run: int | None = Field(default=None, ge=1, le=500)
    daily_token_budget: int | None = Field(default=None, ge=1_000)


class BotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    avatar_emoji: str
    job_description: str
    instructions: str
    model: str
    status: BotStatus
    enabled: bool
    daily_token_budget: int
    max_turns_per_run: int
    sandbox_id: str | None
    active_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_run_status: RunStatus | None = None
    last_run_at: datetime | None = None
    cost_today_usd: float = 0.0
