"""Namespace package shim so pytest can import app-specific test modules.

Pytest collects files like ``src/agilab/apps/builtin/<app>/test/test_*.py`` while the
repository already exposes a top-level ``test`` package. When pytest runs from
the repo root it imports ``test...`` modules from here, so we extend
``__path__`` with each app's ``test`` directory to make them importable.
"""

from pathlib import Path
from pkgutil import extend_path
import importlib
import sys
import types

__path__ = extend_path(__path__, __name__)  # type: ignore[misc]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_ROOT = _REPO_ROOT / "src"
_APPS_ROOT = _REPO_ROOT / "src" / "agilab" / "apps"

src_root_str = str(_SRC_ROOT)
if src_root_str not in sys.path:
    sys.path.insert(0, src_root_str)


def import_agilab_module(module_name: str):
    """Import an ``agilab.*`` module from the repo source tree even if another package is already loaded."""
    pkg = sys.modules.get("agilab")
    package_root = str(_SRC_ROOT / "agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root not in package_path:
            pkg.__path__ = [package_root, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)

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
