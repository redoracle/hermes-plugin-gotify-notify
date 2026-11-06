"""Against-real-server integration tests for the Hermes Gotify notification plugin.

Run with GOTIFY_TEST_URL=http://127.0.0.1:8090 and a disposable Gotify server.
A real server, rather than a mock, must persist and expose the notification.
Never point these tests at production; the server should be disposable.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest

from gotify_notify import register


@dataclass(frozen=True)
class Gotify:
    url: str
    token: str
    app_id: int
    password: str


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    password: str | None = None,
) -> dict:
    headers: dict[str, str] = {}
    if password is not None:
        basic = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {basic}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        assert 200 <= response.status < 300
        return json.load(response)


@pytest.fixture(scope="module")
def gotify_server():
    url = os.environ.get("GOTIFY_TEST_URL")
    if not url:
        pytest.skip("Real Gotify tests require the disposable CI server")
    # Protect users from accidentally running destructive test setup against a
    # hosted/production Gotify installation.
    if not url.startswith("http://127.0.0.1:") or "/" in url.removeprefix("http://127.0.0.1:"):
        pytest.fail("GOTIFY_TEST_URL must be an ephemeral http://127.0.0.1:PORT address")
    password = os.environ.get("GOTIFY_TEST_ADMIN_PASSWORD")
    if not password:
        pytest.fail("GOTIFY_TEST_ADMIN_PASSWORD must be set for integration tests")

    deadline = time.monotonic() + 45
    while True:
        try:
            _request_json(f"{url}/health")
            break
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                pytest.fail("Disposable Gotify server did not become healthy in 45 seconds")
            time.sleep(0.2)

    created = _request_json(
        f"{url}/application",
        method="POST",
        password=password,
        payload={"name": "Hermes integration test", "description": "Ephemeral CI run", "defaultPriority": 5},
    )
    token = created.get("token")
    assert isinstance(token, str) and token, "Gotify did not return the one-time application token"
    assert isinstance(created.get("id"), int) and created["id"] > 0
    return Gotify(url=url, token=token, app_id=created["id"], password=password)


@pytest.fixture
def send(gotify_server, monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", gotify_server.url)
    monkeypatch.setenv("GOTIFY_APP_TOKEN", gotify_server.token)
    monkeypatch.setenv("GOTIFY_TIMEOUT", "5")

    class Context:
        def register_tool(self, *, handler, **_kwargs):
            self.send = handler

    context = Context()
    register(context)
    return context.send


def test_real_server_persists_notification_and_preserves_markdown_extras(gotify_server, send):
    # Arrange / Act: submit through the public Hermes registered tool handler.
    result = json.loads(send({
        "title": "CI deployment",
        "message": "**Successfully deployed**",
        "priority": 8,
    }))

    # Assert: Gotify returned a real ID, and the message is persisted in its DB.
    assert result["success"] is True, result
    assert result["status"] in {200, 201}
    returned = json.loads(result["response"])
    message_id = returned["id"]
    assert isinstance(message_id, int) and message_id > 0
    assert "Successfully deployed" not in json.dumps(result)
    assert gotify_server.token not in json.dumps(result)

    page = _request_json(
        f"{gotify_server.url}/application/{gotify_server.app_id}/message?limit=25",
        password=gotify_server.password,
    )
    matches = [message for message in page["messages"] if message["id"] == message_id]
    assert len(matches) == 1, "The accepted notification is not persisted"
    message = matches[0]
    assert message["message"] == "**Successfully deployed**"
    assert message["title"] == "CI deployment"
    assert message["priority"] == 8
    assert message["appid"] == gotify_server.app_id
    assert message["extras"]["client::display"]["contentType"] == "text/markdown"


def test_real_server_rejects_bad_application_token(gotify_server, send, monkeypatch):
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "not-a-valid-app-token")

    result = json.loads(send({"message": "must not be delivered"}))

    assert result == {"success": False, "status": 401, "error": "Gotify returned HTTP 401"}
    assert "not-a-valid-app-token" not in json.dumps(result)


def test_blank_messages_do_not_reach_real_server(gotify_server, send):
    before = _request_json(
        f"{gotify_server.url}/application/{gotify_server.app_id}/message?limit=25",
        password=gotify_server.password,
    )
    before_ids = {message["id"] for message in before["messages"]}

    result = json.loads(send({"message": " \n \t "}))

    assert result == {"success": False, "error": "message must not be empty"}
    after = _request_json(
        f"{gotify_server.url}/application/{gotify_server.app_id}/message?limit=25",
        password=gotify_server.password,
    )
    after_ids = {message["id"] for message in after["messages"]}
    assert after_ids == before_ids, "Blank input unexpectedly created a persisted message"
