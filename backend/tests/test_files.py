"""The read-only Files tab: workspace listing and file contents."""

import pytest
from httpx import AsyncClient

from app.api import files as files_api
from app.runs.service import RunServices
from app.sandboxes import layout
from tests.conftest import AUTH, create_bot
from tests.fakes import FakeSandboxProvider
from tests.test_run_lifecycle import started_run

WS = layout.WORKSPACE_DIR


async def test_no_listing_before_the_first_run(client: AsyncClient) -> None:
    bot = await create_bot(client)
    response = await client.get(f"/api/bots/{bot['id']}/files", headers=AUTH)
    assert response.json() == {"scanned_at": None, "truncated": False, "entries": []}
    response = await client.get(f"/api/bots/{bot['id']}/files/content/a.txt", headers=AUTH)
    assert response.status_code == 404
    assert "no computer yet" in response.json()["detail"]


async def test_the_listing_is_taken_when_a_run_ends(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, run_id = await started_run(client, services)
    sandbox = sandboxes.sandboxes["sbx-1"]
    sandbox.files[f"{WS}/hello.txt"] = "2026-11-03"
    sandbox.files[f"{WS}/reports/q4.md"] = "# Q4"
    sandbox.files[f"{layout.MEMORY_DIR}/not-workspace.md"] = "x"

    await services.finalize(run_id)
    sandbox.files[f"{WS}/later.txt"] = "written after the run"  # not in the snapshot

    listing = (await client.get(f"/api/bots/{bot['id']}/files", headers=AUTH)).json()
    assert listing["scanned_at"] is not None
    assert [(e["path"], e["kind"], e["size"]) for e in listing["entries"]] == [
        ("reports", "dir", 0),
        ("hello.txt", "file", 10),
        ("reports/q4.md", "file", 4),
    ]


async def test_a_live_listing_reads_the_sandbox_now(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, run_id = await started_run(client, services)
    await services.finalize(run_id)
    sandboxes.sandboxes["sbx-1"].files[f"{WS}/new.txt"] = "hi"

    live = (await client.get(f"/api/bots/{bot['id']}/files?live=true", headers=AUTH)).json()
    assert [e["path"] for e in live["entries"]] == ["new.txt"]
    # The bot is idle, so the live listing becomes the saved one.
    saved = (await client.get(f"/api/bots/{bot['id']}/files", headers=AUTH)).json()
    assert saved == live


async def test_opening_a_file_returns_its_bytes_as_a_download(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, _ = await started_run(client, services)
    sandboxes.sandboxes["sbx-1"].files[f"{WS}/web/page.html"] = "<script>alert(1)</script>"

    response = await client.get(f"/api/bots/{bot['id']}/files/content/web/page.html", headers=AUTH)
    assert response.status_code == 200
    assert response.content == b"<script>alert(1)</script>"
    # Untrusted bytes must never render on Orbit's origin.
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''page.html"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"


async def test_files_outside_the_workspace_cannot_be_opened(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, _ = await started_run(client, services)
    sandbox = sandboxes.sandboxes["sbx-1"]
    sandbox.files[f"{WS}/link"] = "target"
    sandbox.symlinks.add(f"{WS}/link")
    base = f"/api/bots/{bot['id']}/files/content"

    assert (await client.get(f"{base}/link", headers=AUTH)).status_code == 404
    assert (await client.get(f"{base}/missing.txt", headers=AUTH)).status_code == 404
    for bad in ["..%2F.orbit%2Fruns", "a/%2E%2E/%2E%2E/CLAUDE.md", "a//b"]:
        response = await client.get(f"{base}/{bad}", headers=AUTH)
        assert response.status_code in (404, 422), bad
        assert sandbox.reads == [], bad


async def test_big_files_are_refused(
    client: AsyncClient,
    services: RunServices,
    sandboxes: FakeSandboxProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(files_api, "FILE_MAX_BYTES", 5)
    bot, _ = await started_run(client, services)
    sandboxes.sandboxes["sbx-1"].files[f"{WS}/big.log"] = "123456"

    response = await client.get(f"/api/bots/{bot['id']}/files/content/big.log", headers=AUTH)
    assert response.status_code == 413


async def test_a_vanished_sandbox_is_reported(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, run_id = await started_run(client, services)
    await services.finalize(run_id)
    del sandboxes.sandboxes["sbx-1"]

    response = await client.get(f"/api/bots/{bot['id']}/files?live=true", headers=AUTH)
    assert response.status_code == 404
    assert "no longer exists" in response.json()["detail"]
