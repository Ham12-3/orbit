"""Event names, plus a small sender interface so routes and services test without Inngest."""

from typing import Any, Protocol

import inngest

RUN_REQUESTED = "orbit/run.requested"
RUN_FINISHED = "orbit/run.finished"


class EventSender(Protocol):
    async def send(self, name: str, data: dict[str, Any]) -> None: ...


class InngestEventSender:
    def __init__(self, client: inngest.Inngest) -> None:
        self._client = client

    async def send(self, name: str, data: dict[str, Any]) -> None:
        await self._client.send(inngest.Event(name=name, data=data))
