import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RunEventType, RunStatus, RunTrigger


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=20_000)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    thread_id: uuid.UUID | None
    trigger_type: RunTrigger
    status: RunStatus
    input_prompt: str
    final_summary: str | None
    error: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    num_turns: int | None
    agent_session_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int | None
    type: RunEventType
    payload: dict[str, Any]
    created_at: datetime


class RunDetail(RunRead):
    events: list[RunEventRead]


class StreamTicketRead(BaseModel):
    ticket: str
    expires_at: datetime


class RunnerEvent(BaseModel):
    seq: int = Field(ge=1)
    type: RunEventType
    payload: dict[str, Any]


class RunnerEvents(BaseModel):
    events: list[RunnerEvent] = Field(min_length=1, max_length=100)


class RunnerCompletion(BaseModel):
    status: Literal["completed", "failed"]
    summary: str | None = Field(default=None, max_length=100_000)
    error: str | None = Field(default=None, max_length=10_000)
    session_id: str | None = Field(default=None, max_length=64)
    num_turns: int | None = Field(default=None, ge=0)
