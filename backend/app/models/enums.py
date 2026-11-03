"""Enumerations stored as constrained VARCHARs (easier to evolve than native PG enums)."""

from enum import StrEnum

from sqlalchemy import Enum


class BotStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class RunTrigger(StrEnum):
    MANUAL = "manual"
    CHAT = "chat"
    SCHEDULE = "schedule"
    EVENT = "event"
    HANDOFF = "handoff"
    APPROVAL_FOLLOWUP = "approval_followup"


class RunStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_RUN_STATUSES


TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}
)


class MessageRole(StrEnum):
    USER = "user"
    BOT = "bot"


class RunEventType(StrEnum):
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    STATUS = "status"
    ERROR = "error"


def db_enum(enum_cls: type[StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        name=enum_cls.__name__.lower(),
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )
