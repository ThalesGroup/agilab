"""AGILab sitecustomize to keep repo-local tests importable.

Pytest collects `src/agilab/apps/*/test` packages and the standard library also
ships a `test` package. When Python starts it may import the stdlib variant
first, causing `test.test_<app>_manager` imports to resolve to the wrong module.
We bias imports toward the repository shim by inserting the repo root onto
``sys.path`` (if needed) and eagerly importing the local ``test`` package.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_REPO_TEST = _REPO_ROOT / "test" / "__init__.py"
_DEBUG = os.environ.get("AGILAB_SITEDEBUG")


def _debug(message: str) -> None:
    if _DEBUG:
        print(f"[agilab sitecustomize] {message}", file=sys.stderr)

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
    _debug(f"prepended repo root to sys.path: {sys.path[0]}")


def _force_repo_test_package() -> None:
    """Ensure ``sys.modules['test']`` comes from this checkout."""
    if not _REPO_TEST.exists():
        return

    module = importlib.import_module("test")
    module_file = Path(getattr(module, "__file__", ""))
    if module_file == _REPO_TEST:
        _debug("local test package already active.")
        return

    # Reload from the repository path so future imports reuse the shim.
    spec = importlib.util.spec_from_file_location("test", _REPO_TEST)
    if not spec or not spec.loader:
        _debug("failed to create spec for repo test package.")
        return

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[assignment]
    sys.modules["test"] = module
    _debug("reloaded test package from repository path.")


try:
    _force_repo_test_package()
except Exception:
    # Last-resort: do not block interpreter startup if anything goes wrong.
    pass
