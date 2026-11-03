"""Fire-and-forget work that should outlive the request that started it."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Keep references so running tasks are not garbage collected.
_tasks: set[asyncio.Task[None]] = set()


def spawn(work: Coroutine[Any, Any, None], *, name: str) -> None:
    task = asyncio.create_task(_logged(work, name), name=name)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain() -> None:
    """Wait for everything spawned so far (tests, shutdown)."""
    while _tasks:
        await asyncio.gather(*list(_tasks))


async def _logged(work: Coroutine[Any, Any, None], name: str) -> None:
    try:
        await work
    except Exception:
        logger.exception("Background task %s failed", name)
