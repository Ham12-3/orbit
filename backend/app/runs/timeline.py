"""Writing run events: server status lines and the runner's streamed SDK messages."""

import json
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunEvent
from app.models.enums import RunEventType

MAX_PAYLOAD_BYTES = 256 * 1024


def _bounded(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, default=str)
    if len(encoded) <= MAX_PAYLOAD_BYTES:
        return payload
    return {"truncated": True, "preview": encoded[: MAX_PAYLOAD_BYTES // 4]}


def add_system_event(
    session: AsyncSession, run_id: uuid.UUID, type_: RunEventType, message: str, **extra: Any
) -> None:
    session.add(
        RunEvent(run_id=run_id, seq=None, type=type_, payload={"message": message, **extra})
    )


async def add_runner_events(
    session: AsyncSession, run_id: uuid.UUID, events: list[tuple[int, RunEventType, dict[str, Any]]]
) -> None:
    """Insert runner events. A repeated seq (a retried POST) is ignored."""
    if not events:
        return
    rows = [
        {"run_id": run_id, "seq": seq, "type": type_, "payload": _bounded(payload)}
        for seq, type_, payload in events
    ]
    await session.execute(
        insert(RunEvent).values(rows).on_conflict_do_nothing(index_elements=["run_id", "seq"])
    )
