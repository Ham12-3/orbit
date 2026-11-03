from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.memory.paths import MEMORY_FILE_MAX_BYTES
from app.models import MemoryFile
from app.models.enums import MemoryAuthor, MemorySyncState


class MemoryFileRead(BaseModel):
    path: str
    updated_by: MemoryAuthor
    # "push": edited here, reaches the bot's computer at the start of its next run.
    sync_state: MemorySyncState
    size: int
    updated_at: datetime

    @classmethod
    def of(cls, file: MemoryFile) -> "MemoryFileRead":
        return cls(
            path=file.path,
            updated_by=file.updated_by,
            sync_state=file.sync_state,
            size=len(file.content.encode("utf-8")),
            updated_at=file.updated_at,
        )


class MemoryFileDetail(MemoryFileRead):
    content: str

    @classmethod
    def of(cls, file: MemoryFile) -> "MemoryFileDetail":
        return cls(**MemoryFileRead.of(file).model_dump(), content=file.content)


class MemoryFileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=MEMORY_FILE_MAX_BYTES)
