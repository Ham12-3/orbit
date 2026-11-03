"""sandbox-template/scan_tree.py, run on the local filesystem."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import scan_tree

from app.sandboxes.provider import TreeScan


def _tree(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "a.txt").write_text("hi", encoding="utf-8")
    (root / "sub" / "b.md").write_text("x" * 10, encoding="utf-8")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("", encoding="utf-8")


def test_lists_files_and_folders_with_hashes_for_small_files(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = scan_tree.scan(str(tmp_path), max_entries=100, hash_max_bytes=5)

    by_path = {entry["path"]: entry for entry in result["entries"]}
    assert set(by_path) == {"a.txt", "sub", "sub/b.md", "node_modules"}  # not its contents
    assert by_path["a.txt"]["sha256"] == hashlib.sha256(b"hi").hexdigest()
    assert "sha256" not in by_path["sub/b.md"]  # over the hash limit
    assert (by_path["sub"]["kind"], by_path["sub/b.md"]["size"]) == ("dir", 10)
    scan = TreeScan.model_validate(result)
    assert scan.exists
    assert not scan.truncated


def test_stops_at_max_entries(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = scan_tree.scan(str(tmp_path), max_entries=2, hash_max_bytes=0)
    assert result["truncated"] is True
    assert len(result["entries"]) == 2


def test_a_missing_root_does_not_exist(tmp_path: Path) -> None:
    result = scan_tree.scan(str(tmp_path / "nope"), max_entries=10, hash_max_bytes=0)
    assert result == {"exists": False, "truncated": False, "entries": []}


def test_symlinks_are_not_listed_or_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
        (root / "file-link").symlink_to(outside / "secret.txt")
    except OSError:
        pytest.skip("this OS account cannot create symlinks (Windows without Developer Mode)")
    result = scan_tree.scan(str(root), max_entries=10, hash_max_bytes=100)
    assert result["entries"] == []


def test_runs_with_python_dash_c_like_the_backend_does(tmp_path: Path) -> None:
    _tree(tmp_path)
    source = Path(scan_tree.__file__).read_text(encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 - our own script, fixed arguments
        [sys.executable, "-c", source, str(tmp_path), "--max-entries", "10"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    scan = TreeScan.model_validate(json.loads(completed.stdout))
    assert {entry.path for entry in scan.entries} == {"a.txt", "sub", "sub/b.md", "node_modules"}
    assert all(entry.sha256 is None for entry in scan.entries)
