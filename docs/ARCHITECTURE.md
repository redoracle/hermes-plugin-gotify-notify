# Architecture and operational guarantees

## Scope

`gotify_notify` is a small synchronous Hermes Agent tool adapter. It deliberately
uses only the Python standard library at runtime and does not maintain queues,
background workers, persistent connections, or stored credentials. Its public
interface is the `register(ctx)` entry point and its single `gotify_send` tool.

## Request lifecycle

1. Hermes calls `gotify_send` with a JSON object containing `message`, an
   optional `title`, and an optional `priority`.
2. The handler reads `GOTIFY_URL` and `GOTIFY_APP_TOKEN` at invocation time,
   validates the URL/token and applies the configured rendering and timeout.
3. `_build_payload` bounds the title (120 characters), message (4,000
   characters), and priority (1–10) while preserving Gotify's documented
   `extras.client::display.contentType` support.
4. `_send_request` posts JSON to the configured `/message` endpoint using
   `X-Gotify-Key`. It uses `add_unredirected_header` to avoid forwarding the
   secret to a redirected destination. No token is embedded in a URL.
5. Successful responses are read with an 8 KiB cap and summarized to the
   numeric Gotify message ID only; arbitrary server text is never echoed.
   HTTP errors expose only the status, and transport exceptions only the
   exception category. The handler performs no retries, avoiding duplicate
   notifications when a response is lost after delivery.

## Trust boundaries

- **Agent inputs**: message must be a string; the schema describes title and
  priority types. Empty messages remain accepted for backwards compatibility.
- **Environment**: the Gotify base URL and application token are privileged
  deployment configuration, not agent-selected destinations. URLs with
  embedded credentials, query strings, fragments or invalid schemes are
  rejected before network I/O. An HTTP URL is allowed for trusted local
  deployments, but HTTPS should be used over untrusted networks.
- **Server responses**: the JSON result retains the `response` field, but it
  contains only a serialized `{"id": number}` if Gotify supplies a valid
  nonnegative integer ID. It is empty otherwise. Neither successful bodies
  nor error bodies are passed through unfiltered.
- **Redirects**: Python's default opener may follow HTTP redirects, but its
  redirected requests omit the unredirected authentication header. Configure
  Gotify's canonical URL to avoid redirects and unexpected outbound requests.

## Releases and dependency boundaries

Python runtime dependencies remain empty. Development tools live in
`pyproject.toml`, while `package.json` contains release-only Node dependencies.

The release workflow uses semantic-release on `main`. Its prepare hook executes
`scripts/sync_version.py`, which preflights all targets before writing four
version declarations and supports a read-only `--check` CI mode: `pyproject.toml`, `gotify_notify/__init__.py`,
`gotify_notify/plugin.yaml`, and `package.json`. The `@semantic-release/git`
prepare step commits the coherent version metadata with `[skip ci]`, then the
GitHub release step publishes the tag/release. This replaces the previous
post-release API mutation of a single version file.

The release workflow requires a GitHub token allowed to push the release commit
under the repository's branch protection policy. Release jobs should be
reviewed whenever this policy changes. Node release tooling currently has no
committed lockfile; see `docs/RELEASING.md` before considering the release
pipeline fully reproducible.

## Verification strategy

- **Plugin behavior:** mocked transport tests validate payloads, status codes,
  timeout and priority clamping, and registration.
- **Security regression:** tests assert token-free URLs, redirect-safe header
  behavior, invalid URL rejection, and redacted error paths.
- **Release consistency:** unit tests cover idempotency, malformed versions and
  all-or-nothing preflight of metadata changes.
- **CI:** tests run on Linux/macOS and Python 3.11–3.14 with a 95% coverage
  threshold. Ruff, compile checks, metadata consistency, CodeQL and the
  companion Android utility's isolated unit suite provide additional gates. The hardware-dependent full Android
  provisioning self-test is intentionally not run on hosted CI.
