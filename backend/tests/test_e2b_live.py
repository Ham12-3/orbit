"""Live check against real E2B: the real Anthropic key is not visible anywhere in a sandbox.

Opt-in (`make test-e2b`): needs E2B_API_KEY and ANTHROPIC_API_KEY in .env and the
template built with `make sandbox-template`. Creates and then kills one sandbox.
"""

import shlex
import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from e2b import AsyncSandbox

from app.config import Settings
from app.models import Bot
from app.sandboxes import layout
from app.sandboxes.e2b import E2BSandboxProvider

pytestmark = pytest.mark.e2b


async def test_real_anthropic_key_is_not_in_the_sandbox() -> None:
    settings = Settings()
    if settings.e2b_api_key is None or settings.anthropic_api_key is None:
        pytest.skip("E2B_API_KEY and ANTHROPIC_API_KEY must be set in .env")
    real_key = settings.anthropic_api_key.get_secret_value()

    provider = E2BSandboxProvider(settings)
    sandbox = await provider.create(metadata={"purpose": "orbit-env-test"}, timeout_s=300)
    try:
        bot = cast(Bot, SimpleNamespace(model=settings.default_model, max_turns_per_run=1))
        envs = layout.runner_env(
            settings=settings, bot=bot, run_id=uuid.uuid4(), run_token="run-token-under-test"
        )
        # Start a stand-in for the runner with exactly the env a real run gets.
        await sandbox.start_background("sleep 120", envs=envs, cwd=layout.HOME)

        dump = await sandbox.exec(
            "bash -c "
            + shlex.quote(
                "env; for f in /proc/[0-9]*/environ; do tr '\\0' '\\n' < $f; done 2>/dev/null"
            )
        )

        assert "run-token-under-test" in dump.stdout  # proves we can see process envs
        assert real_key not in dump.stdout
        assert real_key[-12:] not in dump.stdout
    finally:
        await AsyncSandbox.kill(sandbox.sandbox_id, api_key=settings.e2b_api_key.get_secret_value())
