"""Application package namespace for AGILAB app projects.

Source app projects live under ``src/agilab/apps/builtin``. Extend the package
search path so legacy imports such as ``agilab.apps.flight_telemetry_project``
continue to resolve without forcing callers to reference ``builtin`` directly.
"""

from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_builtin_dir = _pkg_dir / "builtin"
if _builtin_dir.is_dir():
    builtin_path = str(_builtin_dir)
    if builtin_path not in __path__:
        __path__.append(builtin_path)

__all__ = []
