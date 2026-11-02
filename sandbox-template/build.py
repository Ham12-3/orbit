"""Build and publish the bot template on E2B.

Run from the repo root with `make sandbox-template`. Reads E2B_API_KEY (and optionally
E2B_TEMPLATE, default "orbit-bot") from the repo-root .env.
"""

import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from e2b import Template, default_build_logger
from template import template

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    # Build logs contain non-ASCII; a Windows console (cp1252) would crash the logger.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("E2B_API_KEY"):
        raise SystemExit("E2B_API_KEY is not set in .env")
    name = os.environ.get("E2B_TEMPLATE") or "orbit-bot"
    info = Template.build(
        template,
        name,
        cpu_count=2,
        memory_mb=2048,
        on_build_logs=default_build_logger(),
    )
    print(f"Built template {name!r}: {info}")


if __name__ == "__main__":
    main()
