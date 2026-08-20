# hermes-plugin-gotify-notify

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/redoracle/hermes-plugin-gotify-notify/actions/workflows/ci.yml/badge.svg)](https://github.com/redoracle/hermes-plugin-gotify-notify/actions/workflows/ci.yml)

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that sends high-value, actionable notifications to a [Gotify](https://gotify.net/) server. Messages are rendered as **markdown** in the Gotify client by default.

---

## Features

- **Markdown rendering** — messages include `extras.client::display.contentType: text/markdown` so the Gotify client renders **bold**, _italic_, `code`, [links](https://gotify.net), lists, and headings natively.
- **Configurable content type** — set `GOTIFY_CONTENT_TYPE=text/plain` to disable markdown.
- **Zero external dependencies** — uses only Python stdlib (`urllib.request`).
- **Configurable timeout** — `GOTIFY_TIMEOUT` env var (1–60 seconds, default: 10).
- **Input safety** — title truncated to 120 chars, message to 4000 chars, priority clamped to 1–10, token URL-encoded, content type validated against an allowlist.
- **Clean error handling** — missing env vars, HTTP errors, and connection failures all return structured JSON with `success: false` and an error message — no crashes.

## Installation

### Option A: Clone into `~/.hermes/plugins/`

```bash
git clone https://github.com/redoracle/hermes-plugin-gotify-notify.git \
  ~/.hermes/plugins/gotify-notify
```

### Option B: Install via pip

```bash
pip install git+https://github.com/redoracle/hermes-plugin-gotify-notify.git
```

The pip entry point (`hermes_agent.plugins`) auto-registers the plugin with Hermes' discovery system — no manual config needed.

## Configuration

Add the following to `~/.hermes/.env`:

```bash
# Required
GOTIFY_URL=http://gotify.local
GOTIFY_APP_TOKEN=your_application_token

# Optional
GOTIFY_CONTENT_TYPE=text/markdown   # or text/plain (default: text/markdown)
GOTIFY_TIMEOUT=10                    # seconds, 1-60 (default: 10)
```

### Enable in config.yaml

```yaml
plugins:
  enabled:
    - gotify-notify
```

### Restart Hermes

```bash
hermes gateway restart    # gateway mode
# or exit and relaunch the CLI
```

## Usage

The agent calls `gotify_send` automatically when appropriate — completed long-running tasks, failures, security findings, approval requests, etc.

You can also trigger it manually:

> Send a gotify notification with title "Deploy complete" and message "Build **#42** succeeded on [staging](https://staging.example.com)"

### Gotify Application Token

1. Open your Gotify web UI.
2. Go to **Apps** → **Create Application**.
3. Copy the **Application Token**.
4. Set it as `GOTIFY_APP_TOKEN` in `~/.hermes/.env`.

## Android provisioning utility

[`utils/gotify-androidctl`](utils/gotify-androidctl/) is an optional companion utility for operating the Gotify Android client alongside this plugin. It provisions the category Applications used by the plugin, uploads their images, deploys category sounds to Android, configures notification channels, and audits configuration drift.

The plugin is the versioned deliverable (`pyproject.toml` is the source of truth). `gotify-androidctl` has no independent release version; its reports identify the utility by name only.

### Typical use cases

- Bootstrap a new Gotify server and Android device with the PAGER, SECURITY, INFRA, PLATFORM, AUTOMATION, DEV, DIGEST, MONEY IN/OUT, and TRADING categories.
- Synchronize the icons in [`utils/icons`](utils/icons/) to their corresponding Gotify Applications.
- Convert and deploy category sounds from [`utils/sounds`](utils/sounds/) to the connected Android device.
- Create, inspect, configure, and audit the Gotify Android notification channels for each category.
- Perform an explicit, confirmed Gotify Application-token rotation.

### Usage

Run commands from the repository root. The generated configuration resolves `assets.root: ".."` relative to its own location, so it continues to point at `./utils` regardless of the process working directory.

```bash
# Create a configuration without putting secrets in JSON. In a terminal this
# starts a wizard for the Gotify URL and environment-variable names.
./utils/gotify-androidctl/gotify-androidctl setup \
  --output ./utils/gotify-androidctl/gotify-android.json

# Edit the Gotify URL and credential environment-variable names, then verify paths and prerequisites.
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json show-config
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json doctor

# Preview the complete mutation plan, then provision apps, images, sounds, and channels.
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json --dry-run bootstrap
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json bootstrap --require-icons

# Reconcile only icons, then audit Android/Gotify drift in CI or scheduled jobs.
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json icons
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json --non-interactive --strict audit --fail-on-drift
```

If an interactive command references a missing `-c` file, the utility starts the same setup wizard, writes the configuration, and exits without provisioning. In CI or another non-interactive environment it exits with a safe, copyable `setup --non-interactive --gotify-url ...` command instead.

### Constraints and safety

- Requires `adb`, `curl`, and a connected Android device with USB or wireless debugging enabled. `ffmpeg` is required only when conversion to the selected audio format is needed. OGG deployment requires an FFmpeg Vorbis encoder (`libvorbis` or native `vorbis`); verify with `ffmpeg -hide_banner -encoders | rg 'libvorbis| vorbis'`.
- Gotify Application provisioning and token rotation require Gotify management credentials; rotate tokens only with `--confirm-token-rotation`.
- Android 8+ channel sound and importance settings become user-controlled after channel creation. The utility uses supported Settings intents and semantic UI automation, then falls back to guided mode rather than changing private Android databases.
- Icon and sound configuration values are filename-only and cannot escape the configured `./utils/icons` and `./utils/sounds` directories. Audio sources are never overwritten, ADB uploads are hash-verified by default, and normal reports redact tokens.
- The full local self-test exercises WAV-to-OGG conversion. Install FFmpeg with a Vorbis encoder before running it; the utility prefers `libvorbis` and automatically falls back to native `vorbis` (with stereo conversion) when available.

See the [gotify-androidctl guide](utils/gotify-androidctl/README.md) for the complete command and configuration reference.

## Environment Variables

| Variable              | Required | Default         | Description                                                          |
| --------------------- | -------- | --------------- | -------------------------------------------------------------------- |
| `GOTIFY_URL`          | Yes      | —               | Gotify server base URL                                               |
| `GOTIFY_APP_TOKEN`    | Yes      | —               | Application token from Gotify                                        |
| `GOTIFY_CONTENT_TYPE` | No       | `text/markdown` | Content-Type for message rendering (`text/markdown` or `text/plain`) |
| `GOTIFY_TIMEOUT`      | No       | `10`            | Request timeout in seconds (1–60)                                    |

## Tool Schema

| Parameter  | Type    | Required | Default  | Description                                                        |
| ---------- | ------- | -------- | -------- | ------------------------------------------------------------------ |
| `message`  | string  | Yes      | —        | Notification body (markdown, max 4000 chars)                       |
| `title`    | string  | No       | `Hermes` | Notification title (max 120 chars)                                 |
| `priority` | integer | No       | `5`      | Gotify priority (1–10; 2=info, 5=important, 8=urgent, 10=critical) |

## How It Works

The plugin registers a `gotify_send` tool with the Hermes `PluginManager`. When the agent decides a notification is warranted, it calls the tool with a title, message, and priority. The plugin:

1. Reads `GOTIFY_URL` and `GOTIFY_APP_TOKEN` from the environment.
2. Constructs a JSON payload with the message, title, priority, and `extras.client::display.contentType`.
3. POSTs to `{GOTIFY_URL}/message?token={GOTIFY_APP_TOKEN}`.
4. Returns a JSON result with `success`, `status`, and `response` (or `error`).

The markdown rendering uses Gotify's [message extras](https://gotify.net/docs/msgextras#clientdisplay) — specifically the `client::display.contentType` field. This is a documented Gotify feature, not a hack.

## Security

- **No secrets in code** — all credentials are read from environment variables.
- **Token URL-encoded** — the application token is fully URL-encoded via `urllib.parse.quote(token, safe='')`.
- **Content type allowlist** — `GOTIFY_CONTENT_TYPE` is validated against `{"text/markdown", "text/plain"}`; invalid values fall back to the default.
- **Timeout bounded** — `GOTIFY_TIMEOUT` is clamped to 1–60 seconds; invalid values fall back to 10.
- **No logging of secrets** — the plugin never logs the token or URL.
- **Stdlib only** — no third-party dependencies to audit.

See [SECURITY.md](SECURITY.md) for the full security policy and vulnerability reporting instructions.

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=gotify_notify --cov-report=term-missing
```

All 30 tests pass with zero network calls (HTTP is mocked via `unittest.mock`).

## Compatibility

- Hermes Agent v0.18+
- Python 3.11, 3.12, 3.13
- Any OS that runs Hermes (Linux, macOS, Windows)

## License

[MIT](LICENSE) — © 2026 redoracle

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Pull requests, bug reports, and feature suggestions are welcome.
