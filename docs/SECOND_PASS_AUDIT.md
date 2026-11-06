# Second-pass architecture, security and repository audit

Date: 2026-11-05. Scope: the root Hermes plugin, packaging/release metadata, current workflow configuration, documentation and the companion utility's repository integration. This is a source and local-test audit, **not** a live Gotify, Android hardware, GitHub-hosted CI, or full audit of the companion utility's approximately 210 KiB implementation.

| Priority | Finding | Action |
| --- | --- | --- |
| High | Successful Gotify responses were read without a size cap and copied back to the agent, potentially including message contents or secrets from a compromised server | Read at most 8 KiB plus sentinel and return only a verified nonnegative numeric message ID; added regression cases |
| High | README claimed pip-install automatically enabled the plugin, contrary to Hermes opt-in policy | Document explicit plugin enablement and `hermes plugins doctor` checks |
| High | README suggested cloning the entire repository into a plugin directory, but `plugin.yaml` and `__init__.py` live one level below the repository root | Document copying the `gotify_notify` package as the directory plugin, or installing its pip entry point |
| Medium | CI did not fail when package/manifests drifted between releases | Add read-only version consistency verification to CI and release workflow |
| Medium | Vulnerability reporting had a speculative contact address and response guarantees | Prefer verified private GitHub advisories and make support/response expectations realistic |
| Medium | No CodeQL workflow, ownership declaration, or issue/PR templates | Add CodeQL, CODEOWNERS, structured issue/PR templates and governance documents |
| Medium | Build metadata used deprecated setuptools license-table format and an unregistered framework classifier | Use SPDX `license = "MIT"` metadata and drop the questionable classifier; verify wheel build |
| Low | No style or line-ending conventions, no clear release runbook | Add EditorConfig, Git attributes and release operations documentation |
| Open | Release npm dependencies have no lockfile and cannot be frozen/verified without an npm registry | Do **not** fabricate lockfile; document online generation, review and migration to `npm ci` |
| Open | Android companion CLI is large and contains duplicated entry points | Add a `cmp` CI guard and retain isolated utility unit tests; defer any structural consolidation until full regression/hardware validation is available |

## Dependency policy

At audit time, the first-pass patch already raised Python development tools to current stable compatible ranges and the Conventional Commits preset to 10.4.1; it also upgraded GitHub Actions majors and retained the current stable semantic-release/exec packages. The second pass preserves those safe ranges rather than adopting preview/alpha releases. Python **runtime dependencies remain empty**. Node `engines` declares the minimum supported release runtime. Automated updates remain review-gated by CI and the maintainer.

## Trust and test limitations

- No live network calls are performed by Python unit tests.
- The release dependency graph and new CodeQL workflow require GitHub-hosted verification.
- Python package builds can be checked locally, but this does not prove compatibility with every Hermes release.
- Companion utility external ADB, Gotify management endpoints and FFmpeg conversion need hardware/service integration checks before a utility refactor.
- A pull request requires GitHub write permissions; a local patch by itself is not a published PR.
 
## Subsequent high-trust test improvements (November 2026)

- Added loopback HTTP contract coverage for real request delivery, auth errors, upstream failures and message validation.
- Corrected tests that previously treated blank messages as successful, and covered non-finite priority inputs.
- Improved Android UI switch selection and assertion quality; checked-state selection is now verified using representative UI XML rather than source-text inspection.
- Added Android mock-server application-token validation and a CI-driven provisioning/rotation self-test with readiness probing.
- Version synchronization stages changed files, preserves permissions and attempts rollback after ordinary I/O failures. This is **not** a filesystem transaction under abrupt process failure; release workflows should still run the read-only consistency checker.
- Hardware-backed Android/OEM integration, real Gotify persistence and a reviewed npm lockfile remain separate, outstanding verification work.

## Real-service and recovery verification (November 2026)

- Added an isolated CI job using pinned Gotify 2.9.1 and 3.1.1 Docker images. The job creates a disposable application and verifies a message is persisted with the expected Markdown extras, priority, and title; invalid tokens are refused.
- CI installs FFmpeg/FFprobe and fails rather than silently skipping the real WAV-to-OGG/Vorbis conversion/cache validation.
- Added fault-injection assertions for one-time application-token recovery if the primary secret store is unavailable, including 0600 recovery permissions and no raw token in the error.
- Local plugin unit/contract tests remain credential-free; real Gotify tests are isolated from the default unit suite and are restricted to 127.0.0.1.
- Physical Android/OEM UI behavior and crash-consistent multi-file version transactions remain outside the CI assurance boundary.
