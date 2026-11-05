from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "static"


def db_path() -> Path:
    override = os.environ.get("FINANCES_DB")
    if override:
        return Path(override)
    return DATA_DIR / "finances.db"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = db_path()
    if path.parent != DATA_DIR:
        path.parent.mkdir(parents=True, exist_ok=True)
