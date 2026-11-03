"""The live run timeline as Server-Sent Events.

Polls the database (about once a second) rather than using LISTEN/NOTIFY: simple, works
across several API instances, and cheap at this scale. Each poll uses a fresh short session.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi.sse import ServerSentEvent
from sqlalchemy import select

from app.db import Database
from app.models import Run, RunEvent
from app.schemas.runs import RunEventRead, RunRead

POLL_INTERVAL_S = 1.0
MAX_STREAM_S = 60 * 60
BATCH = 500


async def run_stream(
    db: Database,
    run_id: uuid.UUID,
    *,
    after_event_id: int = 0,
    poll_interval_s: float = POLL_INTERVAL_S,
) -> AsyncIterator[ServerSentEvent]:
    """Yields `run_event` (with ids, so reconnects resume), `run` on any change, then `end`."""
    last_id = after_event_id
    last_state: dict[str, Any] | None = None
    deadline = time.monotonic() + MAX_STREAM_S
    while time.monotonic() < deadline:
        async with db.session() as session:
            events = list(
                await session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                    .order_by(RunEvent.id)
                    .limit(BATCH)
                )
            )
            run = await session.get(Run, run_id)
        if run is None:
            return
        for event in events:
            last_id = event.id
            yield ServerSentEvent(
                event="run_event",
                id=str(event.id),
                data=RunEventRead.model_validate(event).model_dump(mode="json"),
            )
        state = RunRead.model_validate(run).model_dump(mode="json")
        if state != last_state:
            last_state = state
            yield ServerSentEvent(event="run", data=state)
        if run.status.is_terminal and not events:
            yield ServerSentEvent(event="end", data={"status": run.status.value})
            return
        await asyncio.sleep(poll_interval_s)
