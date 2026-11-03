"""List a directory tree inside a bot's sandbox and print it as one JSON document.

The backend runs this source with `python -c` (it is not installed in the template), so it
uses only the standard library. Symlinks are skipped and never followed. The contents of
bulky tool folders (.git, node_modules, ...) are not listed, only the folders themselves.

Output: {"exists": bool, "truncated": bool, "entries": [{"path", "kind", "size",
"modified_at", "sha256"?}]}, where `path` is relative to the root, `modified_at` is in Unix
seconds and `sha256` is set for files up to --hash-max-bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any

SKIP_CONTENTS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".cache"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(path: str, kind: str, info: Any) -> dict[str, Any]:
    size = info.st_size if kind == "file" else 0
    return {"path": path, "kind": kind, "size": size, "modified_at": info.st_mtime}


def scan(root: str, *, max_entries: int, hash_max_bytes: int) -> dict[str, Any]:
    base = Path(root)
    if base.is_symlink() or not base.is_dir():
        return {"exists": False, "truncated": False, "entries": []}
    entries: list[dict[str, Any]] = []
    pending = [""]
    while pending:
        relative = pending.pop()
        try:
            children = sorted((base / relative).iterdir())
        except OSError:
            continue
        for child in children:
            try:
                info = child.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            if len(entries) >= max_entries:
                return {"exists": True, "truncated": True, "entries": entries}
            path = f"{relative}/{child.name}" if relative else child.name
            if stat.S_ISDIR(info.st_mode):
                entries.append(_entry(path, "dir", info))
                if child.name not in SKIP_CONTENTS:
                    pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                entry = _entry(path, "file", info)
                if info.st_size <= hash_max_bytes:
                    try:
                        entry["sha256"] = _sha256(child)
                    except OSError:
                        continue
                entries.append(entry)
    return {"exists": True, "truncated": False, "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description="List a directory tree as JSON")
    parser.add_argument("root")
    parser.add_argument("--max-entries", type=int, default=2000)
    parser.add_argument("--hash-max-bytes", type=int, default=0)
    args = parser.parse_args()
    result = scan(args.root, max_entries=args.max_entries, hash_max_bytes=args.hash_max_bytes)
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
