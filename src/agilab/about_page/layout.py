"""Display-only helpers for the AGILab About page."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


def quick_logo(resources_path: Path) -> None:
    """Render a lightweight banner with the AGILab logo."""
    try:
        from agi_gui.pagelib import get_base64_of_image

        img_data = get_base64_of_image(resources_path / "agilab_logo.png")
        img_src = f"data:image/png;base64,{img_data}"
        st.markdown(
            f"""<div style="background-color: #333333; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 800px; margin: 20px auto;">
                    <div style="display: flex; align-items: center; justify-content: center;">
                        <h1 style="margin: 0; padding: 0 10px 0 0;">Welcome to</h1>
                        <img src="{img_src}" alt="AGI Logo" style="width:160px; margin-bottom: 20px;">
                    </div>
                    <div style="text-align: center;">
                        <strong style="color: black;">a step further toward AGI</strong>
                    </div>
                </div>""",
            unsafe_allow_html=True,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        st.info(str(exc))
        st.info("Welcome to AGILAB", icon="📦")


def landing_page_sections() -> dict[str, Any]:
    """Return compact secondary guidance shown under the first-step path."""
    return {
        "after_first_demo": [
            "try another built-in demo",
            "keep cluster mode for later",
        ],
    }


def display_landing_page(resources_path: Path) -> None:
    """Display compact secondary context under the first-step instructions."""
    del resources_path
    st.info("After the first demo: try another built-in demo. Keep cluster mode for later.")


def clean_openai_key(key: str | None) -> str | None:
    """Return None for missing/placeholder keys to avoid confusing 401s."""
    if not key:
        return None
    trimmed = key.strip()
    placeholders = {"your-key", "sk-your-key", "sk-XXXX"}
    if trimmed in placeholders or len(trimmed) < 12:
        return None
    return trimmed


def openai_status_banner(env: Any, *, env_file_path: Path) -> None:
    """Show a non-blocking banner when OpenAI features are unavailable."""
    env_key = getattr(env, "OPENAI_API_KEY", None)
    key = clean_openai_key(os.environ.get("OPENAI_API_KEY") or env_key)
    if not key:
        st.warning(
            "OpenAI features are disabled. Set OPENAI_API_KEY below in "
            "'Environment Variables', then reload the app. The value will be "
            f"saved in {env_file_path}.",
            icon="⚠️",
        )


def render_package_versions() -> None:
    """Render installed AGILAB package versions."""
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:
        import importlib_metadata  # type: ignore

    packages = [
        ("agilab", "agilab"),
        ("agi-core", "agi-core"),
        ("agi-gui", "agi-gui"),
        ("agi-node", "agi-node"),
        ("agi-env", "agi-env"),
    ]

    for label, pkg_name in packages:
        try:
            version = importlib_metadata.version(pkg_name)
        except importlib_metadata.PackageNotFoundError:
            version = "not installed"
        st.write(f"{label}: {version}")


def render_system_information() -> None:
    """Render local OS and CPU information."""
    import platform

    st.write(f"OS: {platform.system()} {platform.release()}")
    cpu_name = platform.processor() or platform.machine()
    st.write(f"CPU: {cpu_name}")


def render_footer() -> None:
    """Render the About page legal footer."""
    current_year = datetime.now().year
    st.markdown(
        f"""
    <div class='footer' style="display: flex; justify-content: flex-end;">
        <span>&copy; 2020-{current_year} Thales SIX GTS. Licensed under the BSD 3-Clause License.</span>
    </div>
    """,
        unsafe_allow_html=True,
    )
