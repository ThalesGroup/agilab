# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard
# All rights reserved.
#
# Streamlit page: dynamic view discovery under env.AGILAB_VIEWS_ABS.
# Each view runs in its own virtual environment (if found) via a sidecar
# Streamlit process and is embedded back into this app using an <iframe>.
#
# Minimal changes vs your previous version:
# - Replaces list_views(...) with discover_views(...)
# - Replaces importlib.run of the selected view with a sidecar + iframe
# - Adds small helper block for venv discovery and sidecar lifecycle
#
# ----------------------------

from __future__ import annotations

import os
import sys
import socket
import subprocess
import time
import hashlib
from pathlib import Path
from typing import List, Union

import streamlit as st
import streamlit.components.v1 as components

# Use modern TOML libraries
import tomli         # For reading TOML files (read as binary)
import tomli_w       # For writing TOML files (write as binary)

# Project utilities (unchanged)
from agilab.pagelib import activate_mlflow, get_about_content, render_logo, select_project
from agi_env import AgiEnv, normalize_path


# =============== Streamlit page config ==================
st.set_page_config(
    layout="wide",
    menu_items=get_about_content()
)

# =============== Helpers: per-view venv sidecar ==================

def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0

def _python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def _find_venv_for(script_path: Path) -> Path | None:
    """
    Look for a venv close to the view:
      - <view_dir>/.venv or venv
      - ${AGILAB_VENVS_ABS}/<view_name> or <view_name>.venv (optional)
      - ${AGILAB_VIEWS_VENVS_ABS}/<view_name> or <view_name>.venv (optional)
    Return the venv dir (not the python exe) or None.
    """
    view_dir = script_path.parent
    candidates: list[Path] = [
        view_dir / ".venv",
        view_dir / "venv",
    ]
    for env_var in ("AGILAB_VENVS_ABS", "AGILAB_VIEWS_VENVS_ABS"):
        base = os.getenv(env_var)
        if base:
            base = Path(base)
            candidates += [base / script_path.stem, base / f"{script_path.stem}.venv"]

    for venv in candidates:
        python = _python_in_venv(venv)
        if python.exists():
            return venv
    return None

def _port_for(key: str) -> int:
    """Stable deterministic port in [8600..8899] from a key (e.g., view path)."""
    base = int(os.getenv("AGILAB_VIEWS_BASE_PORT", "8600"))
    span = 300
    h = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16)
    return base + (h % span)

