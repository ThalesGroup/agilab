"""Namespace package shim so pytest can import app-specific test modules.

Pytest collects files like ``src/agilab/apps/builtin/<app>/test/test_*.py`` while the
repository already exposes a top-level ``test`` package. When pytest runs from
the repo root it imports ``test...`` modules from here, so we extend
``__path__`` with each app's ``test`` directory to make them importable.
"""

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[misc]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_APPS_ROOT = _REPO_ROOT / "src" / "agilab" / "apps"

def _iter_app_dirs():
    if not _APPS_ROOT.is_dir():
        return []
    entries = []
    for candidate in _APPS_ROOT.iterdir():
        if candidate.name == "builtin" and candidate.is_dir():
            entries.extend(p for p in candidate.iterdir() if p.is_dir())
        elif candidate.is_dir():
            entries.append(candidate)
    return entries


for _app_dir in _iter_app_dirs():
    test_dir = _app_dir / "test"
    if test_dir.is_dir():
        test_dir_str = str(test_dir)
        if test_dir_str not in __path__:
            __path__.append(test_dir_str)
