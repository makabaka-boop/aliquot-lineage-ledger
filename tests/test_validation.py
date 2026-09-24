from __future__ import annotations

from .conftest import make_root


def test_unknown_field_rejected(client):
    r = client.post("/tubes", json={"id": "T1", "initial_amount": 100, "color": "red"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_non_integer_amount_rejected(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "k1",
            "children": [{"id": "C1", "amount": "50"}],
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boolean_amount_rejected(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "k1",
            "children": [{"id": "C1", "amount": True}],
        },
    )
    assert r.status_code == 422


def test_zero_and_negative_amounts_rejected(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    for bad in (0, -1):
        r = client.post(
            "/splits",
            json={
                "parent_id": "T1",
                "expected_revision": 0,
                "request_key": f"k{bad}",
                "children": [{"id": f"C{bad}", "amount": bad}],
            },
        )
        assert r.status_code == 422, r.text


def test_children_count_limits(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    base = {"parent_id": "T1", "expected_revision": 0}

    r = client.post(
        "/splits", json={**base, "request_key": "empty", "children": []}
    )
    assert r.status_code == 422

    r = client.post(
        "/splits",
        json={
            **base,
            "request_key": "too_many",
            "children": [{"id": f"C{i}", "amount": 1} for i in range(21)],
        },
    )
    assert r.status_code == 422


def test_duplicate_child_id_in_request_rejected(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "dup",
            "children": [
                {"id": "C1", "amount": 10},
                {"id": "C1", "amount": 20},
            ],
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_child_id_equal_to_parent_rejected(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    r = client.post(
        "/splits",
        json={
            "parent_id": "T1",
            "expected_revision": 0,
            "request_key": "self",
            "children": [{"id": "T1", "amount": 10}],
        },
    )
    assert r.status_code == 422


def test_malformed_json_is_422(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    r = client.post(
        "/splits",
        content="{not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_parent_is_404(client):
    r = client.post(
        "/splits",
        json={
            "parent_id": "GHOST",
            "expected_revision": 0,
            "request_key": "k",
            "children": [{"id": "C1", "amount": 1}],
        },
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TUBE_NOT_FOUND"


def test_register_duplicate_tube_id_is_409(client):
    client.post("/tubes", json={"id": "T1", "initial_amount": 100})
    r = client.post("/tubes", json={"id": "T1", "initial_amount": 50})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TUBE_ALREADY_EXISTS"


def test_history_is_read_only(client):
    make_root(client, "T1", 100)
    assert client.patch("/tubes/T1", json={"balance": 999}).status_code in (404, 405)
    assert client.put("/tubes/T1", json={"balance": 999}).status_code == 405
    assert client.delete("/tubes/T1").status_code == 405
