from __future__ import annotations


def test_data_survives_restart(db_file):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.post("/tubes", json={"id": "T1", "initial_amount": 100})
        r = c.post(
            "/splits",
            json={
                "parent_id": "T1",
                "expected_revision": 0,
                "request_key": "before-restart",
                "children": [{"id": "C1", "amount": 40}, {"id": "C2", "amount": 35}],
            },
        )
        assert r.status_code == 201

    # Fresh process simulation: new TestClient opens new connections against the
    # same SQLite file on disk.
    with TestClient(app) as c:
        parent = c.get("/tubes/T1").json()
        assert parent["balance"] == 25
        assert parent["revision"] == 1
        assert c.get("/tubes/C1").json()["balance"] == 40
        assert c.get("/tubes/C2").json()["balance"] == 35

        chain = c.get("/tubes/C2").json()
        assert [a["id"] for a in chain["ancestors"]] == ["T1", "C2"]
        assert chain["split_records"][0]["request_key"] == "before-restart"

        # Retrying the exact same request after restart replays the stored result.
        replay = c.post(
            "/splits",
            json={
                "parent_id": "T1",
                "expected_revision": 0,
                "request_key": "before-restart",
                "children": [{"id": "C1", "amount": 40}, {"id": "C2", "amount": 35}],
            },
        )
        assert replay.status_code == 201
        assert replay.json()["parent_balance_after"] == 25
        assert c.get("/tubes/T1").json()["balance"] == 25
