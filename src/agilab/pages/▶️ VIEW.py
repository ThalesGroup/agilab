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
import asyncio
import streamlit as st
import streamlit.components.v1 as components
from IPython.lib import backgroundjobs as bg
import logging

# Use modern TOML libraries
import tomli         # For reading TOML files (read as binary)
import tomli_w       # For writing TOML files (write as binary)

# Project utilities (unchanged)
from agilab.pagelib import activate_mlflow, get_about_content, render_logo, select_project
from agi_env import AgiEnv, normalize_path

logger = logging.getLogger(__name__)

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

jobs = bg.BackgroundJobManager()

# ---------- FIX 1: make exec_bg actually spawn the process (no @staticmethod) ----------
def exec_bg(cmd: Union[str, List[str]], cwd: str, env: dict | None = None) -> subprocess.Popen:
    """
    Execute command in background (non-blocking) with an optional working directory.
    Accepts either a shell string or argv list; returns the Popen handle.
    """
    if isinstance(cmd, str):
        proc = subprocess.Popen(cmd, shell=True, cwd=cwd, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    else:
        proc = subprocess.Popen(cmd, shell=False, cwd=cwd, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return proc
# --------------------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
async def _ensure_sidecar(view_key: str, view_page: Path, port: int):
    """Start the view's Streamlit in a separate process (one per session)."""
    if _is_port_open(port):
        return  # already running

    env = st.session_state['env']
    ip = "127.0.0.1"
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    uv = cmd_prefix + env.uv  # (kept; not strictly needed for the next line but preserved)
    pyvers = env.python_version
    page_home = str(view_page.parents[2])

    # Keep your exact CLI; ensure the space before --browser flag
    cmd = (f"uv run python -m streamlit run {view_page} --server.port {port} --server.headless true"
           f" --browser.gatherUsageStats false")

    # Provide a clean env if desired (we'll pass it to Popen)
    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)

    result = exec_bg(cmd, cwd=page_home, env=child_env)
    logger.info(f"{cmd} result\n{result}")

    # Wait a bit for the port to come up
    for _ in range(80):
        if _is_port_open(port):
            break
        time.sleep(0.1)

@st.cache_resource(show_spinner=False)
async def _ensure_sidecar2(view_key: str, view_page, port: int):
    """Launch or reuse a sidecar Streamlit for `script` on `port`."""
    if _is_port_open(port):
        return

    host = os.getenv("AGILAB_VIEWS_HOST", "127.0.0.1")  # set to LAN IP if you open parent via Network URL

    base_argv = ["-m", "streamlit", "run", str(view_page),
                 "--server.port", str(port),
                 "--server.address", host,
                 "--server.headless", "true",
                 "--browser.gatherUsageStats", "false"]

    candidates: list[list[str]] = []
    uv = os.getenv("UV_BIN", "uv")  # override if needed
    candidates.append([uv, "run", "python", *base_argv])      # uv run python -m streamlit ...
    candidates.append([sys.executable, *base_argv])           # fallback: main interpreter

    logs_dir = Path(os.getenv("AGILAB_VIEWS_LOGDIR", "~/.agilab/sidecars")).expanduser()
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{Path(view_page).stem}.log"

    for argv in candidates:
        # run from the repo root (two levels above src/module/module.py)
        cwd = str(Path(view_page).parents[2])
        exec_bg(argv, cwd=cwd)

        for _ in range(120):
            if _is_port_open(port):
                break
            time.sleep(0.1)
        if _is_port_open(port):
            break
    else:
        st.error(f"Sidecar failed to bind on {host}:{port}. See log: {log_path}")
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
                tail = fh.read()[-2000:]
            with st.expander("Last log lines"):
                st.code(tail)
        except Exception:
            pass

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
    # ---------- FIX 2: routing guard so "main"/"" don't get treated as a file ----------
    qp = st.query_params
    current_page = qp.get("current_page")
    if current_page and current_page not in ("", "main"):
        try:
            await render_view_page(Path(current_page))
        except Exception as e:
            st.error(f"Failed to render view: {e}")
        return
    # -----------------------------------------------------------------------------------

    if 'env' not in st.session_state:
        env = AgiEnv(verbose=0)
        env.init_done = True
        st.session_state['env'] = env
    else:
        env = st.session_state['env']

    page_title = "Views"
    # Sidebar header/logo — keep your call with the title
    render_logo(page_title)

    # Sidebar: project selection
    projects = env.projects
    current_project = env.app if env.app in projects else (projects[0] if projects else None)
    select_project(projects, current_project) # may be updated by select_project

    # Where to store selected views per project
    project = env.app
    app_settings = Path(env.apps_dir) / project / "src" / "app_settings.toml"

    # Discover views dynamically under AGILAB_VIEWS_ABS
    all_views = discover_views(Path(env.AGILAB_VIEWS_ABS))

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
            module = view_name.replace('-','_')
            view_path = view_path / "src" / module / (module + ".py")
            if not view_path or not view_path.exists():
                st.error(f"View '{view_name}' not found at: {view_path}")
                continue
            with cols[i % len(cols)]:
                if st.button(view_name, use_container_width=True):
                    view_str = str(view_path.resolve())
                    st.session_state["current_page"] = view_str
                    st.query_params["current_page"] = view_str
                    st.rerun()
    else:
        st.write("No views selected. Pick some above.")

async def render_view_page(view_path: Path):
    """Render a specific view by launching it as a sidecar app in its own venv and iframing it."""
    back_col, title_col, _ = st.columns([1, 6, 1])
    with back_col:
        if st.button("← Back to Views"):
            # Reset to main page; guard in main() will prevent treating "main" as a path
            st.session_state["current_page"] = "main"
            st.query_params["current_page"] = "main"
            st.rerun()
    with title_col:
        st.subheader(f"View: `{view_path.stem}`")

    if not view_path.exists():
        st.error(f"View script not found: {view_path}")
        return

    # --- sidecar per-view run + iframe embed ---
    view_key = f"{view_path.stem}|{view_path.parent.as_posix()}"
    port = _port_for(view_key)
    await _ensure_sidecar(view_key, view_path, port)

    # Keep 127.0.0.1 to match your current workflow; add ?embed=true for nicer chrome
    components.iframe(f"http://127.0.0.1:{port}/?embed=true", height=900)
    # --- end sidecar embed ---


if __name__ == "__main__":
    asyncio.run(main())
