"""Test suite for the gotify-notify Hermes Agent plugin.

Covers:
  * Registration contract — tool name, toolset, schema, required fields.
  * Environment variable handling — missing required vars, optional vars.
  * Payload construction — markdown extras, content-type override, title
    truncation, message truncation, priority clamping, default title.
  * HTTP success and failure paths (mocked urllib.request.urlopen).
  * URL construction and token encoding.
  * Timeout parsing and clamping.
  * Edge cases — empty message, non-integer priority, invalid content type.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# --------------------------------------------------------------------------- #
# Plugin loader
# --------------------------------------------------------------------------- #

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_DIR = _REPO_ROOT / "gotify_notify"


def _load_plugin():
    """Import the gotify_notify package directly from the repo path."""
    spec = importlib.util.spec_from_file_location(
        "gotify_notify_under_test",
        _PLUGIN_DIR / "__init__.py",
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class _FakeCtx:
    """Minimal plugin context that captures the registered tool."""

    def __init__(self):
        self.tools: dict[str, dict] = {}

    def register_tool(self, name, toolset, schema, handler, description):
        self.tools[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "description": description,
        }


@pytest.fixture
def fake_ctx():
    return _FakeCtx()


@pytest.fixture
def plugin(fake_ctx):
    """Load the plugin and register its tool against the fake context."""
    mod = _load_plugin()
    mod.register(fake_ctx)
    return fake_ctx


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove GOTIFY_* env vars before each test for predictability."""
    for var in ("GOTIFY_URL", "GOTIFY_APP_TOKEN", "GOTIFY_CONTENT_TYPE", "GOTIFY_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def env_set(monkeypatch):
    """Set standard Gotify env vars."""
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.test")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "testtoken123")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _mock_response(status=200, body=b'{"id":1}'):
    """Create a mock response object for urllib.request.urlopen."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _captured_request(mock_urlopen):
    """Extract the Request object passed to urlopen."""
    return mock_urlopen.call_args[0][0]


def _captured_body(mock_urlopen):
    """Parse the JSON body sent to urlopen."""
    req = _captured_request(mock_urlopen)
    return json.loads(req.data.decode())


# --------------------------------------------------------------------------- #
# Registration contract
# --------------------------------------------------------------------------- #


class TestRegistration:
    def test_registers_gotify_send(self, plugin):
        assert "gotify_send" in plugin.tools

    def test_toolset_name(self, plugin):
        assert plugin.tools["gotify_send"]["toolset"] == "gotify"

    def test_schema_name_matches(self, plugin):
        assert plugin.tools["gotify_send"]["schema"]["name"] == "gotify_send"

    def test_schema_requires_message(self, plugin):
        required = plugin.tools["gotify_send"]["schema"]["parameters"]["required"]
        assert "message" in required

    def test_schema_has_title_and_priority(self, plugin):
        props = plugin.tools["gotify_send"]["schema"]["parameters"]["properties"]
        assert "title" in props
        assert "priority" in props
        assert props["priority"]["default"] == 5

    def test_description_mentions_markdown(self, plugin):
        desc = plugin.tools["gotify_send"]["schema"]["description"]
        assert "markdown" in desc.lower()


# --------------------------------------------------------------------------- #
# Missing environment variables
# --------------------------------------------------------------------------- #


class TestMissingEnv:
    def test_missing_url_returns_error(self, plugin, monkeypatch):
        monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok")
        monkeypatch.delenv("GOTIFY_URL", raising=False)

        result = plugin.tools["gotify_send"]["handler"]({"message": "hi"})
        data = json.loads(result)
        assert data["success"] is False
        assert "GOTIFY_URL" in data["error"]

    def test_missing_token_returns_error(self, plugin, monkeypatch):
        monkeypatch.setenv("GOTIFY_URL", "http://gotify.test")
        monkeypatch.delenv("GOTIFY_APP_TOKEN", raising=False)

        result = plugin.tools["gotify_send"]["handler"]({"message": "hi"})
        data = json.loads(result)
        assert data["success"] is False
        assert "GOTIFY_APP_TOKEN" in data["error"]

    def test_missing_both_returns_error(self, plugin):
        result = plugin.tools["gotify_send"]["handler"]({"message": "hi"})
        data = json.loads(result)
        assert data["success"] is False


# --------------------------------------------------------------------------- #
# Payload construction
# --------------------------------------------------------------------------- #


class TestPayload:
    @patch("urllib.request.urlopen")
    def test_markdown_content_type_in_extras(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({
            "message": "Hello **world**",
            "title": "Test",
        })

        body = _captured_body(mock_urlopen)
        assert body["extras"]["client::display"]["contentType"] == "text/markdown"

    @patch("urllib.request.urlopen")
    def test_custom_content_type(self, mock_urlopen, plugin, env_set, monkeypatch):
        monkeypatch.setenv("GOTIFY_CONTENT_TYPE", "text/plain")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        body = _captured_body(mock_urlopen)
        assert body["extras"]["client::display"]["contentType"] == "text/plain"

    @patch("urllib.request.urlopen")
    def test_invalid_content_type_falls_back_to_default(self, mock_urlopen, plugin, env_set, monkeypatch):
        monkeypatch.setenv("GOTIFY_CONTENT_TYPE", "application/xml")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        body = _captured_body(mock_urlopen)
        assert body["extras"]["client::display"]["contentType"] == "text/markdown"

    @patch("urllib.request.urlopen")
    def test_title_truncation(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({
            "message": "hi",
            "title": "A" * 200,
        })

        body = _captured_body(mock_urlopen)
        assert len(body["title"]) == 120

    @patch("urllib.request.urlopen")
    def test_message_truncation(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "x" * 5000})

        body = _captured_body(mock_urlopen)
        assert len(body["message"]) == 4000

    @patch("urllib.request.urlopen")
    def test_priority_clamped_to_max(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({
            "message": "hi",
            "priority": 99,
        })

        body = _captured_body(mock_urlopen)
        assert body["priority"] == 10

    @patch("urllib.request.urlopen")
    def test_priority_clamped_to_min(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({
            "message": "hi",
            "priority": -5,
        })

        body = _captured_body(mock_urlopen)
        assert body["priority"] == 1

    @patch("urllib.request.urlopen")
    def test_default_title_is_hermes(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        body = _captured_body(mock_urlopen)
        assert body["title"] == "Hermes"

    @patch("urllib.request.urlopen")
    def test_custom_title(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({
            "message": "hi",
            "title": "[Sancho:Deploy] Build complete",
        })

        body = _captured_body(mock_urlopen)
        assert body["title"] == "[Sancho:Deploy] Build complete"


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #


class TestHTTP:
    @patch("urllib.request.urlopen")
    def test_success_returns_true(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response(status=200, body=b'{"id":42}')

        result = plugin.tools["gotify_send"]["handler"]({"message": "ok"})
        data = json.loads(result)
        assert data["success"] is True
        assert data["status"] == 200

    @patch("urllib.request.urlopen")
    def test_http_error_returns_false(self, mock_urlopen, plugin, env_set):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://gotify.test/message",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

        result = plugin.tools["gotify_send"]["handler"]({"message": "fail"})
        data = json.loads(result)
        assert data["success"] is False
        assert data["status"] == 401

    @patch("urllib.request.urlopen")
    def test_connection_error_returns_false(self, mock_urlopen, plugin, env_set):
        mock_urlopen.side_effect = ConnectionRefusedError("Connection refused")

        result = plugin.tools["gotify_send"]["handler"]({"message": "fail"})
        data = json.loads(result)
        assert data["success"] is False
        assert "Connection refused" in data["error"]

    @patch("urllib.request.urlopen")
    def test_url_construction(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})
        req = _captured_request(mock_urlopen)

        assert req.get_method() == "POST"
        assert "http://gotify.test/message" in req.full_url
        assert "token=testtoken123" in req.full_url

    @patch("urllib.request.urlopen")
    def test_content_type_header(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})
        req = _captured_request(mock_urlopen)

        assert req.headers["Content-type"] == "application/json; charset=utf-8"

    @patch("urllib.request.urlopen")
    def test_token_url_encoded(self, mock_urlopen, plugin, env_set, monkeypatch):
        """Token with special characters must be URL-encoded."""
        monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok+en&special=1")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})
        req = _captured_request(mock_urlopen)

        assert "token=tok%2Ben%26special%3D1" in req.full_url


# --------------------------------------------------------------------------- #
# Timeout handling
# --------------------------------------------------------------------------- #


class TestTimeout:
    @patch("urllib.request.urlopen")
    def test_default_timeout(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        assert mock_urlopen.call_args[1]["timeout"] == 10

    @patch("urllib.request.urlopen")
    def test_custom_timeout(self, mock_urlopen, plugin, env_set, monkeypatch):
        monkeypatch.setenv("GOTIFY_TIMEOUT", "30")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        assert mock_urlopen.call_args[1]["timeout"] == 30

    @patch("urllib.request.urlopen")
    def test_timeout_clamped_to_max(self, mock_urlopen, plugin, env_set, monkeypatch):
        monkeypatch.setenv("GOTIFY_TIMEOUT", "120")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        assert mock_urlopen.call_args[1]["timeout"] == 60

    @patch("urllib.request.urlopen")
    def test_timeout_clamped_to_min(self, mock_urlopen, plugin, env_set, monkeypatch):
        monkeypatch.setenv("GOTIFY_TIMEOUT", "0")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        assert mock_urlopen.call_args[1]["timeout"] == 1

    @patch("urllib.request.urlopen")
    def test_invalid_timeout_falls_back(self, mock_urlopen, plugin, env_set, monkeypatch):
        monkeypatch.setenv("GOTIFY_TIMEOUT", "not-a-number")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})

        assert mock_urlopen.call_args[1]["timeout"] == 10


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


class TestEdgeCases:
    @patch("urllib.request.urlopen")
    def test_empty_message_still_sends(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        result = plugin.tools["gotify_send"]["handler"]({"message": ""})
        data = json.loads(result)
        assert data["success"] is True

    @patch("urllib.request.urlopen")
    def test_non_integer_priority_falls_back(self, mock_urlopen, plugin, env_set):
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({
            "message": "hi",
            "priority": "high",
        })

        body = _captured_body(mock_urlopen)
        # int("high") raises ValueError, which should be caught
        # If it doesn't fall back, the test will error — that's correct

    @patch("urllib.request.urlopen")
    def test_url_with_trailing_slash_stripped(self, mock_urlopen, plugin, env_set, monkeypatch):
        monkeypatch.setenv("GOTIFY_URL", "http://gotify.test/")
        mock_urlopen.return_value = _mock_response()

        plugin.tools["gotify_send"]["handler"]({"message": "hi"})
        req = _captured_request(mock_urlopen)

        assert "gotify.test/message" in req.full_url
        assert "//message" not in req.full_url
