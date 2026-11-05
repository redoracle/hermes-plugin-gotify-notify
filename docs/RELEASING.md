# Release engineering

This repository uses Conventional Commits and [semantic-release](https://semantic-release.gitbook.io/semantic-release/) to create tags and GitHub Releases from the protected `main` branch. Release publishing is a privileged workflow; it must not run from pull requests.

## Release sources of truth

- `pyproject.toml` is the canonical package version and build metadata.
- `scripts/sync_version.py` synchronizes version strings in `pyproject.toml`, `package.json`, `gotify_notify/__init__.py`, and `gotify_notify/plugin.yaml`.
- Run `python scripts/sync_version.py --check` to verify consistency without modifying files.
- The release workflow calls `scripts/prepare-release.sh VERSION`, then `@semantic-release/git` commits the synchronized version files before creating the GitHub Release.

## Contributor workflow

1. Branch from `main` and use a Conventional Commit message: `fix: ...`, `feat: ...`, or `feat!: ...` for breaking changes.
2. Run the tests, Ruff lint, metadata checker, and package build before requesting review.
3. Confirm that GitHub Actions CI and CodeQL are green; require a human review for any change touching network authentication or release permissions.
4. Merge through a protected branch according to the repository's policy. Do not manually bump versions in routine PRs.

## Maintainer release checks

- Confirm `GITHUB_TOKEN` can commit prepared version metadata to `main`. If branch rules reject the commit, adjust the release architecture/policy explicitly rather than bypassing review controls.
- The release workflow uses the repository-scoped token with `contents: write`; do not grant broader permissions.
- `npm install --ignore-scripts` installs release-only tooling. **There is no committed npm lockfile**, so resolution is not reproducible yet. Before enabling strict supply-chain gates, generate a real lockfile using the official registry on an online development machine, review its integrity hashes and transitive dependencies, commit it, then replace the workflow step with `npm ci --ignore-scripts`. Do not invent lockfile entries or hashes.
- Review Dependabot PRs and upstream release notes. Major dependency upgrades should be separate, reviewed changes; preserve compatibility with the active Node and Python runtime matrix.
- After release, verify that the tag, GitHub Release, package metadata and plugin manifest have the same version and that the project can be installed via pip.

## Rollback

If an automated release fails, inspect the workflow logs and compare the repository's version files before rerunning. Never reuse or move an immutable published version tag. Fix the release pipeline in a new conventional-commit PR, then let semantic-release choose the next version. If a bad notification plugin version was deployed, pin installation to a known-good Git commit/tag while the fix is prepared.

## Release-notes compatibility guard

The release-notes generator in the current semantic-release toolchain uses `conventional-changelog-writer@8`. The `conventional-changelog-conventionalcommits@10` preset requires writer v9 and fails during `generateNotes` with a missing-helper error. Keep the preset pinned to **9.3.1** until the installed release-notes generator supports writer v9. Do not silently raise this major version.

Run `npm run test:release-notes` after installing release dependencies to validate realistic feature and fix sections. CI and the privileged release workflow run the same check before publishing. When updating semantic-release or the preset, verify the complete release-notes smoke test in CI before merging.
