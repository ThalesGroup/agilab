"""Namespace package shim so pytest can import app-specific test modules.

Pytest collects files like ``src/agilab/apps/<app>/test/test_*.py`` while the
repository already exposes a top-level ``test`` package. When pytest runs from
the repo root it imports ``test...`` modules from here, so we extend
``__path__`` with each app's ``test`` directory to make them importable.
"""

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[misc]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_APPS_ROOT = _REPO_ROOT / "src" / "agilab" / "apps"

if _APPS_ROOT.is_dir():
    for app_dir in _APPS_ROOT.iterdir():
        test_dir = app_dir / "test"
        if test_dir.is_dir():
            test_dir_str = str(test_dir)
            if test_dir_str not in __path__:
                __path__.append(test_dir_str)
