# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex 0.42.0
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

import os
import sys
import socket
import time
import hashlib
from pathlib import Path
from typing import Union
import asyncio
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
import streamlit.components.v1 as components
from IPython.lib import backgroundjobs as bg
import logging
import subprocess

# Use modern TOML libraries
import tomli         # For reading TOML files (read as binary)
import tomli_w       # For writing TOML files (write as binary)

# Project utilities (unchanged)
from agi_env.pagelib import get_about_content, render_logo, select_project, inject_theme
from agi_env import AgiEnv, normalize_path

logger = logging.getLogger(__name__)

# =============== Streamlit page config ==================
st.set_page_config(
    layout="wide",
    menu_items=get_about_content()
)
resources_path = Path(__file__).resolve().parents[1] / "resources"
inject_theme(resources_path)

# =============== Helpers: per-view venv sidecar ==================

def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0

def _python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def _find_venv_for(script_path: Path) -> Path | None:
    """
    Look for a venv close to the apps-pages:
      - <view_dir>/.venv or venv
      - ${AGILAB_VENVS_ABS}/<view_name> or <view_name>.venv (optional)
      - ${AGILAB_PAGES_VENVS_ABS}/<view_name> or <view_name>.venv (optional)
    Return the venv dir (not the python exe) or None.
    """
    view_dir = script_path.parent
    candidates: list[Path] = [
        view_dir / ".venv",
        view_dir / "venv",
    ]
    for env_var in ("AGILAB_VENVS_ABS", "AGILAB_PAGES_VENVS_ABS"):
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
    base = int(os.getenv("AGILAB_PAGES_VENVS_ABS", "8600"))
    span = 300
    h = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16)
    return base + (h % span)

jobs = bg.BackgroundJobManager()

@staticmethod
def exec_bg(agi_env: AgiEnv, cmd: str, cwd: str) -> None:
    """
    Execute background command
    Args:
        cmd: the command to be run
        cwd: the current working directory

    Returns:
        """
    stdout = open(agi_env.out_log, "ab", buffering=0)
    stderr = open(agi_env.err_log, "ab", buffering=0)
    return subprocess.Popen(cmd, shell=isinstance(cmd, str), cwd=cwd, stdout=stdout, stderr=stderr)

@st.cache_resource(show_spinner=False)
def _ensure_sidecar(view_key: str, view_page: Path, port: int):
    """Start the view's Streamlit in a separate process (one per session)."""
    if _is_port_open(port):
        return  # already running
    env = st.session_state['env']
    ip = "127.0.0.1"
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    uv = cmd_prefix + env.uv
    pyvers = env.python_version
    page_home = str(view_page.parents[2])
    env.out_log = f"{env.AGILAB_LOG_ABS / view_page.stem}.log"
    env.err_log = f"{env.AGILAB_LOG_ABS / view_page.stem}.err"

    cmd = (f"uv run --project {page_home} python -m streamlit run {view_page} --server.port {port} --server.headless true"
           f" --browser.gatherUsageStats false -- --active-app {env.active_app}")
    result = exec_bg(env, cmd, cwd=page_home)

    env = os.environ.copy()
    # Avoid leaking the main app's sys.path into the child
    env.pop("PYTHONPATH", None)

    # Wait a bit for the port to come up
    for _ in range(80):
        if _is_port_open(port):
            break
        time.sleep(0.1)


def discover_views(pages_dir: Union[str, Path]) -> list[Path]:
    """
    Dynamic discovery under env.AGILAB_PAGES_ABS with common layouts:
      - <root>/apps-pages/*.py
      - <root>/apps-pages/*/(main.py|app.py|<name>.py)
      - convenience: <root>/*.py
    Follows symlinks too.
    Returns a list of concrete script Paths.
    """
    out: set[Path] = set()
    pages_dir = Path(pages_dir).resolve()  # follow symlinks

    if pages_dir.exists():
        # Example: find all pyproject.toml files (as in your code)
        out = set()
        for subdir in pages_dir.glob("[!_.]*"):  # only depth 2 dirs
            pyproject = subdir / "pyproject.toml"
            if pyproject.is_file():
                out.add(subdir.resolve())# resolve symlinks for consistency

    return sorted(out, key=lambda p: (p.as_posix(), p.name))

