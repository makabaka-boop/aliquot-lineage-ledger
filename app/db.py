from __future__ import annotations

import os
import sqlite3

from fastapi import Request

from .config import db_path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS tubes (
    id            TEXT PRIMARY KEY,
    initial_amount INTEGER NOT NULL CHECK (initial_amount > 0),
    balance       INTEGER NOT NULL CHECK (balance >= 0),
    revision      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS splits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_key TEXT NOT NULL UNIQUE,
    parent_id   TEXT NOT NULL REFERENCES tubes(id),
    expected_revision INTEGER NOT NULL,
    body_json   TEXT NOT NULL,
    result_json TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lineage (
    parent_id  TEXT NOT NULL REFERENCES tubes(id),
    child_id   TEXT NOT NULL REFERENCES tubes(id),
    split_id   INTEGER NOT NULL REFERENCES splits(id),
    position   INTEGER NOT NULL,
    amount     INTEGER NOT NULL CHECK (amount > 0),
    PRIMARY KEY (parent_id, child_id),
    UNIQUE (child_id),
    CHECK (parent_id <> child_id)
);

CREATE INDEX IF NOT EXISTS idx_lineage_parent ON lineage(parent_id);
CREATE INDEX IF NOT EXISTS idx_lineage_split  ON lineage(split_id);
"""


def connect(database: str | None = None) -> sqlite3.Connection:
    """Open a connection configured for safe concurrent access.

    * autocommit (``isolation_level=None``) so we control the transaction
      boundary explicitly with ``BEGIN IMMEDIATE``;
    * WAL allows a reader and one writer to coexist;
    * a busy timeout makes concurrent writers wait for the write lock instead
      of failing immediately.
    """
    path = database or db_path()
    # Ensure a local data directory exists on first run (Docker uses /data).
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(
        path,
        timeout=5.0,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def get_db(request: Request) -> sqlite3.Connection:
    """FastAPI dependency: one connection per request, closed afterwards."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
