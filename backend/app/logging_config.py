"""Logging setup."""

import logging
import re

_TICKET = re.compile(r"ticket=[^&\s]+")


class _DropInngestSyncPolls(logging.Filter):
    """The Inngest Dev Server re-syncs the app every few seconds with PUT /api/inngest."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "PUT /api/inngest" not in record.getMessage()


class _RedactStreamTickets(logging.Filter):
    """Live-run URLs carry a ticket in the query string; keep it out of the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _TICKET.sub("ticket=***", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO, and URLs can carry tokens.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    access = logging.getLogger("uvicorn.access")
    for filter_type in (_DropInngestSyncPolls, _RedactStreamTickets):
        if not any(isinstance(f, filter_type) for f in access.filters):
            access.addFilter(filter_type())
