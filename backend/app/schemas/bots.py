import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.llm_proxy.pricing import SUPPORTED_MODELS
from app.models.enums import BotStatus


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    avatar_emoji: str = Field(default="🤖", min_length=1, max_length=16)
    job_description: str = Field(min_length=1, max_length=4000)
    instructions: str = Field(default="", max_length=20_000)
    model: str | None = None
    max_turns_per_run: int | None = Field(default=None, ge=1, le=500)
    daily_token_budget: int | None = Field(default=None, ge=1_000)

    @field_validator("model")
    @classmethod
    def _known_model(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_MODELS:
            raise ValueError(f"model must be one of {sorted(SUPPORTED_MODELS)}")
        return value


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
