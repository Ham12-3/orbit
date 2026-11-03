"""Start a bot run from the command line and follow its timeline.

    make try-run p="Create workspace/hello.txt containing today's date"
    make try-run p="What is in workspace/hello.txt?" bot=<bot-id>

Without `bot`, it creates a new bot. Talks to the local API with LOCAL_API_TOKEN from .env.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8000"
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def describe(event: dict[str, Any]) -> str:
    payload = event["payload"]
    kind = event["type"]
    if kind == "text":
        return f"[text] {payload.get('text', '')}"
    if kind == "tool_use":
        return f"[tool] {payload.get('name')} {json.dumps(payload.get('input'))[:300]}"
    if kind == "tool_result":
        flag = " (error)" if payload.get("is_error") else ""
        return f"[result{flag}] {str(payload.get('content', ''))[:300]}"
    return f"[{kind}] {payload.get('message') or json.dumps(payload)[:300]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--bot", default="")
    args = parser.parse_args()

    token = dotenv_values(ROOT / ".env").get("LOCAL_API_TOKEN")
    if not token:
        raise SystemExit("LOCAL_API_TOKEN is not set in .env (run make install)")
    with httpx.Client(
        base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=30
    ) as api:
        bot_id = args.bot
        if not bot_id:
            bot = api.post(
                "/api/bots",
                json={"name": "Try Bot", "job_description": "A general-purpose test bot."},
            )
            bot.raise_for_status()
            bot_id = bot.json()["id"]
            print(f"Created bot {bot_id}")
        run = api.post(f"/api/bots/{bot_id}/runs", json={"prompt": args.prompt})
        run.raise_for_status()
        run_id = run.json()["id"]
        print(f"Started run {run_id}\n")

        seen = 0
        while True:
            detail = api.get(f"/api/runs/{run_id}").json()
            for event in detail["events"][seen:]:
                print(describe(event))
            seen = len(detail["events"])
            if detail["status"] in TERMINAL:
                break
            time.sleep(2)

    print(f"\nStatus: {detail['status']}")
    if detail["error"]:
        print(f"Error: {detail['error']}")
    print(f"Summary: {detail['final_summary']}")
    print(
        f"Tokens: in {detail['input_tokens']}, out {detail['output_tokens']}, "
        f"cache read {detail['cache_read_tokens']}, cache write {detail['cache_write_tokens']}; "
        f"cost ${detail['cost_usd']:.4f}"
    )
    print(f"\nReuse this bot: --bot {bot_id}")
    return 0 if detail["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
