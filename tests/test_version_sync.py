"""Release metadata synchronization tests (no network or Git required)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_version.py"
_spec = importlib.util.spec_from_file_location("sync_version_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


@pytest.fixture
def release_tree(tmp_path):
    (tmp_path / "gotify_notify").mkdir()
    originals = {
        "pyproject.toml": '[project]\nversion = "1.0.0"\n',
        "package.json": '{\n  "version": "1.0.0",\n}\n',
        "gotify_notify/__init__.py": '__version__ = "1.0.0"\n',
        "gotify_notify/plugin.yaml": 'name: gotify\nversion: "1.0.0"\n',
    }
    for filename, content in originals.items():
        (tmp_path / filename).write_text(content)
    return tmp_path, originals


def test_sync_updates_all_version_declarations(release_tree):
    root, _ = release_tree
    _module.sync_version("2.3.4", root)
    for filename in (
        "pyproject.toml", "package.json", "gotify_notify/__init__.py",
        "gotify_notify/plugin.yaml"
    ):
        assert '"2.3.4"' in (root / filename).read_text()


def test_sync_is_idempotent(release_tree):
    root, _ = release_tree
    _module.sync_version("2.3.4", root)
    before = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
    _module.sync_version("2.3.4", root)
    assert before == {p: p.read_text() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("version", ["", "1", "v1.2.3", "1.2.3; echo unsafe", "1.2.3-beta.1", "1.2.3+build", "01.2.3"])
def test_bad_version_does_not_modify_any_file(release_tree, version):
    root, originals = release_tree
    with pytest.raises(ValueError):
        _module.sync_version(version, root)
    assert all((root / filename).read_text() == content for filename, content in originals.items())


def test_missing_declaration_is_atomic(release_tree):
    root, originals = release_tree
    (root / "gotify_notify/plugin.yaml").write_text("version: invalid\n")
    with pytest.raises(ValueError):
        _module.sync_version("2.3.4", root)
    assert (root / "pyproject.toml").read_text() == originals["pyproject.toml"]
    assert (root / "package.json").read_text() == originals["package.json"]


def test_check_only_accepts_consistent_versions(release_tree):
    root, originals = release_tree
    _module.sync_version("1.0.0", root, check_only=True)
    assert all((root / filename).read_text() == content for filename, content in originals.items())


def test_check_only_rejects_mismatch_without_editing(release_tree):
    root, originals = release_tree
    with pytest.raises(ValueError, match="Version mismatch"):
        _module.sync_version("2.0.0", root, check_only=True)
    assert all((root / filename).read_text() == content for filename, content in originals.items())


def test_replace_failure_rolls_back_every_version_declaration(release_tree):
    root, originals = release_tree
    actual_replace = _module.os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated filesystem failure")
        return actual_replace(source, destination)

    with mock.patch.object(_module.os, "replace", side_effect=fail_second_replace):
        with pytest.raises(OSError, match="simulated filesystem failure"):
            _module.sync_version("2.3.4", root)

    assert all((root / name).read_text() == content for name, content in originals.items())
    assert sorted(x.relative_to(root).as_posix() for x in root.rglob("*") if x.is_file()) == sorted(originals)


def test_sync_preserves_existing_file_permissions(release_tree):
    root, _ = release_tree
    script = root / "gotify_notify/__init__.py"
    script.chmod(0o600)
    _module.sync_version("2.3.4", root)
    assert script.stat().st_mode & 0o777 == 0o600
