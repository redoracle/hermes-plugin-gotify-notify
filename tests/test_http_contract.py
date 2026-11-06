"""Real localhost HTTP contract coverage for Gotify notification delivery.

No external Gotify credentials, Internet access or production server is used.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue

import pytest

from gotify_notify import register


@pytest.fixture
def gotify_http(monkeypatch):
    requests: Queue[dict] = Queue()

    class GotifyHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, ValueError):
                body = None

            requests.put({
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
            })

            if self.path != "/message":
                status, reply = 404, {"error": "Unknown endpoint"}
            elif self.headers.get("X-Gotify-Key") != "app-token-test":
                status, reply = 401, {"error": "Unauthorized", "secret": "private"}
            elif not isinstance(body, dict) or not body.get("message"):
                status, reply = 400, {"error": "message required"}
            elif body["message"] == "service unavailable":
                status, reply = 503, {"error": "upstream failure", "secret": "private"}
            else:
                status, reply = 200, {
                    "id": 412,
                    "message": body["message"],
                    "token": "private",
                }

            data = json.dumps(reply).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), GotifyHandler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        monkeypatch.setenv("GOTIFY_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("GOTIFY_APP_TOKEN", "app-token-test")
        monkeypatch.setenv("GOTIFY_TIMEOUT", "2")
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")

        class Context:
            def register_tool(self, *, handler, **_kwargs):
                self.send = handler

        context = Context()
        register(context)
        try:
            yield context.send, requests
        finally:
            server.shutdown()
            worker.join(timeout=5)
            assert not worker.is_alive(), "Contract server did not stop"


def received(requests):
    try:
        return requests.get(timeout=2)
    except Empty as exc:
        raise AssertionError("Local Gotify contract server received no POST") from exc


def test_notification_reaches_http_server_with_expected_payload_and_credentials(gotify_http):
    send, requests = gotify_http

    result = json.loads(send({
        "title": "Deployment",
        "message": "**Passed**",
        "priority": 8,
    }))
    request = received(requests)

    assert result == {"success": True, "status": 200, "response": '{"id": 412}'}
    assert request["path"] == "/message"
    assert request["headers"]["X-Gotify-Key"] == "app-token-test"
    assert request["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert request["body"] == {
        "title": "Deployment",
        "message": "**Passed**",
        "priority": 8,
        "extras": {"client::display": {"contentType": "text/markdown"}},
    }
    assert "app-token-test" not in request["path"]
    assert "private" not in json.dumps(result)
    assert "**Passed**" not in json.dumps(result)


def test_bad_application_token_returns_401_without_reflecting_server_body(gotify_http, monkeypatch):
    send, requests = gotify_http
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "bad-token")

    result = json.loads(send({"message": "hi"}))

    assert result == {"success": False, "status": 401, "error": "Gotify returned HTTP 401"}
    assert received(requests)["headers"]["X-Gotify-Key"] == "bad-token"
    assert "private" not in json.dumps(result)


def test_503_response_is_not_mistaken_for_success(gotify_http):
    send, requests = gotify_http

    result = json.loads(send({"message": "service unavailable"}))

    assert received(requests)["body"]["message"] == "service unavailable"
    assert result == {"success": False, "status": 503, "error": "Gotify returned HTTP 503"}
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("message", ["", "  ", "\n\t"])
def test_blank_message_is_rejected_before_network_request(gotify_http, message):
    send, requests = gotify_http

    result = json.loads(send({"message": message}))

    assert result == {"success": False, "error": "message must not be empty"}
    assert requests.empty()
