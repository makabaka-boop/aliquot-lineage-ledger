from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "test_inventory.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return str(path)


@pytest.fixture()
def client(db_file):
    # Import after DB_PATH is set so lifespan and per-request connections use it.
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_root(client, tube_id="ROOT", amount=1000):
    r = client.post("/tubes", json={"id": tube_id, "initial_amount": amount})
    assert r.status_code == 201, r.text
    return r.json()
