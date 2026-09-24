from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import DomainError
from .schemas import RegisterTubeIn, SplitIn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def canonical_body(payload: dict[str, Any]) -> str:
    """Canonical serialization of a request body for idempotency comparison.

    JSON object keys are sorted so key ordering on the wire does not matter,
    but list (children) ordering is part of the contract and stays as sent.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _row_to_tube(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "initial_amount": row["initial_amount"],
        "balance": row["balance"],
        "revision": row["revision"],
    }


def _split_record(conn: sqlite3.Connection, split_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT s.id, s.request_key, s.parent_id, s.expected_revision,
               s.result_json, s.created_at
          FROM splits s
         WHERE s.id = ?
        """,
        (split_id,),
    ).fetchone()
    if row is None:
        return None
    result = json.loads(row["result_json"])
    return {
        "id": row["id"],
        "request_key": row["request_key"],
        "parent_id": row["parent_id"],
        "expected_revision": row["expected_revision"],
        "created_at": row["created_at"],
        "children": result["children"],
        "new_revision": result["new_revision"],
        "parent_balance_after": result["parent_balance_after"],
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_tube(conn: sqlite3.Connection, data: RegisterTubeIn) -> dict[str, Any]:
    """Register a brand-new root tube. A root's revision starts at 0."""
    try:
        conn.execute(
            "INSERT INTO tubes (id, initial_amount, balance, revision) VALUES (?, ?, ?, 0)",
            (data.id, data.initial_amount, data.initial_amount),
        )
    except sqlite3.IntegrityError:
        raise DomainError(
            status_code=409,
            code="TUBE_ALREADY_EXISTS",
            message=f"tube id already registered: {data.id}",
        )
    return {
        "id": data.id,
        "initial_amount": data.initial_amount,
        "balance": data.initial_amount,
        "revision": 0,
    }


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def split_tube(conn: sqlite3.Connection, data: SplitIn, raw_body: dict[str, Any]) -> dict[str, Any]:
    """Atomically split a parent tube into 1..20 children.

    Concurrency model: every split takes an IMMEDIATE write lock and is guarded
    by an optimistic revision check, so two transactions racing on the same old
    revision cannot both succeed.
    """
    body = canonical_body(raw_body)
    txn_open = False

    def _rollback() -> None:
        nonlocal txn_open
        if txn_open:
            conn.execute("ROLLBACK")
            txn_open = False

    try:
        # Fast path before opening a transaction: idempotent replay / conflict.
        hit = conn.execute(
            "SELECT body_json, result_json FROM splits WHERE request_key = ?",
            (data.request_key,),
        ).fetchone()
        if hit is not None:
            if hit["body_json"] != body:
                raise DomainError(
                    status_code=409,
                    code="IDEMPOTENCY_CONFLICT",
                    message="request_key was already used with a different body",
                    details={"request_key": data.request_key},
                )
            return json.loads(hit["result_json"])

        conn.execute("BEGIN IMMEDIATE")
        txn_open = True

        result = _execute_split(conn, data, body)
        conn.execute("COMMIT")
        txn_open = False
        return result

    except DomainError:
        _rollback()
        # A racing peer may have committed the same request_key between our
        # read and our INSERT: resolve as replay (same body) or 409 (different).
        if data.request_key:
            recovered = _recover_after_integrity(conn, data.request_key, body)
            if recovered is not None:
                return recovered
        raise
    except sqlite3.IntegrityError as exc:
        _rollback()
        recovered = _recover_after_integrity(conn, data.request_key, body)
        if recovered is not None:
            return recovered
        # Remaining unique violations mean a child id already exists elsewhere.
        existing = _existing_child_ids(
            conn, data.parent_id, [c.id for c in data.children]
        )
        if existing:
            raise DomainError(
                status_code=409,
                code="TUBE_ALREADY_EXISTS",
                message="one or more child tube ids already exist",
                details={"existing_ids": existing},
            ) from exc
        raise DomainError(
            status_code=500,
            code="INTEGRITY_ERROR",
            message="database integrity constraint failed",
        ) from exc


def _recover_after_integrity(
    conn: sqlite3.Connection, request_key: str, body: str
) -> dict[str, Any] | None:
    hit = conn.execute(
        "SELECT body_json, result_json FROM splits WHERE request_key = ?",
        (request_key,),
    ).fetchone()
    if hit is None:
        return None
    if hit["body_json"] != body:
        raise DomainError(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="request_key was already used with a different body",
            details={"request_key": request_key},
        )
    return json.loads(hit["result_json"])


def _existing_child_ids(
    conn: sqlite3.Connection, parent_id: str, child_ids: list[str]
) -> list[str]:
    if not child_ids:
        return []
    placeholders = ",".join("?" for _ in child_ids)
    rows = conn.execute(
        f"SELECT id FROM tubes WHERE id IN ({placeholders})", child_ids
    ).fetchall()
    return [r["id"] for r in rows]


def _execute_split(
    conn: sqlite3.Connection, data: SplitIn, body: str
) -> dict[str, Any]:
    parent = conn.execute(
        "SELECT id, balance, revision FROM tubes WHERE id = ?",
        (data.parent_id,),
    ).fetchone()
    if parent is None:
        raise DomainError(
            status_code=404,
            code="TUBE_NOT_FOUND",
            message=f"parent tube not found: {data.parent_id}",
        )

    # Optimistic lock: the parent must be exactly at the revision the client saw.
    if parent["revision"] != data.expected_revision:
        raise DomainError(
            status_code=412,
            code="REVISION_CONFLICT",
            message=(
                f"expected revision {data.expected_revision} but tube is at "
                f"revision {parent['revision']}"
            ),
            details={
                "tube_id": data.parent_id,
                "expected_revision": data.expected_revision,
                "current_revision": parent["revision"],
            },
        )

    requested = sum(c.amount for c in data.children)
    if requested > parent["balance"]:
        raise DomainError(
            status_code=409,
            code="INSUFFICIENT_BALANCE",
            message=(
                f"requested {requested} µL but only {parent['balance']} µL available"
            ),
            details={
                "tube_id": data.parent_id,
                "requested": requested,
                "available": parent["balance"],
            },
        )

    # The request_key UNIQUE constraint is the durable idempotency guard.
    cur = conn.execute(
        """
        INSERT INTO splits (request_key, parent_id, expected_revision, body_json, result_json)
        VALUES (?, ?, ?, ?, NULL)
        """,
        (data.request_key, data.parent_id, data.expected_revision, body),
    )
    split_id = cur.lastrowid

    new_balance = parent["balance"] - requested
    new_revision = parent["revision"] + 1
    conn.execute(
        "UPDATE tubes SET balance = ?, revision = ? WHERE id = ?",
        (new_balance, new_revision, data.parent_id),
    )

    child_payload = []
    for position, child in enumerate(data.children):
        conn.execute(
            "INSERT INTO tubes (id, initial_amount, balance, revision) VALUES (?, ?, ?, 0)",
            (child.id, child.amount, child.amount),
        )
        conn.execute(
            """
            INSERT INTO lineage (parent_id, child_id, split_id, position, amount)
            VALUES (?, ?, ?, ?, ?)
            """,
            (data.parent_id, child.id, split_id, position, child.amount),
        )
        child_payload.append({"id": child.id, "amount": child.amount})

    result = {
        "split_id": split_id,
        "request_key": data.request_key,
        "parent_id": data.parent_id,
        "new_revision": new_revision,
        "parent_balance_after": new_balance,
        "children": child_payload,
    }
    conn.execute("UPDATE splits SET result_json = ? WHERE id = ?",
                 (json.dumps(result, ensure_ascii=False), split_id))
    return result


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

# Root-first ancestor chain of a tube, including the tube itself at the end.
_CHAIN_SQL = """
WITH RECURSIVE chain(ancestor_id, balance, revision, depth) AS (
    SELECT id, balance, revision, 0
      FROM tubes WHERE id = :tube_id
    UNION ALL
    SELECT t.id, t.balance, t.revision, c.depth + 1
      FROM lineage l
      JOIN tubes t ON t.id = l.parent_id
      JOIN chain c ON c.ancestor_id = l.child_id
)
SELECT * FROM chain ORDER BY depth DESC
"""

_EDGES_SQL = """
WITH RECURSIVE chain(node_id, depth) AS (
    SELECT id, 0 FROM tubes WHERE id = :tube_id
    UNION ALL
    SELECT l.parent_id, c.depth + 1
      FROM lineage l JOIN chain c ON c.node_id = l.child_id
)
SELECT l.parent_id, l.child_id, l.split_id, l.position, l.amount
  FROM lineage l
 WHERE l.child_id IN (SELECT node_id FROM chain)
 ORDER BY (SELECT depth FROM chain WHERE node_id = l.child_id) DESC, l.position
"""


def get_tube(conn: sqlite3.Connection, tube_id: str) -> dict[str, Any]:
    chain_rows = conn.execute(_CHAIN_SQL, {"tube_id": tube_id}).fetchall()
    if not chain_rows:
        raise DomainError(
            status_code=404,
            code="TUBE_NOT_FOUND",
            message=f"tube not found: {tube_id}",
        )

    ancestors = [
        {
            "id": row["ancestor_id"],
            "balance": row["balance"],
            "revision": row["revision"],
            "depth": row["depth"],
        }
        for row in chain_rows
    ]
    # Ordered root -> self; the last entry is the queried tube itself.
    root_id = ancestors[0]["id"]

    edge_rows = conn.execute(_EDGES_SQL, {"tube_id": tube_id}).fetchall()
    edges = [
        {
            "parent_id": row["parent_id"],
            "child_id": row["child_id"],
            "split_id": row["split_id"],
            "position": row["position"],
            "amount": row["amount"],
        }
        for row in edge_rows
    ]

    # Original split records along the whole path:
    #  * every split that created one of the tubes on root..self (via edges);
    #  * every split this tube itself initiated as a parent (none for leaves/root
    #    unless it was later used as a source).
    split_ids = list(dict.fromkeys(row["split_id"] for row in edge_rows))
    own_rows = conn.execute(
        "SELECT id FROM splits WHERE parent_id = ? ORDER BY id", (tube_id,)
    ).fetchall()
    for row in own_rows:
        if row["id"] not in split_ids:
            split_ids.append(row["id"])
    split_records = [rec for sid in split_ids if (rec := _split_record(conn, sid))]

    self_row = chain_rows[-1]
    return {
        "id": self_row["ancestor_id"],
        "balance": self_row["balance"],
        "revision": self_row["revision"],
        "root_id": root_id,
        "ancestors": ancestors,
        "lineage": edges,
        "split_records": split_records,
    }


def list_tubes(conn: sqlite3.Connection, limit: int, offset: int) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT id, initial_amount, balance, revision FROM tubes ORDER BY id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS n FROM tubes").fetchone()["n"]
    return {
        "items": [_row_to_tube(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_split(conn: sqlite3.Connection, split_id: int) -> dict[str, Any]:
    record = _split_record(conn, split_id)
    if record is None:
        raise DomainError(
            status_code=404,
            code="SPLIT_NOT_FOUND",
            message=f"split record not found: {split_id}",
        )
    return record
