#!/usr/bin/env bash
set -euo pipefail

# semantic-release invokes this before @semantic-release/git prepares a commit.
python3 scripts/sync_version.py "${1:?usage: prepare-release.sh VERSION}"
