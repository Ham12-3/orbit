from datetime import datetime

from pydantic import BaseModel

from app.sandboxes.provider import FileEntry


class WorkspaceListing(BaseModel):
    # When the listing was taken (end of the last run, or a live refresh). None: never.
    scanned_at: datetime | None
    truncated: bool
    entries: list[FileEntry]


class ClaudeMdRead(BaseModel):
    content: str
