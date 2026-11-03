import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MessageRole, RunStatus


class ThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=20_000)


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)


class ThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    run_id: uuid.UUID | None
    run_status: RunStatus | None
    created_at: datetime


class ThreadDetail(ThreadRead):
    messages: list[MessageRead]
    # The run answering the latest message, while it is still going.
    active_run_id: uuid.UUID | None
