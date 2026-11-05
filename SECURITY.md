# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in this plugin, please report it responsibly.

**Do NOT open a public GitHub issue.**

Instead, submit a **private vulnerability report** via [GitHub Security Advisories](https://github.com/redoracle/hermes-plugin-gotify-notify/security/advisories/new). Do not put proof-of-concept code, credentials, or exploit details into a public issue or pull request.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)
- Your name/handle for credit (optional)

### Disclosure coordination

A maintainer will review private reports as capacity permits and coordinate remediation and disclosure with the reporter. No fixed SLA or guaranteed response timeframe is represented. Include the affected version, impact, a minimal reproducer and suggested mitigation where possible.

## Security Measures

### Secrets handling

- All credentials (`GOTIFY_APP_TOKEN`, `GOTIFY_URL`) are read from environment variables — never hardcoded, never logged.
- The application token is sent only in `X-Gotify-Key`, using `add_unredirected_header` so `urllib` does not copy it when following redirects.
- Responses do not echo HTTP error bodies, arbitrary successful response bodies, or raw exceptions that might contain secrets. A successful response is read with an 8 KiB limit and reports only a validated numeric message ID.

### Input validation

| Input | Validation |
|-------|------------|
| `GOTIFY_URL` | Requires an absolute HTTP(S) URL without credentials, query parameters, fragments, whitespace or a malformed port. |
| `GOTIFY_APP_TOKEN` | Rejects embedded whitespace and ASCII control characters. |
| `GOTIFY_CONTENT_TYPE` | Allowlist: `text/markdown`, `text/plain`. Invalid values fall back to `text/markdown`. |
| `GOTIFY_TIMEOUT` | Parsed as integer, clamped to 1–60. Invalid values fall back to 10. |
| `title` | Truncated to 120 characters. |
| `message` | Truncated to 4000 characters. |
| `priority` | Clamped to 1–10. |

### Dependency surface

- **Zero runtime dependencies** — the plugin uses only the Python standard library. Development, build, and release tooling still carry supply-chain risk and are tested separately.

### Network safety

- All HTTP requests use a bounded timeout (default: 10 seconds, max: 60), and successful response reads are capped at 8 KiB plus a one-byte overflow sentinel.
- The initial POST targets `{GOTIFY_URL}/message`. urllib may follow HTTP redirects, but its redirected requests **do not include** the Gotify token.
- Use HTTPS outside a trusted local network; Python's default TLS certificate validation remains enabled.
- The base URL is validated and trailing slashes are removed. Never configure it with an untrusted endpoint.

### What the plugin does NOT do

- Does not log `GOTIFY_APP_TOKEN` or `GOTIFY_URL`.
- Does not store credentials to disk.
- Does not intentionally initiate requests to endpoints other than the configured `/message` URL. Python's redirect handler can follow HTTP redirects without the token; use a canonical Gotify URL to avoid redirects.
- Does not execute shell commands.
- Does not import or use `eval`, `exec`, `subprocess`, or `pickle`.