@st.cache_resource(show_spinner=False)
def _ensure_sidecar(view_key: str, venv: Path | None, script: Path, port: int):
    """Start the view's Streamlit in a separate process (one per session)."""
    if _is_port_open(port):
        return  # already running

    # Choose interpreter: prefer view venv, else current python (warn)
    if venv:
        python = str(_python_in_venv(venv))
    else:
        python = sys.executable
        st.warning(f"No venv found for '{script.name}'. Falling back to app interpreter.")

    cmd = [
        python, "-m", "streamlit", "run", str(script),
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]

    env = os.environ.copy()
    # Avoid leaking the main app's sys.path into the child
    env.pop("PYTHONPATH", None)

    # Launch detached
    kwargs = dict(env=env, cwd=str(script.parent),
                  stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(cmd, **kwargs)

    # Wait a bit for the port to come up
    for _ in range(80):
        if _is_port_open(port):
            break
        time.sleep(0.1)

def discover_views(views_dir: Union[str, Path]) -> list[Path]:
    """
    Dynamic discovery under env.AGILAB_VIEWS_ABS with common layouts:
      - <root>/views/*.py
      - <root>/views/*/(main.py|app.py|<name>.py)
      - convenience: <root>/*.py
    Follows symlinks too.
    Returns a list of concrete script Paths.
    """
    out: set[Path] = set()
    views_dir = Path(views_dir).resolve()  # follow symlinks

    if views_dir.exists():
        # Example: find all pyproject.toml files (as in your code)
        for p in views_dir.rglob("pyproject.toml"):
            out.add(p.parent.resolve())  # resolve symlinks for consistency

        # add optional convenience discovery of scripts in root or views
        for p in views_dir.glob("*.py"):
            out.add(p.resolve())

        for p in views_dir.glob("views/*.py"):
            out.add(p.resolve())

        for p in views_dir.glob("views/*/*.py"):
            if p.name in {"main.py", "app.py"} or p.stem == p.parent.name:
                out.add(p.resolve())

    return sorted(out, key=lambda p: (p.as_posix(), p.name))



# =============== Page logic ==================

def _init_env() -> AgiEnv:
    if "env" not in st.session_state or not getattr(st.session_state["env"], "init_done", False):
        env = AgiEnv()
        env.init_done = True
        st.session_state["env"] = env
    return st.session_state["env"]

def _ensure_servers(env: AgiEnv):
    if not st.session_state.get("server_started"):
        activate_mlflow(env)
        st.session_state["server_started"] = True

def _read_config(path: Path) -> dict:
    try:
        if path.exists():
            with open(path, "rb") as f:
                return tomli.load(f)
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
    return {}

def _write_config(path: Path, cfg: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            tomli_w.dump(cfg, f)
    except Exception as e:
        st.error(f"Error updating configuration: {e}")

def main():
    # Navigation by query param
    qp = st.query_params
    current_page = qp.get("current_page")

    env = _init_env()
    _ensure_servers(env)
    page_title = "Views"
    # Sidebar header/logo
    render_logo(page_title)

    # Sidebar: project selection
    projects = env.projects
    current_project = env.app if env.app in projects else (projects[0] if projects else None)
    select_project(projects, current_project)
    env = st.session_state["env"]  # may be updated by select_project

    # Where to store selected views per project
    project = env.app
    app_settings = Path(env.apps_dir) / project / "src" / "app_settings.toml"

    # Discover views dynamically under AGILAB_VIEWS_ABS
    all_views = discover_views(Path(env.AGILAB_VIEWS_ABS))

    # Route: if a concrete page path is in the URL, show that view
    if current_page:
        try:
            render_view_page(Path(current_page))
        except Exception as e:
            st.error(f"Failed to render view: {e}")
        return

    # ---------- Main "Views" page ----------
    st.title(page_title)

    if not all_views:
        st.info("No views found under AGILAB_VIEWS_ABS.")
        return

    # Load config and ensure structure
    cfg = _read_config(app_settings)
    if "views" not in cfg:
        cfg["views"] = {}
    project_views: list[str] = cfg.get("views", {}).get("view_module", [])

    # Multiselect with current selections
    view_names = [p.stem for p in all_views]
    # Keep only those that still exist
    preselect = [v for v in project_views if v in view_names]

    selected_views = st.multiselect(
        "Select views to expose on the home page",
        view_names,
        default=preselect,
        help="These will appear as buttons below."
    )

    # Persist selection
    cfg["views"]["view_module"] = selected_views
    _write_config(app_settings, cfg)

    # Show buttons for the selected views
    st.divider()
    cols = st.columns(min(len(selected_views), 4) or 1)

    if selected_views:
        for i, view_name in enumerate(selected_views):
            view_path = next((p for p in all_views if p.stem == view_name), None)
            if not view_path:
                st.error(f"View '{view_name}' not found.")
                continue
            with cols[i % len(cols)]:
                if st.button(view_name, use_container_width=True):
                    st.session_state["current_page"] = str(view_path.resolve())
                    st.query_params["current_page"] = str(view_path.resolve())
                    st.rerun()
    else:
        st.write("No views selected. Pick some above.")

def render_view_page(view_path: Path):
    """Render a specific view by launching it as a sidecar app in its own venv and iframing it."""
    back_col, title_col, _ = st.columns([1, 6, 1])
    with back_col:
        if st.button("← Back to Views"):
            st.session_state["current_page"] = "main"
            st.query_params["current_page"] = "main"
            st.rerun()
    with title_col:
        st.subheader(f"View: `{view_path.stem}`")

    # --- sidecar per-view run + iframe embed ---
    # Unique key for port hashing (works even if two views share the same filename)
    view_key = f"{view_path.stem}|{view_path.parent.as_posix()}"
    port = _port_for(view_key)
    venv = view_path / ".venv"

    _ensure_sidecar(view_key, venv, view_path, port)
    components.iframe(f"http://localhost:{port}", height=900)
    # --- end sidecar embed ---


if __name__ == "__main__":
    main()