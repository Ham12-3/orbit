"""Reading token usage from Messages API responses as they pass through the proxy."""

import json
from typing import Any

from app.llm_proxy.pricing import Usage

_COUNT_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens",
)
_MAX_BUFFER = 4 * 1024 * 1024


def _counts(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    counts = {key: value for key, value in raw.items() if isinstance(value, int)}
    breakdown = raw.get("cache_creation")
    if isinstance(breakdown, dict):
        counts.update({k: v for k, v in breakdown.items() if isinstance(v, int)})
    return {key: counts[key] for key in _COUNT_KEYS if key in counts}


def usage_from_counts(counts: dict[str, int]) -> Usage:
    cache_write = counts.get("cache_creation_input_tokens", 0)
    write_1h = counts.get("ephemeral_1h_input_tokens", 0)
    write_5m = counts.get("ephemeral_5m_input_tokens", cache_write - write_1h)
    return Usage(
        input_tokens=counts.get("input_tokens", 0),
        output_tokens=counts.get("output_tokens", 0),
        cache_read_tokens=counts.get("cache_read_input_tokens", 0),
        cache_write_5m_tokens=max(write_5m, 0),
        cache_write_1h_tokens=write_1h,
    )


def usage_from_message(message: dict[str, Any]) -> Usage:
    """Usage of a non-streaming Messages API response body."""
    return usage_from_counts(_counts(message.get("usage")))


class SseUsageTracker:
    """Feed raw SSE bytes in; read the final usage out.

    `message_start` carries the input-side counts, `message_delta` the running output count.
    Counts only grow, so the max of everything seen is the total.
    """

    def __init__(self) -> None:
        self._buffer = b""
        self._counts: dict[str, int] = {}

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split(b"\n")
        if len(self._buffer) > _MAX_BUFFER:  # not SSE we understand; stop buffering
            self._buffer = b""
        for line in lines:
            self._handle(line.rstrip(b"\r"))

    @property
    def usage(self) -> Usage:
        return usage_from_counts(self._counts)

    def _handle(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        try:
            event = json.loads(line[5:])
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        if event.get("type") == "message_start":
            message = event.get("message")
            self._merge(message.get("usage") if isinstance(message, dict) else None)
        elif event.get("type") == "message_delta":
            self._merge(event.get("usage"))

    def _merge(self, raw: object) -> None:
        for key, value in _counts(raw).items():
            self._counts[key] = max(self._counts.get(key, 0), value)
