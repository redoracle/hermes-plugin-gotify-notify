#!/usr/bin/env python3
"""Keep stable-release version declarations in sync during a release."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
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
    # Stage changes and backups before touching any original file.
    # Ordinary I/O failures are rolled back; sudden process termination
    # cannot make a multi-file update fully atomic.
    changed = {path: (path.read_text(encoding="utf-8"), content)
               for path, content in updates.items()
               if path.read_text(encoding="utf-8") != content}
    stages: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    installed: list[Path] = []

    def stage(path: Path, data: str) -> Path:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            shutil.copymode(path, temporary)
            return temporary
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    try:
        for path, (original, updated) in changed.items():
            stages[path] = stage(path, updated)
            backups[path] = stage(path, original)
        for path in changed:
            os.replace(stages[path], path)
            installed.append(path)
    except OSError as exc:
        rollback_errors: list[str] = []
        for path in reversed(installed):
            try:
                os.replace(backups[path], path)
            except OSError as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        if rollback_errors:
            raise RuntimeError("Version update rollback failed: " + "; ".join(rollback_errors)) from exc
        raise
    finally:
        for temporary in (*stages.values(), *backups.values()):
            temporary.unlink(missing_ok=True)


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
