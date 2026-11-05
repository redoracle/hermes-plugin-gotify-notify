#!/usr/bin/env python3
"""Keep stable-release version declarations in sync during a release."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def sync_version(version: str, root: Path, *, check_only: bool = False) -> None:
    """Preflight all version locations, then update or check the stable version."""
    if not _VERSION.fullmatch(version):
        raise ValueError("Version must be a stable MAJOR.MINOR.PATCH release")

    files = {
        "pyproject.toml": r'(?m)^(version = ")[^"]+(")$',
        "package.json": r'(?m)^(  "version": ")[^"]+(",)$',
        "gotify_notify/__init__.py": r'(?m)^(__version__ = ")[^"]+(")$',
        "gotify_notify/plugin.yaml": r'(?m)^(version: ")[^"]+(")$',
    }
    updates = {}
    for filename, pattern in files.items():
        path = root / filename
        original = path.read_text(encoding="utf-8")
        matches = list(re.finditer(pattern, original))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one version declaration in {filename}")
        match = matches[0]
        updates[path] = (
            original[:match.start()]
            + f"{match.group(1)}{version}{match.group(2)}"
            + original[match.end():]
        )
    if check_only:
        mismatched = [path.relative_to(root).as_posix() for path, content in updates.items()
                      if path.read_text(encoding="utf-8") != content]
        if mismatched:
            raise ValueError("Version mismatch in " + ", ".join(mismatched))
        return
    for path, content in updates.items():
        if path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: sync_version.py VERSION | --check")
    try:
        if sys.argv[1] == "--check":
            root = Path.cwd()
            project_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
            sync_version(project_version, root, check_only=True)
        else:
            sync_version(sys.argv[1], Path.cwd())
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(f"Release version synchronization failed: {exc}") from exc
