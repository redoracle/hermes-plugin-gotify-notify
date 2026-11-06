# Gotify notifications for Hermes Agent

[![CI](https://github.com/redoracle/hermes-plugin-gotify-notify/actions/workflows/ci.yml/badge.svg)](https://github.com/redoracle/hermes-plugin-gotify-notify/actions/workflows/ci.yml)
[![CodeQL](https://github.com/redoracle/hermes-plugin-gotify-notify/actions/workflows/codeql.yml/badge.svg)](https://github.com/redoracle/hermes-plugin-gotify-notify/actions/workflows/codeql.yml)
[![Python 3.11–3.14](https://img.shields.io/badge/Python-3.11--3.14-blue)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

A lightweight, dependency-free [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that delivers actionable push notifications through [Gotify](https://gotify.net/). It exposes one tool, `gotify_send`, and uses Gotify's native Markdown rendering support.

**Designed for important events**, not routine tool chatter: task completions, failures, security findings, human approvals, quota/budget alerts, and concise summaries.

## Highlights

- **No runtime third-party packages**: Python standard library only.
- **Safer authentication**: sends the application token in an `X-Gotify-Key` header, never as a URL parameter; the credential is not forwarded on HTTP redirects.
- **Bounded inputs and network operations**: 120-character title, 4,000-character message, priority 1–10, timeout 1–60 seconds, and 8 KiB maximum server response read.
- **Privacy-conscious results**: a structured JSON result reports status and, when available, only the Gotify message ID; server-supplied message text and raw failure details are not echoed back.
- **Configurable rendering**: Markdown by default, with plain-text support.
- **Cross-platform test coverage**: Python 3.11–3.14 on Linux and macOS in GitHub Actions.

## Quick start

### 1. Install the plugin

For an existing Hermes installation, prefer the [Hermes plugin manager](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) or install the package **into the Python environment that runs Hermes**:

```bash
python -m pip install git+https://github.com/redoracle/hermes-plugin-gotify-notify.git
```

Alternatively, install as a directory plugin (copy the **package directory**, not the entire Git repository):

```bash
git clone https://github.com/redoracle/hermes-plugin-gotify-notify.git
mkdir -p ~/.hermes/plugins
cp -R hermes-plugin-gotify-notify/gotify_notify ~/.hermes/plugins/gotify-notify
```

The directory at `~/.hermes/plugins/gotify-notify/` must contain both `__init__.py` and `plugin.yaml`. The repository root is **not** itself a Hermes plugin directory.

### 2. Configure Gotify

Create a Gotify **Application** in its web UI, then add these values to `~/.hermes/.env`:

```dotenv
GOTIFY_URL=https://gotify.example.com
GOTIFY_APP_TOKEN=replace-with-your-application-token

# Optional:
GOTIFY_CONTENT_TYPE=text/markdown
GOTIFY_TIMEOUT=10
```

For a reverse-proxy prefix, use a canonical base URL such as `https://gotify.example.com/gotify`. The plugin appends `/message` itself. **Use HTTPS on untrusted networks**; plain HTTP is supported for explicitly trusted local deployments.

### 3. Enable and verify

Plugins are **opt-in**: installing the Python package makes it discoverable but does not enable it. Enable the plugin through Hermes, or add its name to `~/.hermes/config.yaml`:

```bash
hermes plugins enable gotify-notify
hermes plugins list
hermes plugins doctor gotify-notify --ci
```

```yaml
plugins:
  enabled:
    - gotify-notify
```

Restart Hermes if required by your deployment (`hermes gateway restart` for gateway mode). If using a managed Hermes environment, prefer its plugin installer so the package survives environment replacement. Refer to the official [plugin documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins).

### 4. Send a message

Ask Hermes:

> Send a Gotify notification titled "Deployment complete" with the message "**Staging** is healthy; see the deployment dashboard" at priority 5.

Hermes calls `gotify_send` with a JSON object, for example:

```json
{
  "title": "Deployment complete",
  "message": "**Staging** is healthy; see the deployment dashboard",
  "priority": 5
}
```

A successful tool response is JSON, for example:

```json
{"success": true, "status": 200, "response": "{\"id\": 42}"}
```

`response` is deliberately minimal: it contains a serialized message-ID object when Gotify provides a valid nonnegative integer `id`, or an empty string otherwise. A failure returns `{"success": false, "error": "..."}` and, for an HTTP failure, a `status` code. **No automatic retries** are performed: a retry after an ambiguous network failure could duplicate the notification.

## Configuration reference

| Environment variable | Required | Default | Behavior |
| --- | --- | --- | --- |
| `GOTIFY_URL` | Yes | — | Absolute HTTP(S) base URL; no embedded credentials, query or fragment |
| `GOTIFY_APP_TOKEN` | Yes | — | Gotify **Application** token, never a client or administrator password |
| `GOTIFY_CONTENT_TYPE` | No | `text/markdown` | `text/markdown` or `text/plain` (invalid values fall back to Markdown) |
| `GOTIFY_TIMEOUT` | No | `10` | Integer seconds; clamped to 1–60 |

Tool parameters: `message` (required string, truncated to 4,000 characters), `title` (optional, defaults to `Hermes`, truncated to 120 characters), and `priority` (optional, defaults to 5, clamped to 1–10). Common priorities: 2 informational, 5 important, 8 urgent, 10 critical.

## Architecture and security

```text
Hermes Agent  →  gotify_send  →  validation / bounded JSON  →  HTTPS POST /message
                                                          X-Gotify-Key header
                                                        →  Gotify server / clients
```

The `register(ctx)` entry point provides the Hermes tool. Authentication is based only on operator-supplied environment configuration; agent-provided parameters **cannot change the destination or token**. The plugin does not persist credentials or maintain a queue. Redirected requests do not inherit the authentication header.

- [Architecture and trust boundaries](docs/ARCHITECTURE.md)
- [Security policy and private vulnerability reporting](SECURITY.md)
- [Operational troubleshooting](SUPPORT.md)
- [Release process](docs/RELEASING.md)

## Android companion utility

The optional [`gotify-androidctl`](utils/gotify-androidctl/README.md) helps provision Gotify applications, icons, sounds, notification channels, and Android drift audits. It is **independent of the Python plugin** and has hardware/system dependencies (`adb`, and optionally FFmpeg). Review its [full guide](utils/gotify-androidctl/README.md) and [security policy](utils/gotify-androidctl/SECURITY.md) before making changes to a connected device.

## Development and verification

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest tests/ --cov=gotify_notify --cov-report=term-missing --cov-fail-under=95
python -m ruff check gotify_notify tests
python scripts/sync_version.py --check
python -m compileall -q gotify_notify tests scripts
```

Unit tests use mocks and deterministic loopback HTTP without external credentials. A separate CI job additionally runs the plugin against disposable **real Gotify 2.9.1 and 3.1.1 servers**, checking persisted messages and authentication. The Android job exercises provisioning, token rotation, and **mandatory FFmpeg/Vorbis conversion**; genuine device/OEM workflows remain separately gated. See [testing architecture and integration setup](docs/TESTING.md). See [CONTRIBUTING.md](CONTRIBUTING.md) and the [CI workflow](.github/workflows/ci.yml).

## Project governance

- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Support](SUPPORT.md)
- [Security](SECURITY.md) · [License](LICENSE) · [Changelog](CHANGELOG.md)

MIT licensed. Maintained by [redoracle](https://github.com/redoracle).
