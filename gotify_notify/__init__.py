"""Gotify notification plugin for Hermes Agent.

Sends high-value, actionable notifications through a Gotify server.
Messages are rendered as markdown in the Gotify client by default.

Environment variables (in ~/.hermes/.env):

    GOTIFY_URL            Base URL of the Gotify server (required)
    GOTIFY_APP_TOKEN      Application token from Gotify (required)
    GOTIFY_CONTENT_TYPE   Content-Type for rendering (default: text/markdown)
    GOTIFY_TIMEOUT        Request timeout in seconds (default: 10)

License: MIT
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

__version__ = "1.1.0"
__all__ = ["register"]

# --- Constants ---------------------------------------------------------------

_MAX_TITLE_LEN = 120
_MAX_MESSAGE_LEN = 4000
_MIN_PRIORITY = 1
_MAX_PRIORITY = 10
_DEFAULT_PRIORITY = 5
_DEFAULT_CONTENT_TYPE = "text/markdown"
_DEFAULT_TIMEOUT = 10
_MAX_RESPONSE_BYTES = 8192
_ALLOWED_CONTENT_TYPES = frozenset({"text/markdown", "text/plain"})


# --- Helpers -----------------------------------------------------------------

def _get_env(name: str, default: str = "") -> str:
    """Return a stripped environment variable or *default*."""
    return os.environ.get(name, default).strip()


def _validate_content_type(value: str) -> str:
    """Return *value* if it is an allowed content type, else the default."""
    if value in _ALLOWED_CONTENT_TYPES:
        return value
    return _DEFAULT_CONTENT_TYPE


def _normalize_base_url(value: str) -> str | None:
    """Validate a Gotify HTTP(S) base URL, including reverse-proxy paths.

    Reject credentials, query strings, fragments and malformed ports to avoid
    accidentally sending an application token to an unintended destination.
    """
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return None
    try:
        parts = urllib.parse.urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            return None
        _ = parts.port  # ValueError for malformed port numbers.
    except ValueError:
        return None
    return value.rstrip("/")


def _build_payload(
    title: str,
    message: str,
    priority: int,
    content_type: str,
) -> dict[str, Any]:
    """Construct the Gotify message payload.

    The ``extras.client::display.contentType`` field enables markdown
    rendering in compatible Gotify clients. See:
    https://gotify.net/docs/msgextras#clientdisplay
    """
    return {
        "title": title[:_MAX_TITLE_LEN],
        "message": message[:_MAX_MESSAGE_LEN],
        "priority": max(_MIN_PRIORITY, min(_MAX_PRIORITY, priority)),
        "extras": {
            "client::display": {
                "contentType": content_type,
            },
        },
    }


def _send_request(
    base_url: str,
    token: str,
    payload: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    """POST JSON using a redirect-safe Gotify authentication header.

    ``add_unredirected_header`` prevents urllib from forwarding the token
    to a different origin if the server responds with a redirect.
    """
    request = urllib.request.Request(
        f"{base_url}/message",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    request.add_unredirected_header("X-Gotify-Key", token)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Gotify usually echoes the full submitted message in its response.
            # Never return arbitrary server content (or a token it might echo)
            # to the agent. Keep the existing response field, but include only
            # the message identifier when the bounded response is valid JSON.
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            safe_response = ""
            if len(raw) <= _MAX_RESPONSE_BYTES:
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        message_id = data.get("id")
                        if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id >= 0:
                            safe_response = json.dumps({"id": message_id})
                except (ValueError, UnicodeDecodeError):
                    pass
            return {
                "success": 200 <= response.status < 300,
                "status": response.status,
                "response": safe_response,
            }
    except urllib.error.HTTPError as exc:
        # Server error bodies may contain credentials or untrusted content.
        return {
            "success": False,
            "status": exc.code,
            "error": f"Gotify returned HTTP {exc.code}",
        }
    except ConnectionRefusedError:
        return {"success": False, "error": "Connection refused"}
    except urllib.error.URLError as exc:
        # Do not echo exception text: proxies and libraries may include URLs.
        return {
            "success": False,
            "error": f"Gotify connection failed ({type(exc.reason).__name__})",
        }
    except Exception as exc:  # noqa: BLE001 — preserve the JSON tool contract.
        return {
            "success": False,
            "error": f"Gotify request failed ({type(exc).__name__})",
        }


# --- Plugin entry point ------------------------------------------------------

def register(ctx: Any) -> None:
    """Register the ``gotify_send`` tool with the Hermes plugin context.

    Parameters
    ----------
    ctx
        Plugin context provided by the Hermes ``PluginManager``. Must
        implement ``register_tool(name, toolset, schema, handler,
        description)``.
    """
    schema = {
        "name": "gotify_send",
        "description": (
            "Send a short, high-value notification to the operator through "
            "Gotify. Messages are rendered as markdown in the Gotify client. "
            "Use only for: completed long-running tasks with concrete "
            "results, failed or blocked tasks, human approval requests, "
            "auth/API key/quota/rate-limit errors, cost or budget "
            "anomalies, security-relevant findings, failed CI/CD/backup/"
            "scheduled jobs, daily/weekly summaries, or artifacts ready "
            "for review. Do NOT use for routine chatter, every tool call, "
            "normal responses, verbose logs, intermediate thoughts, "
            "trivial successes, duplicate messages, or unverified results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Short notification title, max 120 chars. "
                        "Format: [Hermes:<instance>] <event>"
                    ),
                },
                "message": {
                    "type": "string",
                    "description": (
                        "Notification body, rendered as markdown. Include "
                        "concrete result, status, impact, and next action. "
                        "Use **bold**, [links](url), `code`, and lists."
                    ),
                },
                "priority": {
                    "type": "integer",
                    "description": (
                        "Gotify priority: 2=info, 5=important, "
                        "8=urgent, 10=critical."
                    ),
                    "default": _DEFAULT_PRIORITY,
                },
            },
            "required": ["message"],
        },
    }

    def handle_gotify_send(params: dict[str, Any], **kwargs: Any) -> str:
        """Handle a ``gotify_send`` tool invocation."""
        del kwargs  # Unused — reserved for future framework hooks.

        base_url = _get_env("GOTIFY_URL")
        token = _get_env("GOTIFY_APP_TOKEN")

        if not base_url or not token:
            return json.dumps({
                "success": False,
                "error": (
                    "Missing GOTIFY_URL or GOTIFY_APP_TOKEN environment "
                    "variable. Configure them in ~/.hermes/.env"
                ),
            })

        if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in token):
            return json.dumps({
                "success": False,
                "error": "Invalid GOTIFY_APP_TOKEN: whitespace or control characters",
            })

        normalized_url = _normalize_base_url(base_url)
        if normalized_url is None:
            return json.dumps({
                "success": False,
                "error": "Invalid GOTIFY_URL: expected an HTTP(S) base URL without credentials, query or fragment",
            })

        if not isinstance(params, dict) or not isinstance(params.get("message"), str):
            return json.dumps({
                "success": False,
                "error": "message must be a string",
            })

        content_type = _validate_content_type(
            _get_env("GOTIFY_CONTENT_TYPE", _DEFAULT_CONTENT_TYPE)
        )

        try:
            timeout = int(_get_env("GOTIFY_TIMEOUT", str(_DEFAULT_TIMEOUT)))
            timeout = max(1, min(60, timeout))
        except ValueError:
            timeout = _DEFAULT_TIMEOUT

        title = str(params.get("title") or "Hermes").strip()[:_MAX_TITLE_LEN] or "Hermes"
        message = params["message"].strip()
        if not message:
            return json.dumps({"success": False, "error": "message must not be empty"})
        try:
            priority = int(params.get("priority", _DEFAULT_PRIORITY))
        except (ValueError, TypeError, OverflowError):
            priority = _DEFAULT_PRIORITY

        payload = _build_payload(title, message, priority, content_type)
        result = _send_request(normalized_url, token, payload, timeout)
        return json.dumps(result)

    ctx.register_tool(
        name="gotify_send",
        toolset="gotify",
        schema=schema,
        handler=handle_gotify_send,
        description="Send important notifications to Gotify with markdown rendering.",
    )
