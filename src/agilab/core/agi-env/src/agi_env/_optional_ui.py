"""Optional UI dependency helpers for agi-env."""

from __future__ import annotations

from types import ModuleType
from typing import Callable


UI_EXTRA_INSTALL_HINT = (
    "agi-env UI helpers require Streamlit. Install the UI package with "
    "`pip install agi-gui`."
)


def require_streamlit(importer: Callable[..., ModuleType] = __import__) -> ModuleType:
    """Import Streamlit or raise an actionable optional-extra error."""

    try:
        return importer("streamlit")
    except ModuleNotFoundError as exc:
        if exc.name == "streamlit":
            raise ModuleNotFoundError(UI_EXTRA_INSTALL_HINT) from exc
        raise
