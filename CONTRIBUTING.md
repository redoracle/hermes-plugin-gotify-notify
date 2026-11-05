# Contributing

Thank you for your interest in improving `hermes-plugin-gotify-notify`. This document covers everything you need to get started.

## Development Setup

```bash
git clone https://github.com/redoracle/hermes-plugin-gotify-notify.git
cd hermes-plugin-gotify-notify

# Create a virtual environment (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

## Running Tests

```bash
# Full suite
pytest tests/ -v

# With the CI coverage threshold
python -m pytest tests/ --cov=gotify_notify --cov-report=term-missing --cov-fail-under=95

# Python lint and syntax checks
python -m ruff check gotify_notify tests
python -m compileall -q gotify_notify tests scripts
python scripts/sync_version.py --check

# Companion CLI unit suite
python -m unittest discover -s utils/gotify-androidctl/tests -p 'test_androidctl.py'

# Single test class
pytest tests/test_gotify_notify.py::TestPayload -v
```

All tests use mocked HTTP — no live Gotify server is needed. Never add tests that make real network calls.

## Code Style

- **Ruff** enforces E4, E7, E9 and F checks on plugin and tests (line-length is not enforced).
- **Type hints** on all public functions.
- **Docstrings** on all public functions and classes (triple-quote, describe what, not how).
- **`from __future__ import annotations`** at the top of every Python file.
- **No external dependencies** — stdlib only. If you need a third-party package, justify it in the PR description.
- **Error handling** — keep the JSON response contract, read server bodies with bounded limits, and never echo untrusted server content or raw exceptions that could contain credentials.

## Pull Request Process

1. **Create a branch** from `main`:
   ```
   fix/description     # Bug fixes
   feat/description    # New features
   docs/description    # Documentation
   test/description    # Tests
   ```

2. **Write tests** for any new behavior. Every new code path must have test coverage.

3. **Run tests locally**:
   ```bash
   python -m pytest tests/ --cov=gotify_notify --cov-fail-under=95
   python -m ruff check gotify_notify tests
   ```

4. **Commit with conventional commits**:
   ```
   feat: add GOTIFY_PRIORITY_DEFAULT env var
   fix: handle empty GOTIFY_URL without crash
   test: add edge case for empty message
   docs: clarify header-based Gotify authentication
   ```

5. **Keep PRs focused** — one logical change per PR. Don't mix features with refactors.

6. **Describe what and why** — the PR description should explain the motivation, the change, and how to test it.

## Security Considerations

- **Never hardcode secrets** — tokens, URLs, and credentials must come from environment variables.
- **Validate all inputs** — content types, timeouts, and priorities are validated and clamped.
- **Protect the token** — send it as an unredirected `X-Gotify-Key` header; never place it in a URL or echo it in diagnostics.
- **No logging of sensitive data** — the plugin must never log `GOTIFY_APP_TOKEN` or `GOTIFY_URL`.

If you discover a security vulnerability, see [SECURITY.md](SECURITY.md) for responsible disclosure. All contributions are subject to the [Code of Conduct](CODE_OF_CONDUCT.md). See [release engineering](docs/RELEASING.md) for versioning rules and [second-pass audit findings](docs/SECOND_PASS_AUDIT.md) for outstanding risks.

## Plugin Architecture

```
gotify_notify/
├── __init__.py      # Plugin code: register(), _build_payload(), _send_request()
├── plugin.yaml      # Hermes plugin manifest
tests/
├── __init__.py      # Path setup
├── test_gotify_notify.py       # Original behavior regression tests
├── test_security_regression.py # URL, header, and error security tests
├── test_version_sync.py        # Release metadata tests
scripts/
├── sync_version.py             # Atomic release version synchronization
```

The plugin entry point is `register(ctx)` — called by Hermes' `PluginManager` during discovery. It registers a single tool (`gotify_send`) with its schema and handler.

### Key design decisions

- **stdlib `urllib`** instead of `requests` or `httpx` — zero dependencies, works everywhere Hermes runs.
- **Content type allowlist** — only `text/markdown` and `text/plain` are accepted; invalid values silently fall back to the default. This prevents header injection.
- **Timeout clamping** — 1–60 seconds. Invalid values (non-integer, empty) fall back to 10. This prevents DoS via misconfiguration.
- **Safe diagnostics** — HTTP errors include status codes; successful Gotify responses are reduced to a numeric message ID and transport errors are categorized without leaking raw server text.
- **Version coherence** — `scripts/sync_version.py` updates four version declarations before `@semantic-release/git` commits and tags the release; test the script before editing release automation.

## Reporting Issues

Use [GitHub Issues](https://github.com/redoracle/hermes-plugin-gotify-notify/issues). Include:

- Hermes Agent version (`hermes version`)
- Python version
- OS
- Gotify server version
- Relevant env vars (redact the token!)
- Error output or unexpected behavior
- Steps to reproduce

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
