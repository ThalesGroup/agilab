"""Optional UI dependency helpers for agi-env."""

from __future__ import annotations

from types import ModuleType
from typing import Callable
from importlib import import_module


UI_EXTRA_INSTALL_HINT = (
    "agi-env UI helpers require the AGILAB React host. Install the UI package with "
    "`pip install agi-gui`."
)


def require_python_ui(importer: Callable[..., ModuleType] = import_module) -> ModuleType:
    """Load the optional UI provider without coupling the core to a web host."""

    try:
        return importer("agi_web.python_ui")
    except ModuleNotFoundError as exc:
        if exc.name in {"agi_web", "agi_web.python_ui"}:
            raise ModuleNotFoundError(UI_EXTRA_INSTALL_HINT) from exc
        raise
