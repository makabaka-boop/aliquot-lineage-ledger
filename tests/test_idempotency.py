from __future__ import annotations

from .conftest import make_root

BODY = {
    "parent_id": "T1",
    "expected_revision": 0,
    "request_key": "idem-1",
    "children": [{"id": "C1", "amount": 40}],
}


def test_retry_same_key_same_body_returns_original(client):
    make_root(client, "T1", 100)
    first = client.post("/splits", json=BODY)
    assert first.status_code == 201
    first_json = first.json()

    # Balance is gone after the first call...
    assert client.get("/tubes/T1").json()["balance"] == 60

    # ...yet the retry replays the stored result and deducts nothing again.
    second = client.post("/splits", json=BODY)
    assert second.status_code == 201
    assert second.json() == first_json
    assert client.get("/tubes/T1").json()["balance"] == 60
    assert client.get("/tubes/T1").json()["revision"] == 1

    # Only one split record / lineage edge exists.
    assert client.get("/splits/1").json()["id"] == 1
    tube = client.get("/tubes/C1").json()
    assert tube["balance"] == 40
    assert tube["revision"] == 0
    root = client.get("/tubes/T1").json()
    assert len(root["split_records"]) == 1
    assert root["split_records"][0]["request_key"] == "idem-1"


def test_retry_with_key_reordered_keys_still_replays(client):
    make_root(client, "T1", 100)
    first = client.post("/splits", json=BODY)
    shuffled = {
        "children": BODY["children"],
        "request_key": BODY["request_key"],
        "expected_revision": BODY["expected_revision"],
        "parent_id": BODY["parent_id"],
    }
    second = client.post("/splits", json=shuffled)
    assert second.status_code == 201
    assert second.json() == first.json()


def test_same_key_different_body_is_409(client):
    make_root(client, "T1", 100)
    assert client.post("/splits", json=BODY).status_code == 201

    changed = {**BODY, "children": [{"id": "C9", "amount": 99}]}
    r = client.post("/splits", json=changed)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    # The different body must not have executed.
    assert client.get("/tubes/C9").status_code == 404
    assert client.get("/tubes/C1").json()["balance"] == 40


def test_replay_stored_even_if_now_stale(client):
    make_root(client, "T1", 100)
    first = client.post("/splits", json=BODY)
    # Another split moves the parent to revision 2...
    client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 1,
            "request_key": "idem-2",
            "children": [{"id": "C2", "amount": 5}],
        },
    )
    # ...but the original request key still replays instead of 412.
    replay = client.post("/splits", json=BODY)
    assert replay.status_code == 201
    assert replay.json() == first.json()


def test_replay_does_not_recreate_children(client):
    make_root(client, "T1", 100)
    client.post("/splits", json=BODY)
    replay = client.post("/splits", json=BODY)
    assert replay.status_code == 201
    tubes = client.get("/tubes").json()
    child_tubes = [t for t in tubes["items"] if t["id"] == "C1"]
    assert len(child_tubes) == 1
