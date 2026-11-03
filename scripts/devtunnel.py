"""Microsoft Dev Tunnel that lets bot sandboxes reach the local API on port 8000.

    make tunnel-setup   once: create a persistent tunnel (anonymous access, no request
                        timeout) and write DEVTUNNEL_ID and PUBLIC_BASE_URL to .env
    make dev            runs `devtunnel.py host`, which hosts it while you work

Why Dev Tunnels: the URL stays the same across restarts, it passes the client's own
Authorization header through, and it streams SSE unbuffered (Cloudflare quick tunnels do
not support SSE). Needs `winget install Microsoft.devtunnel` and `devtunnel user login`.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any

from dotenv import dotenv_values
from init_env import set_env_values

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
PORT = 8000
URL_PATTERN = re.compile(rf"https://[a-z0-9-]+-{PORT}\.[a-z0-9]+\.devtunnels\.ms")
URL_WAIT_S = 60


def find_cli() -> str | None:
    found = shutil.which("devtunnel")
    if found:
        return found
    # winget's shim folder is missing from PATH in terminals opened before the install.
    fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
    exe = fallback / "devtunnel.exe"
    return str(exe) if exe.exists() else None


def run_json(cli: str, *args: str) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [cli, *args, "--json"], capture_output=True, text=True, timeout=60, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"devtunnel {' '.join(args)} failed:\n{result.stdout}{result.stderr}")
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def create_tunnel(cli: str) -> str:
    created = run_json(
        cli,
        "create",
        "--allow-anonymous",
        "--expiration",
        "30d",
        "--request-timeout",
        "0",
        "--description",
        "Orbit backend for bot sandboxes",
    )
    tunnel_id: str = created["tunnel"]["tunnelId"]
    run_json(
        cli,
        "port",
        "create",
        tunnel_id,
        "-p",
        str(PORT),
        "--protocol",
        "http",
        "--request-timeout",
        "0",
    )
    print(f"Created tunnel {tunnel_id}")
    return tunnel_id


def _output(process: "subprocess.Popen[str]") -> IO[str]:
    if process.stdout is None:
        raise RuntimeError("devtunnel output is not piped")
    return process.stdout


def discover_url(cli: str, tunnel_id: str) -> str:
    """Host briefly: the CLI only prints the public URL while hosting."""
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [cli, "host", tunnel_id], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    deadline = time.monotonic() + URL_WAIT_S
    try:
        for line in _output(process):
            if match := URL_PATTERN.search(line):
                return match.group(0)
            if time.monotonic() > deadline:
                break
    finally:
        process.terminate()
        process.wait(timeout=10)
    raise SystemExit(f"devtunnel host {tunnel_id} did not print a URL within {URL_WAIT_S}s")


def setup(cli: str) -> int:
    tunnel_id = dotenv_values(ENV_FILE).get("DEVTUNNEL_ID") or create_tunnel(cli)
    url = discover_url(cli, tunnel_id)
    set_env_values(ENV_FILE, {"DEVTUNNEL_ID": tunnel_id, "PUBLIC_BASE_URL": url})
    print(f"Wrote DEVTUNNEL_ID={tunnel_id} and PUBLIC_BASE_URL={url} to .env")
    return 0


def host(cli: str | None) -> int:
    env = dotenv_values(ENV_FILE)
    tunnel_id = env.get("DEVTUNNEL_ID")
    expected = (env.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if cli is None or not tunnel_id:
        reason = "devtunnel is not installed" if cli is None else "DEVTUNNEL_ID is not set"
        print(f"No tunnel ({reason}). Bot runs need one: run make tunnel-setup.", flush=True)
        while True:  # exiting would make concurrently stop the other dev processes
            time.sleep(3600)

    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [cli, "host", tunnel_id], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    for line in _output(process):
        print(line, end="", flush=True)
        if (match := URL_PATTERN.search(line)) and match.group(0) != expected:
            print(
                f"WARNING: tunnel URL {match.group(0)} differs from PUBLIC_BASE_URL={expected!r}."
                " Run make tunnel-setup and restart make dev.",
                flush=True,
            )
    return process.wait()


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    cli = find_cli()
    if command == "host":
        return host(cli)
    if command == "setup":
        if cli is None:
            raise SystemExit("Install the CLI first: winget install Microsoft.devtunnel")
        return setup(cli)
    raise SystemExit("usage: devtunnel.py setup|host")


if __name__ == "__main__":
    sys.exit(main())
