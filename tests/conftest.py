from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.main import create_app


def make_split(parent: str, revision: int, key: str, children: list[tuple[str, int]]) -> dict:
    return {
        "parent_id": parent,
        "expected_revision": revision,
        "request_key": key,
        "children": [{"id": cid, "amount_ul": amt} for cid, amt in children],
    }


def total_balance(client: TestClient) -> int:
    return sum(t["balance_ul"] for t in client.get("/tubes").json()["tubes"])


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "lab.db")


@pytest.fixture()
def client(db_path):
    app = create_app(db_path)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def server(db_path):
    """A real uvicorn instance in a thread: concurrent requests get genuinely
    independent SQLite connections, like two terminals hitting the API."""
    app = create_app(db_path)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn failed to start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=15)
