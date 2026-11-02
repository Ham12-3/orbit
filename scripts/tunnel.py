"""Expose the local API (port 8000) at PUBLIC_BASE_URL with ngrok, for bot sandboxes.

Part of `make dev`. If PUBLIC_BASE_URL is unset or ngrok is missing, it explains and idles
(exiting would make concurrently stop the other dev processes).
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def idle(message: str) -> None:
    print(message, flush=True)
    while True:
        time.sleep(3600)


def main() -> int:
    url = (dotenv_values(ROOT / ".env").get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    url = os.environ.get("PUBLIC_BASE_URL", url)
    if not url:
        idle("PUBLIC_BASE_URL is not set in .env: no tunnel. Bot runs need it (see CLAUDE.md).")
    ngrok = shutil.which("ngrok")
    if ngrok is None:
        idle("ngrok is not installed: no tunnel. Install it, then restart make dev.")
    print(f"Tunnelling {url} -> http://localhost:8000", flush=True)
    command = [str(ngrok), "http", "8000", "--url", url, "--log", "stdout", "--log-level", "warn"]
    return subprocess.call(command)  # noqa: S603 - fixed argv, no shell


if __name__ == "__main__":
    sys.exit(main())
