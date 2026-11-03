"""Logging setup."""

import logging


class _DropInngestSyncPolls(logging.Filter):
    """The Inngest Dev Server re-syncs the app every few seconds with PUT /api/inngest."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "PUT /api/inngest" not in record.getMessage()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO, and URLs can carry tokens.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    access = logging.getLogger("uvicorn.access")
    for filter_type in (_DropInngestSyncPolls,):
        if not any(isinstance(f, filter_type) for f in access.filters):
            access.addFilter(filter_type())
