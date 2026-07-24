# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in this plugin, please report it responsibly.

**Do NOT open a public GitHub issue.**

Instead, email: **security@redoracle.dev** (if available) or send a private vulnerability report via [GitHub Security Advisories](https://github.com/redoracle/hermes-plugin-gotify-notify/security/advisories/new).

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)
- Your name/handle for credit (optional)

### Response timeline

| Step | Target |
|------|--------|
| Acknowledgment | Within 48 hours |
| Initial assessment | Within 7 days |
| Fix or mitigation | Within 30 days (severity-dependent) |
| Public disclosure | After fix is released, coordinated with reporter |

## Security Measures

### Secrets handling

- All credentials (`GOTIFY_APP_TOKEN`, `GOTIFY_URL`) are read from environment variables — never hardcoded, never logged.
- The application token is URL-encoded via `urllib.parse.quote(token, safe='')` before being placed in the query string.

### Input validation

| Input | Validation |
|-------|------------|
| `GOTIFY_CONTENT_TYPE` | Allowlist: `text/markdown`, `text/plain`. Invalid values fall back to `text/markdown`. |
| `GOTIFY_TIMEOUT` | Parsed as integer, clamped to 1–60. Invalid values fall back to 10. |
| `title` | Truncated to 120 characters. |
| `message` | Truncated to 4000 characters. |
| `priority` | Clamped to 1–10. |

### Dependency surface

- **Zero runtime dependencies** — the plugin uses only Python stdlib (`urllib.request`, `json`, `os`, `urllib.parse`). No supply chain risk from third-party packages.

### Network safety

- All HTTP requests use a bounded timeout (default: 10 seconds, max: 60).
- The plugin POSTs only to `{GOTIFY_URL}/message` — no other endpoints.
- No user input is passed unsanitized to the URL. The token is URL-encoded; the base URL is stripped of trailing slashes.

### What the plugin does NOT do

- Does not log `GOTIFY_APP_TOKEN` or `GOTIFY_URL`.
- Does not store credentials to disk.
- Does not make requests to any endpoint other than `/message`.
- Does not execute shell commands.
- Does not import or use `eval`, `exec`, `subprocess`, or `pickle`.
