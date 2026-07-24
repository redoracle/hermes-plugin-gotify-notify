"""Pytest configuration for the gotify-notify plugin test suite."""

import sys
from pathlib import Path

# Ensure the plugin package is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_PARENT = _REPO_ROOT
if str(_PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_PARENT))
