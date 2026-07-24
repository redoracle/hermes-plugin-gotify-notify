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
import urllib.parse
import urllib.request
from typing import Any

__version__ = "1.0.0"
__all__ = ["register"]

# --- Constants ---------------------------------------------------------------

_MAX_TITLE_LEN = 120
_MAX_MESSAGE_LEN = 4000
_MIN_PRIORITY = 1
_MAX_PRIORITY = 10
_DEFAULT_PRIORITY = 5
_DEFAULT_CONTENT_TYPE = "text/markdown"
_DEFAULT_TIMEOUT = 10
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
    """POST *payload* to the Gotify server and return a result dict.

    The token is sent as a query parameter (Gotify's documented auth
    method). URL construction uses ``urllib.parse.quote`` with
    ``safe=''`` to ensure the token is fully URL-encoded.
    """
    url = f"{base_url}/message?token={urllib.parse.quote(token, safe='')}"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return {
                "success": 200 <= resp.status < 300,
                "status": resp.status,
                "response": body,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return {
            "success": False,
            "status": exc.code,
            "error": f"HTTP {exc.code}: {body[:500]}",
        }
    except Exception as exc:  # noqa: BLE001 — surface all errors to the agent
        return {
            "success": False,
            "error": str(exc),
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

        base_url = _get_env("GOTIFY_URL").rstrip("/")
        token = os.environ.get("GOTIFY_APP_TOKEN", "").strip()

        if not base_url or not token:
            return json.dumps({
                "success": False,
                "error": (
                    "Missing GOTIFY_URL or GOTIFY_APP_TOKEN environment "
                    "variable. Configure them in ~/.hermes/.env"
                ),
            })

        content_type = _validate_content_type(
            _get_env("GOTIFY_CONTENT_TYPE", _DEFAULT_CONTENT_TYPE)
        )

        try:
            timeout = int(_get_env("GOTIFY_TIMEOUT", str(_DEFAULT_TIMEOUT)))
            timeout = max(1, min(60, timeout))
        except ValueError:
            timeout = _DEFAULT_TIMEOUT

        title = str(params.get("title") or "Hermes").strip()[:_MAX_TITLE_LEN]
        message = str(params["message"]).strip()
        try:
            priority = int(params.get("priority", _DEFAULT_PRIORITY))
        except (ValueError, TypeError):
            priority = _DEFAULT_PRIORITY

        payload = _build_payload(title, message, priority, content_type)
        result = _send_request(base_url, token, payload, timeout)
        return json.dumps(result)

    ctx.register_tool(
        name="gotify_send",
        toolset="gotify",
        schema=schema,
        handler=handle_gotify_send,
        description="Send important notifications to Gotify with markdown rendering.",
    )
