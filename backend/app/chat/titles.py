"""Thread titles: a plain fallback straight away, then a short one from a cheap model."""

import logging
from typing import Protocol

import anthropic

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 80
SYSTEM_PROMPT = (
    "Write a title of at most six words for a chat that begins with the user's message. "
    "Reply with the title only: no quotes, no trailing punctuation."
)


def fallback_title(message: str) -> str:
    words = " ".join(message.split())
    return words if len(words) <= 60 else f"{words[:57].rstrip()}..."


class TitleGenerator(Protocol):
    async def title(self, message: str) -> str | None: ...


class ClaudeTitleGenerator:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=15.0, max_retries=1)
        self._model = model

    async def title(self, message: str) -> str | None:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=40,
                thinking={"type": "disabled"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message[:4000]}],
            )
        except anthropic.APIError as exc:
            logger.warning("Title generation failed: %s", type(exc).__name__)
            return None
        if response.stop_reason == "refusal":
            return None
        text = "".join(block.text for block in response.content if block.type == "text")
        title = text.strip().strip("\"'").strip()
        return title[:TITLE_MAX_CHARS] or None

    async def aclose(self) -> None:
        await self._client.close()
