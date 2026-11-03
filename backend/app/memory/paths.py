"""Rules for memory file paths and sizes, shared by the API and the sync."""

import re

MEMORY_FILE_MAX_BYTES = 64 * 1024
MEMORY_MAX_FILES = 200
MEMORY_PATH_MAX_CHARS = 200
MEMORY_MAX_DEPTH = 5
# Letters, digits, "_", "-", "." and spaces; must not start with "." (no hidden files, no "..").
_SEGMENT = re.compile(r"\w[\w.\- ]{0,99}")


class InvalidMemoryPathError(ValueError):
    pass


def check_memory_path(path: str) -> str:
    """Return `path` if it is a safe path relative to memory/, else raise."""
    parts = path.split("/")
    if (
        not path
        or len(path) > MEMORY_PATH_MAX_CHARS
        or len(parts) > MEMORY_MAX_DEPTH
        or not all(_SEGMENT.fullmatch(part) and part == part.strip() for part in parts)
    ):
        raise InvalidMemoryPathError(
            "Use a relative path like notes.md or people/alex.md: letters, digits, '_', '-', "
            f"'.' and spaces, at most {MEMORY_MAX_DEPTH} folders deep and "
            f"{MEMORY_PATH_MAX_CHARS} characters."
        )
    return path
