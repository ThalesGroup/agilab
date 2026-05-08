"""Shared bootstrap helpers for AGILAB Streamlit pages."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any, Callable


def session_env_ready(
    session_state: Any,
    *,
    env_key: str = "env",
    init_done_default: bool = True,
) -> bool:
    """Return whether the Streamlit session already has a usable AGILAB env."""
    if env_key not in session_state:
        return False
    return bool(getattr(session_state[env_key], "init_done", init_done_default))


def load_about_page_module(
    current_file: str | Path,
    *,
    load_module: Callable[..., Any] | None = None,
) -> Any:
    """Load the main page module from the active checkout or packaged install."""
    current_path = Path(current_file).resolve()
    about_path = current_path.parents[1] / "main_page.py"
    if load_module is not None:
        return load_module(
            "agilab.main_page",
            current_file=current_file,
            fallback_path=about_path,
            fallback_name="agilab_about_fallback",
        )

    try:
        module = importlib.import_module("agilab.main_page")
        if hasattr(module, "main"):
            return module
    except (ImportError, ModuleNotFoundError):
        pass

    spec = importlib.util.spec_from_file_location("agilab_about_fallback", about_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load main_page page module from {about_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "main"):
        raise ModuleNotFoundError("Unable to import main_page page module.")
    return module


def ensure_page_env(
    streamlit: Any,
    current_file: str | Path,
    *,
    init_done_default: bool = True,
    load_module: Callable[..., Any] | None = None,
) -> Any | None:
    """Ensure the page has a bootstrapped env, delegating cold starts to the main page."""
    if session_env_ready(
        streamlit.session_state,
        init_done_default=init_done_default,
    ):
        return streamlit.session_state["env"]

    about_page = load_about_page_module(current_file, load_module=load_module)
    about_page.main()
    streamlit.rerun()
    return None
