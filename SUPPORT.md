# Support and troubleshooting

This repository is community-maintained. For a reproducible bug, open a [bug report](https://github.com/redoracle/hermes-plugin-gotify-notify/issues/new/choose); for improvements, use the feature-request template. For vulnerabilities, **do not open a public issue**—use the [private reporting process](SECURITY.md).

## First checks

1. Confirm Hermes discovers and has enabled `gotify-notify`:
   ```bash
   hermes plugins list
   hermes plugins doctor gotify-notify --ci
   ```
2. Verify the running Hermes process reads `GOTIFY_URL` and `GOTIFY_APP_TOKEN` from `~/.hermes/.env` (without printing the secret).
3. Confirm the token is from a Gotify **Application**, not a Gotify client account.
4. Prefer a canonical `https://` URL that reaches `/message` without redirection. For a reverse-proxy subpath, specify the prefix in `GOTIFY_URL`.
5. Restart the Hermes gateway or interactive process after changing environment configuration.

## Common problems

| Symptom | Likely cause and safe next step |
| --- | --- |
| Plugin not listed | The package is not installed into the active Hermes Python environment, or the directory does not contain both `plugin.yaml` and `__init__.py` |
| Plugin listed but unavailable | Enable it using `hermes plugins enable gotify-notify`; inspect the Hermes plugin doctor output |
| `Missing GOTIFY_URL or GOTIFY_APP_TOKEN` | Configure both values in the environment loaded by the Hermes process |
| `Invalid GOTIFY_URL` | Supply a full `http://` or `https://` URL without credentials, query or fragment |
| HTTP 401 / 403 | Check that the Application token is valid and permitted by Gotify; rotate it if exposure is suspected |
| HTTP 3xx or no notification | Configure the canonical endpoint; credentials intentionally do not follow redirects |
| Timeout or TLS error | Check DNS, firewall, reverse proxy, certificate chain, and that the server supports the selected scheme |

The plugin does not retry requests because an uncertain outcome could mean Gotify accepted the notification. If a delivery may have succeeded, inspect Gotify before retrying.

## Useful diagnostic context

When opening an issue, include the plugin version, Hermes version, Python version, operating system, minimal reproduction, sanitized JSON error, and relevant configuration **names**. Never post application tokens, passwords, real hostnames you consider private, screenshots containing secrets, or unredacted log files.
