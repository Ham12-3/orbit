"""Create or update local env files from their examples.

Never overwrites a value you set. Adds keys that are new in the example, fills in generated
secrets (LOCAL_API_TOKEN, RUN_TOKEN_SECRET) when empty, copies LOCAL_API_TOKEN to the
frontend (which must use the same value), and drops keys from retired setups.
"""

import re
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_ENV = ROOT / ".env"
FRONTEND_ENV = ROOT / "frontend" / ".env.local"
GENERATED = {"LOCAL_API_TOKEN", "RUN_TOKEN_SECRET"}
# Supabase auth and the Phase 1 dev token were replaced by single-user mode.
RETIRED = {
    ROOT_ENV: {"SUPABASE_URL", "DEV_API_TOKEN", "DEV_USER_ID"},
    FRONTEND_ENV: {
        "NEXT_PUBLIC_SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
        "NEXT_PUBLIC_API_URL",
    },
}
LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def read_values(target: Path) -> dict[str, str]:
    if not target.exists():
        return {}
    lines = target.read_text(encoding="utf-8").splitlines()
    return {m.group(1): m.group(2).strip() for line in lines if (m := LINE.match(line))}


def merge_env(example: Path, target: Path, *, generated: set[str]) -> None:
    if not target.exists():
        shutil.copyfile(example, target)
        print(f"created {target.relative_to(ROOT)}")
    lines = target.read_text(encoding="utf-8").splitlines()
    present = {m.group(1): i for i, line in enumerate(lines) if (m := LINE.match(line))}

    added = []
    for line in example.read_text(encoding="utf-8").splitlines():
        match = LINE.match(line)
        if match and match.group(1) not in present:
            present[match.group(1)] = len(lines)
            lines.append(line)
            added.append(match.group(1))

    filled = []
    for key in sorted(generated):
        index = present[key]
        match = LINE.match(lines[index])
        if match and not match.group(2).strip():
            lines[index] = f"{key}={secrets.token_urlsafe(32)}"
            filled.append(key)

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key in added:
        print(f"added     {key} to {target.relative_to(ROOT)}")
    for key in filled:
        print(f"generated {key}")


def set_env_values(target: Path, values: dict[str, str]) -> None:
    """Set keys in an env file, replacing existing lines or appending new ones."""
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    remaining = dict(values)
    for i, line in enumerate(lines):
        match = LINE.match(line)
        if match and match.group(1) in remaining:
            lines[i] = f"{match.group(1)}={remaining.pop(match.group(1))}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_env_keys(target: Path, keys: set[str]) -> None:
    if not target.exists():
        return
    lines = target.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not ((m := LINE.match(line)) and m.group(1) in keys)]
    if len(kept) != len(lines):
        target.write_text("\n".join(kept) + "\n", encoding="utf-8")
        print(f"removed retired keys from {target.relative_to(ROOT)}")


if __name__ == "__main__":
    for path, keys in RETIRED.items():
        remove_env_keys(path, keys)
    merge_env(ROOT / ".env.example", ROOT_ENV, generated=GENERATED)
    merge_env(ROOT / "frontend" / ".env.example", FRONTEND_ENV, generated=set())
    token = read_values(ROOT_ENV)["LOCAL_API_TOKEN"]
    if read_values(FRONTEND_ENV).get("ORBIT_API_TOKEN") != token:
        set_env_values(FRONTEND_ENV, {"ORBIT_API_TOKEN": token})
        print("synced    ORBIT_API_TOKEN in frontend/.env.local")
