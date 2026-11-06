"""Security and input-validation regression tests for the Gotify plugin."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from gotify_notify import _normalize_base_url, _send_request, register


class FakeContext:
    def register_tool(self, name, toolset, schema, handler, description):
        self.schema = schema
        self.handler = handler


@pytest.fixture
def send(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "https://gotify.example/api")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "super-secret-token")
    context = FakeContext()
    register(context)
    return context.handler


def test_header_authentication_does_not_expose_token_in_url(send):
    response = MagicMock(status=200)
    response.read.return_value = b'{"id":10}'
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response) as opener:
        assert json.loads(send({"message": "hello"}))["success"] is True
        request = opener.call_args.args[0]
        assert request.full_url == "https://gotify.example/api/message"
        assert "super-secret-token" not in request.full_url
        assert request.get_header("X-gotify-key") == "super-secret-token"
        assert "X-gotify-key" in request.unredirected_hdrs
        assert "X-gotify-key" not in request.headers


def test_redirect_cannot_forward_gotify_token():
    request = urllib.request.Request(
        "https://gotify.example/message", data=b"{}", method="POST"
    )
    request.add_unredirected_header("X-Gotify-Key", "secret")
    redirected = urllib.request.HTTPRedirectHandler().redirect_request(
        request, None, 302, "Found", {}, "https://other.example/collect"
    )
    assert redirected is not None
    assert redirected.get_header("X-gotify-key") is None
    assert "secret" not in str(redirected.headers)


@pytest.mark.parametrize("value", [
    "example.com", "ftp://gotify.example", "http://user:pass@gotify.example",
    "https://gotify.example?foo=bar", "https://gotify.example/#fragment",
    "https://gotify.example:invalid", "https://[invalid", "http://gotify.example\nEvil",
])
def test_invalid_urls_are_rejected(value):
    assert _normalize_base_url(value) is None


def test_reverse_proxy_path_is_preserved():
    assert _normalize_base_url("https://gotify.example/api/") == "https://gotify.example/api"


@pytest.mark.parametrize("value", [
    "http://bad:pw@gotify.example", "https://gotify.example/?debug=1", "just-a-host"
])
def test_invalid_env_does_not_trigger_a_request(send, monkeypatch, value):
    monkeypatch.setenv("GOTIFY_URL", value)
    with patch("urllib.request.urlopen") as opener:
        data = json.loads(send({"message": "hello"}))
    assert data["success"] is False
    assert "Invalid GOTIFY_URL" in data["error"]
    opener.assert_not_called()


def test_bad_token_is_rejected_before_http(send, monkeypatch):
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "abc\r\nHeader: injected")
    with patch("urllib.request.urlopen") as opener:
        data = json.loads(send({"message": "hello"}))
    assert data["success"] is False
    assert "GOTIFY_APP_TOKEN" in data["error"]
    opener.assert_not_called()


@pytest.mark.parametrize("params", [{}, {"message": None}, {"message": 123}, None])
def test_invalid_message_returns_structured_error(send, params):
    with patch("urllib.request.urlopen") as opener:
        data = json.loads(send(params))
    assert data == {"success": False, "error": "message must be a string"}
    opener.assert_not_called()


def test_http_error_body_does_not_reflect_server_content():
    error = urllib.error.HTTPError(
        "https://gotify.example/message", 403, "secret-token", {}, None
    )
    with patch("urllib.request.urlopen", side_effect=error):
        result = _send_request("https://gotify.example", "secret-token", {}, 10)
    assert result == {"success": False, "status": 403, "error": "Gotify returned HTTP 403"}
    assert "secret-token" not in json.dumps(result)


def test_url_error_text_does_not_reflect_credential():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("secret-token")):
        result = _send_request("https://gotify.example", "secret-token", {}, 10)
    assert result["success"] is False
    assert "secret-token" not in json.dumps(result)


def test_unexpected_error_text_does_not_reflect_credential():
    with patch("urllib.request.urlopen", side_effect=RuntimeError("secret-token")):
        result = _send_request("https://gotify.example", "secret-token", {}, 10)
    assert result == {"success": False, "error": "Gotify request failed (RuntimeError)"}


def test_empty_title_defaults_to_hermes(send):
    response = MagicMock(status=200)
    response.read.return_value = b"{}"
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response) as opener:
        send({"message": "hello", "title": "   "})
    payload = json.loads(opener.call_args.args[0].data)
    assert payload["title"] == "Hermes"


def test_success_body_is_bounded_and_response_is_minimal(send):
    response = MagicMock(status=201)
    response.read.return_value = b'{"id": 42, "message": "secret-notification", "title": "test"}'
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response):
        result = json.loads(send({"message": "secret-notification"}))
    assert result == {"success": True, "status": 201, "response": '{"id": 42}'}
    response.read.assert_called_once_with(8193)
    assert "secret-notification" not in json.dumps(result)


def test_success_response_never_reflects_token(send):
    response = MagicMock(status=200)
    response.read.return_value = b'{"id": 7, "token": "super-secret-token"}'
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response):
        result = json.loads(send({"message": "safe"}))
    assert result["response"] == '{"id": 7}'
    assert "super-secret-token" not in json.dumps(result)


@pytest.mark.parametrize("body", [b"not-json", b"{" + b"x" * 9000 + b"}", b'{"id": "bad"}', b'{"id": true}'])
def test_invalid_or_large_success_responses_are_not_reflected(send, body):
    response = MagicMock(status=200)
    response.read.return_value = body
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response):
        result = json.loads(send({"message": "hello"}))
    assert result["success"] is True
    assert result["response"] == ""
 
@pytest.mark.parametrize("priority", [float("inf"), float("-inf"), "1e9999", None])
def test_invalid_priority_falls_back_to_default_without_crashing(send, priority):
    response = MagicMock(status=200)
    response.read.return_value = b'{"id": 16}'
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response) as opener:
        result = json.loads(send({"message": "Deployment finished", "priority": priority}))
    assert result == {"success": True, "status": 200, "response": '{"id": 16}'}
    assert json.loads(opener.call_args.args[0].data)["priority"] == 5