# --- helper: hide the parent (this page's) Streamlit sidebar when embedding a child ---
def _hide_parent_sidebar():
    st.markdown(
        """
        <style>
        /* Hide the sidebar and its toggle button */
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarNav"] { display: none !important; }
        [data-testid="collapsedControl"] { display: none !important; }
        /* Pull content to the left since sidebar is gone */
        [data-testid="stAppViewContainer"] { margin-left: 0 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
# --- end helper ---

# =============== Page logic ==================

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

async def main():
    # Navigation by query param
    qp = st.query_params
    current_page = qp.get("current_page")

    if 'env' not in st.session_state:
        apps_dir_value = st.session_state.get("apps_dir")
        env = AgiEnv(
            apps_dir=Path(apps_dir_value).expanduser() if apps_dir_value else None,
            verbose=0,
        )
        env.init_done = True
        st.session_state['env'] = env
        st.session_state['IS_SOURCE_ENV'] = env.is_source_env
        st.session_state['IS_WORKER_ENV'] = env.is_worker_env
    else:
        env = st.session_state['env']

    page_title = "Explore"
    # Sidebar header/logo
    render_logo(page_title)

    # Sidebar: project selection
    projects = env.projects
    current_project = env.app if env.app in projects else (projects[0] if projects else None)
    select_project(projects, current_project)  # may be updated by select_project

    # Where to store selected pages per project
    project = env.app
    app_settings = Path(env.apps_dir) / project / "src" / "app_settings.toml"

    # Discover pages dynamically under AGILAB_PAGES_ABS
    all_views = discover_views(Path(env.AGILAB_PAGES_ABS))

    # Route: only render a view when the param is a concrete path, not "main"/empty
    if current_page and current_page not in ("", "main"):
        try:
            await render_view_page(Path(current_page))
        except Exception as e:
            st.error(f"Failed to render view: {e}")
        return

    # ---------- Main "Explore" page ----------
    st.title(page_title)

    if not all_views:
        st.info("No pages found under AGILAB_PAGES_ABS.")
        return

    # Load config and ensure structure
    cfg = _read_config(app_settings)
    if "pages" not in cfg:
        cfg["pages"] = {}
    project_views: list[str] = cfg.get("pages", {}).get("view_module", [])

    # Multiselect with current selections
    view_names = [p.stem for p in all_views]
    # Keep only those that still exist
    preselect = [v for v in project_views if v in view_names]

    selection_key = f"view_selection__{project or 'default'}"

    if selection_key not in st.session_state:
        st.session_state[selection_key] = list(preselect)
    else:
        # Sanitize any persisted selection to only include currently available views
        current = st.session_state.get(selection_key, [])
        if not isinstance(current, list):
            current = []
        cleaned = [v for v in current if v in view_names]
        if cleaned != current:
            st.session_state[selection_key] = cleaned

    # Styling is handled globally in resources/theme.css. No per-page override here to avoid double borders.

    selected_views = st.multiselect(
        "Select page to expose on the home page",
        view_names,
        key=selection_key,
        help="These will appear as buttons below."
    )

    cleaned_selection = [v for v in selected_views if v in view_names]
    if cleaned_selection != selected_views:
        st.session_state[selection_key] = cleaned_selection
        selected_views = cleaned_selection

    if cfg.get("pages", {}).get("view_module") != selected_views:
        cfg.setdefault("pages", {})["view_module"] = selected_views
        _write_config(app_settings, cfg)

    # Show buttons for the selected pages
    st.divider()
    cols = st.columns(min(len(selected_views), 4) or 1)

    if selected_views:
        for i, view_name in enumerate(selected_views):
            view_path = next((p for p in all_views if p.stem == view_name), None)
            module = view_name.replace('-', '_')
            view_path = view_path / "src" / module / (module + ".py")
            if not view_path:
                st.error(f"Page '{view_name}' not found.")
                continue
            with cols[i % len(cols)]:
                if st.button(view_name, type="primary", use_container_width=True):
                    view_str = str(view_path.resolve())
                    st.session_state["current_page"] = view_str
                    st.query_params["current_page"] = view_str
                    st.rerun()
    else:
        st.write("No Page selected. Pick some above.")

async def render_view_page(view_path: Path):
    """Render a specific view by launching it as a sidecar app in its own venv and iframing it."""
    # Hide THIS page's sidebar while a child view is displayed
    _hide_parent_sidebar()

    back_col, title_col, _ = st.columns([1, 6, 1])
    with back_col:
        if st.button("← Back to Explore", type="primary"):
            st.session_state["current_page"] = "main"
            st.query_params["current_page"] = "main"
            st.rerun()
    with title_col:
        st.subheader(f"View: `{view_path.stem}`")

    # --- sidecar per-view run + iframe embed ---
    # Unique key for port hashing (works even if two Page share the same filename)
    view_key = f"{view_path.stem}|{view_path.parent.as_posix()}"
    port = _port_for(view_key)
    _ensure_sidecar(view_key, view_path, port)

    # Regular iframe (child keeps its own sidebar if it has one)
    components.iframe(f"http://127.0.0.1:{port}/?embed=true", height=900)

    # --- end sidecar embed ---

if __name__ == "__main__":
    asyncio.run(main())
