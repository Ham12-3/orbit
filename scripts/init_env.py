"""Create or update local env files from their examples.

Never overwrites a value you set. Adds keys that are new in the example, and fills in
generated secrets (DEV_API_TOKEN, RUN_TOKEN_SECRET) when they are empty.
"""

import re
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = {"DEV_API_TOKEN", "RUN_TOKEN_SECRET"}
LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def merge_root_env(example: Path, target: Path) -> None:
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

    generated = []
    for key in sorted(GENERATED):
        index = present[key]
        match = LINE.match(lines[index])
        if match and not match.group(2).strip():
            lines[index] = f"{key}={secrets.token_urlsafe(32)}"
            generated.append(key)

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key in added:
        print(f"added     {key} to .env")
    for key in generated:
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


def copy_if_missing(example: Path, target: Path) -> None:
    if target.exists():
        print(f"kept    {target.relative_to(ROOT)}")
    else:
        shutil.copyfile(example, target)
        print(f"created {target.relative_to(ROOT)}")


if __name__ == "__main__":
    merge_root_env(ROOT / ".env.example", ROOT / ".env")
    copy_if_missing(ROOT / "frontend" / ".env.example", ROOT / "frontend" / ".env.local")
