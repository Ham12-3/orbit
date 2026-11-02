"""Create local env files from their examples, never overwriting existing ones."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAIRS = [
    (ROOT / ".env.example", ROOT / ".env"),
    (ROOT / "frontend" / ".env.example", ROOT / "frontend" / ".env.local"),
]

for example, target in PAIRS:
    rel = target.relative_to(ROOT)
    if target.exists():
        print(f"kept    {rel}")
    else:
        shutil.copyfile(example, target)
        print(f"created {rel}")
