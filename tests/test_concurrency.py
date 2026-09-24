from __future__ import annotations

import threading

from app.db import connect, init_db
from app.schemas import SplitIn
from app.service import split_tube

from .conftest import make_root


def _make_split(parent="T1", key="k", children=("C1", 50), rev=0):
    if isinstance(children, tuple):
        child_list = [{"id": children[0], "amount": children[1]}]
    else:
        child_list = [{"id": cid, "amount": amt} for cid, amt in children]
    return SplitIn(
        parent_id=parent,
        expected_revision=rev,
        request_key=key,
        children=child_list,
    )


def test_two_connections_same_old_revision_at_most_one_wins(db_file):
    """Core requirement: two independent connections racing on the same old
    revision on the same parent — exactly one split may commit."""
    conn_a = connect(db_file)
    conn_b = connect(db_file)
    init_db(conn_a)
    conn_a.execute(
        "INSERT INTO tubes (id, initial_amount, balance, revision) VALUES ('T1', 100, 100, 0)"
    )

    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def worker(name, conn, child_id, key):
        try:
            barrier.wait()
            split_tube(
                conn,
                _make_split(key=key, children=(child_id, 40)),
                {
                    "parent_id": "T1",
                    "expected_revision": 0,
                    "request_key": key,
                    "children": [{"id": child_id, "amount": 40}],
                },
            )
            outcomes[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - record the code for assertion
            outcomes[name] = getattr(exc, "code", type(exc).__name__)

    t1 = threading.Thread(target=worker, args=("a", conn_a, "CA", "key-a"))
    t2 = threading.Thread(target=worker, args=("b", conn_b, "CB", "key-b"))
    t1.start(); t2.start()
    t1.join(10); t2.join(10)

    statuses = sorted(outcomes.values())
    assert "ok" in statuses, outcomes
    assert statuses.count("ok") == 1, outcomes
    assert "REVISION_CONFLICT" in statuses, outcomes

    parent = conn_a.execute("SELECT balance, revision FROM tubes WHERE id = 'T1'").fetchone()
    assert parent["revision"] == 1
    assert parent["balance"] == 60

    n_children = conn_a.execute(
        "SELECT COUNT(*) AS n FROM tubes WHERE id IN ('CA', 'CB')"
    ).fetchone()["n"]
    assert n_children == 1

    conn_a.close(); conn_b.close()


def test_two_api_clients_racing_same_revision(db_file):
    """Same race exercised through HTTP with two independent clients."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        make_root(c, "T1", 100)

    client1 = TestClient(app)
    client2 = TestClient(app)
    barrier = threading.Barrier(2)
    results = {}

    def call(name, client, child_id, key):
        payload = {
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": key,
            "children": [{"id": child_id, "amount": 30}],
        }
        barrier.wait()
        r = client.post("/splits", json=payload)
        results[name] = r.status_code

    t1 = threading.Thread(target=call, args=("a", client1, "CA", "ka"))
    t2 = threading.Thread(target=call, args=("b", client2, "CB", "kb"))
    t1.start(); t2.start()
    t1.join(15); t2.join(15)

    assert sorted(results.values()) == [201, 412], results
    with TestClient(app) as c:
        t1_state = c.get("/tubes/T1").json()
        assert t1_state["revision"] == 1
        assert t1_state["balance"] == 70


def test_same_key_same_body_racing_clients(client):
    """Idempotency under concurrency: both callers see one stored result."""
    make_root(client, "T1", 100)
    payload = {
        "parent_id": "T1",
        "expected_revision": 0,
        "request_key": "race-same",
        "children": [{"id": "C1", "amount": 25}],
    }
    barrier = threading.Barrier(2)
    statuses = []

    def call():
        barrier.wait()
        statuses.append(client.post("/splits", json=payload).status_code)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    assert statuses == [201, 201]
    assert client.get("/tubes/T1").json()["balance"] == 75
    assert len(client.get("/tubes/T1").json()["split_records"]) == 1
