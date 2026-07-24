# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-24

### Added
- Initial release.
- `gotify_send` tool registration with Hermes Agent plugin system.
- Markdown rendering via `extras.client::display.contentType` (default: `text/markdown`).
- Configurable content type via `GOTIFY_CONTENT_TYPE` environment variable.
- Configurable request timeout via `GOTIFY_TIMEOUT` (1–60 seconds, default: 10).
- Input validation: title truncation (120 chars), message truncation (4000 chars), priority clamping (1–10).
- Token URL-encoding via `urllib.parse.quote(token, safe='')`.
- Content type allowlist (`text/markdown`, `text/plain`); invalid values fall back to default.
- HTTP error handling with structured JSON responses.
- Comprehensive test suite (30 tests, zero network calls).
- pip entry point for `hermes_agent.plugins`.
- GitHub Actions CI (Python 3.11/3.12/3.13 on Ubuntu and macOS).
- MIT license, SECURITY.md, CONTRIBUTING.md.
