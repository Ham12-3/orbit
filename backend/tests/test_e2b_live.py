"""Live checks against real E2B: the real Anthropic key is not visible anywhere in a sandbox,
and the file operations behind memory sync and the Files tab work.

Opt-in (`make test-e2b`): needs E2B_API_KEY and ANTHROPIC_API_KEY in .env and the
template built with `make sandbox-template`. Each test creates and then kills one sandbox.
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
from app.sandboxes.provider import SandboxFileNotFoundError

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


async def test_file_operations_on_a_real_sandbox() -> None:
    """scan_tree (python -c), stat, read_bytes and remove against real E2B."""
    settings = Settings()
    if settings.e2b_api_key is None:
        pytest.skip("E2B_API_KEY must be set in .env")
    provider = E2BSandboxProvider(settings)
    sandbox = await provider.create(metadata={"purpose": "orbit-files-test"}, timeout_s=300)
    try:
        root = layout.MEMORY_DIR
        await sandbox.make_dirs(root)
        await sandbox.write_text(f"{root}/people/alex.md", "Alex runs the team.")
        await sandbox.write_text(f"{root}/prefs.md", "- short")
        await sandbox.exec(f"ln -s /etc {root}/link")

        scan = await sandbox.scan_tree(root, max_entries=50, hash_max_bytes=1024)
        by_path = {entry.path: entry for entry in scan.entries}
        assert scan.exists
        assert set(by_path) == {"people", "people/alex.md", "prefs.md"}  # no symlink
        assert by_path["prefs.md"].sha256 is not None
        assert by_path["people"].kind == "dir"

        assert (await sandbox.stat(f"{root}/link")).kind == "symlink"
        assert (await sandbox.stat(f"{root}/prefs.md")).size == len("- short")
        assert await sandbox.read_bytes(f"{root}/people/alex.md") == b"Alex runs the team."

        await sandbox.remove(f"{root}/prefs.md")
        await sandbox.remove(f"{root}/prefs.md")  # already gone: not an error
        with pytest.raises(SandboxFileNotFoundError):
            await sandbox.read_bytes(f"{root}/prefs.md")
        missing = await sandbox.scan_tree(f"{root}/nope", max_entries=5)
        assert not missing.exists
    finally:
        await AsyncSandbox.kill(sandbox.sandbox_id, api_key=settings.e2b_api_key.get_secret_value())
