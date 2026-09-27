"""Host header allowlist: only loopback names reach any backend route."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def appmod(tmp_path, monkeypatch):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    return appmod


@pytest.mark.parametrize("host", [
    "127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:3000", "LOCALHOST:8000",
    "LocalHost", "[::1]", "[::1]:8000",
])
def test_allowed_hosts_reach_routes(appmod, host):
    client = TestClient(appmod.app, base_url="http://127.0.0.1")
    response = client.get("/capabilities", headers={"host": host})
    assert response.status_code == 200


@pytest.mark.parametrize("host", [
    "evil.example", "evil.example:8000", "testserver", "127.0.0.1.evil.example",
    "localhost.", "localhost:", "localhost:80a", "127.0.0.2", "0.0.0.0:8000", "::1",
    "[::1]x", "user@127.0.0.1", "127.0.0.1:8000:1", "",
])
def test_disallowed_hosts_are_rejected_without_echo(appmod, host):
    client = TestClient(appmod.app, base_url="http://127.0.0.1")
    response = client.get("/capabilities?probe=secret-query", headers={"host": host})
    assert response.status_code == appmod.HOST_REJECT_STATUS == 400
    assert response.json() == {"detail": appmod.HOST_REJECT_MESSAGE}
    if host:
        assert host not in response.text
    assert "secret-query" not in response.text


def test_rejection_applies_to_all_paths_and_methods_before_side_effects(appmod):
    client = TestClient(appmod.app, base_url="http://evil.example")
    assert client.post("/runs", json={"goal": "x"}).status_code == 400
    assert client.get("/no-such-route").status_code == 400
    assert client.options("/runs", headers={"origin": "http://127.0.0.1:3000",
                                            "access-control-request-method": "POST"}).status_code == 400
    assert appmod.RUNS == {}
    assert not (appmod.RUNS_DIR).exists() or not any(appmod.RUNS_DIR.iterdir())


def test_missing_host_header_is_rejected(appmod):
    import asyncio

    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": "/capabilities", "raw_path": b"/capabilities",
             "query_string": b"", "root_path": "", "headers": [],
             "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000)}
    asyncio.run(appmod.app(scope, receive, send))
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 400


def test_duplicate_host_headers_are_rejected(appmod):
    import asyncio

    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": "/capabilities", "raw_path": b"/capabilities",
             "query_string": b"", "root_path": "",
             "headers": [(b"host", b"127.0.0.1"), (b"host", b"evil.example")],
             "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000)}
    asyncio.run(appmod.app(scope, receive, send))
    assert messages[0]["status"] == 400
