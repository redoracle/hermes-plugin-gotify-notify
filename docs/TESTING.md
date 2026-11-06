# Test architecture and confidence boundaries

The project uses complementary test layers. Do not confuse statement coverage or a mocked request with production delivery.

| Layer | Execution | Evidence |
| --- | --- | --- |
| Python unit and regression tests | `python -m pytest tests/` | Input validation, error handling, payload and release metadata contracts |
| Loopback HTTP contract tests | Included in `tests/` | Real HTTP framing, headers, response redaction, 401/503; a deterministic in-process server |
| Real Gotify integration | `python -m pytest integration/test_real_gotify.py` | Real Gotify 2/3 application-token issue, notification persistence in the server database, response shape and Markdown extras |
| Android utility tests | CI `androidctl` job | ADB mock safety, app provisioning/rotation and token recovery |
| FFmpeg conversion/cache | CI `androidctl` job with FFmpeg installed | Real WAV to OGG/Vorbis conversion, codec and cache reuse |
| Physical Android/OEM | Not automatically covered | Pixel/Samsung channel-settings navigation, device state, notifications and UI selector compatibility |

## Disposable real Gotify server

These tests **must never be pointed at a production service**. The fixture rejects non-loopback addresses, creates an application, and writes test messages to its database. GitHub Actions starts dedicated Gotify 2.9.1 and 3.1.1 service containers on ephemeral runners.

Example for local Docker use (the data is disposable; do not reuse a production volume):

```bash
docker run --rm --name hermes-gotify-integration -p 127.0.0.1:8090:80 \
  -e GOTIFY_DEFAULTUSER_PASS=ci-disposable-gotify-password gotify/server:3.1.1

# In another shell, from the repository root:
python -m pip install -e '.[dev]'
GOTIFY_TEST_URL=http://127.0.0.1:8090 \
GOTIFY_TEST_ADMIN_PASSWORD=ci-disposable-gotify-password \
python -m pytest integration/test_real_gotify.py -v
```

The integration fixtures wait for the actual HTTP health endpoint with a monotonic deadline, then provision an application via the documented admin API. The test invokes the plugin's registered handler and queries the message list to verify persistence. No actual administrator password or token is committed.

The Docker image versions are intentionally pinned to patch tags. Changing supported Gotify versions requires reviewing upstream API changes and successful integration runs. This is a GitHub-hosted integration test, not a substitute for a manually operated production environment.

## Android recovery and media verification

```bash
python -m unittest discover -s utils/gotify-androidctl/tests -p 'test_androidctl.py' -v
GOTIFY_REQUIRE_FFMPEG=1 bash utils/gotify-androidctl/selftest.sh
```

The strict self-test needs `curl`, `ffmpeg` and `ffprobe`. It creates only temporary mock-server resources and validates one-time tokens, permission modes, idempotent provisioning, rotation boundaries, and audio codec/cache. Android hardware is not required.

The unit fault-injection tests simulate primary and recovery-storage errors. The tool preserves a 0600 recovery copy of a one-time token when possible. Fatal process termination or device disconnection at arbitrary phases remains a separate recovery risk.

## Operational principles

- Preserve deterministic, isolated tests: no shared production state, no network beyond the disposable integration container.
- Assert observable persisted effects and exact negative results, not only positive status codes.
- Retain bounded timeouts and ensure service shutdown/cleanup.
- Do not bypass failed CI checks. Failed real Gotify or media tests are compatibility signals, not expected skips.
- Keep CodeQL, static checks, unit tests and integration tests independently required in repository rules.
