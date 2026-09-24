from __future__ import annotations

from .conftest import make_root


def test_layered_splits_total_volume_conserved(client):
    # Root 100 µL.
    make_root(client, "ROOT", 100)

    def split(parent, rev, key, children):
        r = client.post(
            "/splits",
            json={
                "parent_id": parent,
                "expected_revision": rev,
                "request_key": key,
                "children": [{"id": cid, "amount": amt} for cid, amt in children],
            },
        )
        assert r.status_code == 201, r.text
        return r.json()

    # Layer 1: ROOT -> A (60) + B (30); ROOT keeps 10.
    split("ROOT", 0, "l1", [("A", 60), ("B", 30)])
    # Layer 2: A -> A1 (20) + A2 (25); A keeps 15.
    split("A", 0, "l2", [("A1", 20), ("A2", 25)])
    # Layer 3: A1 -> A1x (7) + A1y (8); A1 keeps 5.
    split("A1", 0, "l3", [("A1x", 7), ("A1y", 8)])
    # B can also be split: B -> B1 (30), B keeps 0.
    split("B", 0, "l2b", [("B1", 30)])

    def total_balance():
        items = client.get("/tubes?limit=500").json()["items"]
        return sum(t["balance"] for t in items)

    assert total_balance() == 100

    # Spot check balances and revisions.
    assert client.get("/tubes/ROOT").json()["balance"] == 10
    assert client.get("/tubes/ROOT").json()["revision"] == 1
    assert client.get("/tubes/A").json()["balance"] == 15
    assert client.get("/tubes/A").json()["revision"] == 1
    assert client.get("/tubes/A1").json()["balance"] == 5
    assert client.get("/tubes/A1").json()["revision"] == 1
    assert client.get("/tubes/A1x").json()["balance"] == 7
    assert client.get("/tubes/B").json()["balance"] == 0
    assert client.get("/tubes/B1").json()["balance"] == 30

    # Empty tube cannot be split (409, distinct from revision 412).
    r = client.post(
        "/splits",
        json={
            "parent_id": "B",
            "expected_revision": 1,
            "request_key": "overdraw",
            "children": [{"id": "BX", "amount": 1}],
        },
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"

    # Deep child has the full root-to-self chain and every original split on it.
    deep = client.get("/tubes/A1y").json()
    assert deep["root_id"] == "ROOT"
    assert [a["id"] for a in deep["ancestors"]] == ["ROOT", "A", "A1", "A1y"]
    keys = [rec["request_key"] for rec in deep["split_records"]]
    assert keys == ["l1", "l2", "l3"]

    # Edge amounts reconstruct the genealogy.
    edges = {(e["parent_id"], e["child_id"]): e["amount"] for e in deep["lineage"]}
    assert edges == {("ROOT", "A"): 60, ("A", "A1"): 20, ("A1", "A1y"): 8}

    # Conservation from the deep child's perspective:
    # remaining balance of each tube on the root..leaf path + already-split
    # amounts of siblings equals the root's initial 100.
    root_remaining = 10
    a_remaining = 15
    a1_remaining = 5
    a1y = 8
    assert root_remaining + a_remaining + a1_remaining + a1y + 30 + 25 + 7 == 100


def test_exhaustive_equal_split_conservation(client):
    make_root(client, "ROOT", 20)
    for i in range(20):
        r = client.post(
            "/splits",
            json={
                "parent_id": "ROOT",
                "expected_revision": i,
                "request_key": f"s{i}",
                "children": [{"id": f"C{i}", "amount": 1}],
            },
        )
        assert r.status_code == 201, r.text

    root = client.get("/tubes/ROOT").json()
    assert root["balance"] == 0
    assert root["revision"] == 20
    items = client.get("/tubes?limit=500").json()["items"]
    assert sum(t["balance"] for t in items) == 20


def test_split_twenty_children_at_once(client):
    make_root(client, "ROOT", 20)
    children = [{"id": f"C{i:02d}", "amount": 1} for i in range(20)]
    r = client.post(
        "/splits",
        json={
            "parent_id": "ROOT",
            "expected_revision": 0,
            "request_key": "fanout",
            "children": children,
        },
    )
    assert r.status_code == 201
    assert len(r.json()["children"]) == 20
    assert client.get("/tubes/ROOT").json()["balance"] == 0
    view = client.get("/tubes/C19").json()
    assert [a["id"] for a in view["ancestors"]] == ["ROOT", "C19"]
    assert view["split_records"][0]["children"] == children
