from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "inventory.db")


def db_path() -> str:
    """Resolve the SQLite file location on every call so tests can override it."""
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)
