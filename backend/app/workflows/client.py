import logging

import inngest
from pydantic import SecretStr

from app.config import Settings

INNGEST_APP_ID = "orbit"


def create_inngest_client(settings: Settings) -> inngest.Inngest:
    return inngest.Inngest(
        app_id=INNGEST_APP_ID,
        # Explicit, so a stray INNGEST_DEV in the shell can't flip modes.
        is_production=not settings.inngest_dev,
        signing_key=_reveal(settings.inngest_signing_key),
        event_key=_reveal(settings.inngest_event_key),
        logger=logging.getLogger("orbit.inngest"),
    )


def _reveal(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret is not None else None
