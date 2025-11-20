"""
Application packages that ship with AGILab.
from __future__ import annotations

from pathlib import Path

# Ensure imports like ``import agilab.apps.flight_project`` keep working after
# moving built-in apps under ``apps/builtin``.
_PKG_DIR = Path(__file__).resolve().parent
_BUILTIN_DIR = _PKG_DIR / "builtin"
if _BUILTIN_DIR.is_dir():
    builtin_path = str(_BUILTIN_DIR)
    if builtin_path not in __path__:
        __path__.append(builtin_path)

__all__: list[str] = []
Built-in apps now live under ``src/agilab/apps/builtin`` so we extend the
package search path to include that directory. This keeps imports such as
``agilab.apps.flight_project`` working without forcing callers to reference the
``builtin`` subpackage explicitly.
"""

from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_builtin_dir = _pkg_dir / "builtin"
if _builtin_dir.is_dir():
    # Ensure importlib can locate builtin apps when using the legacy module path.
    __path__.append(str(_builtin_dir))

__all__ = []
