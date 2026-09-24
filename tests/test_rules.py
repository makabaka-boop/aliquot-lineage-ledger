from __future__ import annotations

from .conftest import make_root


def test_insufficient_balance_distinct_error_code(client):
    make_root(client, "T1", 100)
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "big",
            "children": [{"id": "C1", "amount": 60}, {"id": "C2", "amount": 41}],
        },
    )
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "INSUFFICIENT_BALANCE"
    assert body["details"]["requested"] == 101
    assert body["details"]["available"] == 100

    # Failed split must leave no trace on the parent.
    t = client.get("/tubes/T1").json()
    assert t["balance"] == 100
    assert t["revision"] == 0
    assert t["split_records"] == []
    assert client.get("/tubes/C1").status_code == 404


def test_revision_conflict_distinct_error_code(client):
    make_root(client, "T1", 100)
    ok = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "first",
            "children": [{"id": "C1", "amount": 30}],
        },
    )
    assert ok.status_code == 201

    stale = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "stale",
            "children": [{"id": "C2", "amount": 10}],
        },
    )
    assert stale.status_code == 412
    body = stale.json()["error"]
    assert body["code"] == "REVISION_CONFLICT"
    assert body["details"]["expected_revision"] == 0
    assert body["details"]["current_revision"] == 1

    # Fresh revision succeeds; the stale attempt changed nothing.
    fresh = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 1,
            "request_key": "fresh",
            "children": [{"id": "C2", "amount": 10}],
        },
    )
    assert fresh.status_code == 201
    assert fresh.json()["new_revision"] == 2


def test_balance_and_revision_checks_are_independent(client):
    make_root(client, "T1", 10)
    # Advance the revision so the client's view is stale AND its request is too big.
    client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "advance",
            "children": [{"id": "C1", "amount": 1}],
        },
    )
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "stale_big",
            "children": [{"id": "C2", "amount": 100}],
        },
    )
    # Revision conflict is detected before balance arithmetic.
    assert r.status_code == 412
    assert r.json()["error"]["code"] == "REVISION_CONFLICT"


def test_successful_split_shape(client):
    make_root(client, "T1", 100)
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "s1",
            "children": [
                {"id": "C1", "amount": 30},
                {"id": "C2", "amount": 25},
            ],
        },
    )
    assert r.status_code == 201
    result = r.json()
    assert result["parent_id"] == "T1"
    assert result["new_revision"] == 1
    assert result["parent_balance_after"] == 45
    assert [c["id"] for c in result["children"]] == ["C1", "C2"]


def test_existing_child_id_conflict(client):
    make_root(client, "T1", 100)
    make_root(client, "OTHER", 50)
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "collision",
            "children": [{"id": "OTHER", "amount": 10}],
        },
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TUBE_ALREADY_EXISTS"


def test_chain_and_records_for_child_tube(client):
    make_root(client, "T1", 100)
    client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "s1",
            "children": [{"id": "C1", "amount": 60}],
        },
    )
    client.post(
        "/splits",
        json={
            "parent_id": "C1",
            "expected_revision": 0,
            "request_key": "s2",
            "children": [{"id": "G1", "amount": 20}, {"id": "G2", "amount": 10}],
        },
    )
    view = client.get("/tubes/G2").json()
    assert view["id"] == "G2"
    assert view["root_id"] == "T1"
    assert [a["id"] for a in view["ancestors"]] == [
        "T1",
        "C1",
        "G2",
    ]
    assert [e["child_id"] for e in view["lineage"]] == ["C1", "G2"]
    assert [rec["request_key"] for rec in view["split_records"]] == ["s1", "s2"]
    record = view["split_records"][1]
    assert record["parent_id"] == "C1"
    assert [c["id"] for c in record["children"]] == ["G1", "G2"]

    # Root view only lists its own split.
    root_view = client.get("/tubes/T1").json()
    assert [rec["request_key"] for rec in root_view["split_records"]] == ["s1"]
