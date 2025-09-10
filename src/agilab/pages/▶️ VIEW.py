# Streamlit page: dynamic view discovery under env.AGILAB_VIEWS_ABS.
# Each view runs as a sidecar Streamlit process and is embedded via <iframe>.
# Minimal changes, no per-view venv lookup (as requested).

from __future__ import annotations

import hashlib
import os
import socket
import sys
import time
from pathlib import Path
from typing import Dict, List

import streamlit as st
import streamlit.components.v1 as components

# ---- TOML read/write helpers (no hard deps) ----
try:  # Python 3.11+
    import tomllib as _toml_read  # type: ignore[attr-defined]
except Exception:  # fallback
    import tomli as _toml_read  # type: ignore[no-redef]

def _toml_load(path: Path) -> Dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return _toml_read.load(f)

def _toml_dump(path: Path, data: Dict):
    # Try tomli_w; if missing, write the tiny shape we need by hand.
    try:
        import tomli_w  # type: ignore
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            tomli_w.dump(data, f)  # type: ignore
        return
    except Exception:
        pass
    views = data.get("views", {})
    view_module = views.get("view_module", [])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[views]\n")
        f.write("view_module = [")
        f.write(", ".join(repr(s) for s in view_module))
        f.write("]\n")

# ---- Query param helpers (Streamlit version friendly) ----
def _get_qp() -> Dict[str, str]:
    qp = getattr(st, "query_params", None)
    if qp is not None:
        return dict(qp)
    return {k: v[0] if isinstance(v, list) and v else v
            for k, v in st.experimental_get_query_params().items()}  # type: ignore[attr-defined]

def _set_qp(**params):
    if hasattr(st, "query_params"):
        for k, v in params.items():
            st.query_params[k] = v  # type: ignore[attr-defined]
    else:
        st.experimental_set_query_params(**params)  # type: ignore[attr-defined]

# ---- Agilab imports (from your project) ----
from agilab.pagelib import activate_mlflow, get_about_content, render_logo, select_project
from agi_env import AgiEnv

# ---------------- Streamlit page config ----------------
st.set_page_config(layout="wide", menu_items=get_about_content())

# ---------------- Sidecar helpers ----------------
def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0

def _port_for(key: str) -> int:
    """Deterministic port in [8600..8899] from a key (e.g., view path)."""
    base = int(os.getenv("AGILAB_VIEWS_BASE_PORT", "8600"))
    span = 300
    h = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16)
    return base + (h % span)

@st.cache_resource(show_spinner=False)
def _ensure_sidecar(view_key: str, venv, script: Path, port: int):
    """Launch or reuse a sidecar Streamlit for `script` on `port`."""
    if _is_port_open(port):
        return

    host = os.getenv("AGILAB_VIEWS_HOST", "127.0.0.1")  # match how you open the parent app
    script_abs = str(script.resolve())

    base_argv = ["-m", "streamlit", "run", script_abs,
                 "--server.port", str(port),
                 "--server.address", host,
                 "--server.headless", "true",
                 "--browser.gatherUsageStats", "false"]

    candidates: list[list[str]] = []
    uv = os.getenv("UV_BIN", "uv")
    candidates.append([uv, "run", "python", *base_argv])      # uv run python -m streamlit ...
    candidates.append([sys.executable, *base_argv])           # fallback: main interpreter

    # Optional logs to help when it fails before binding
    logs_dir = Path(os.getenv("AGILAB_VIEWS_LOGDIR", "~/.agilab/sidecars")).expanduser()
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{script.stem}.log"

    # Try each candidate until port is up
    for argv in candidates:
        try:
            # IMPORTANT: run from the view folder so relative imports work
            # Keep PYTHONPATH as-is (your project layout may rely on it)
            try:
                AgiEnv.run_async(argv, venv=venv, cwd=str(script.parent),
                                 stdout=str(log_path), stderr=str(log_path))
            except TypeError:
                # If your AgiEnv.run_async doesn't accept stdout/stderr
                AgiEnv.run_async(argv, venv=venv, cwd=str(script.parent))
        except Exception:
            # try next candidate
            continue

        # wait up to ~12s for the port
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

# ---------------- Discovery ----------------
def discover_views(root: str | Path) -> List[Path]:
    """
    Dynamic discovery under env.AGILAB_VIEWS_ABS with common layouts:
      - <root>/views/*.py
      - <root>/views/*/(main.py|app.py|<name>.py)
      - (also) <root>/*.py
    """
    root = Path(root)
    out: set[Path] = set()

    views_dir = root / "views"
    if views_dir.exists():
        for p in views_dir.glob("*.py"):
            if not p.name.startswith("_"):
                out.add(p)
        for d in views_dir.glob("*/"):
            d = Path(d)
            for fname in ("main.py", "app.py", f"{d.name}.py"):
                p = d / fname
                if p.exists():
                    out.add(p)
                    break

    for p in root.glob("*.py"):
        if not p.name.startswith("_"):
            out.add(p)

    return sorted(out, key=lambda p: (p.parent.as_posix(), p.name))

# ---------------- Page logic ----------------
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

def _read_config(path: Path) -> Dict:
    try:
        return _toml_load(path)
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
        return {}

def _write_config(path: Path, cfg: Dict):
    try:
        _toml_dump(path, cfg)
    except Exception as e:
        st.error(f"Error updating configuration: {e}")

def main():
    # --- routing guard (prevents treating "main" as a file path) ---
    qp = _get_qp()
    current_page = qp.get("current_page")
    if current_page and current_page not in ("", "main"):
        try:
            render_view_page(Path(current_page))
        except Exception as e:
            st.error(f"Failed to render view: {e}")
        st.stop()
    # ---------------------------------------------------------------

    env = _init_env()
    _ensure_servers(env)

    render_logo()

    # Sidebar: project selection
    projects = env.projects
    current_project = env.app if env.app in projects else (projects[0] if projects else None)
    select_project(projects, current_project)
    env = st.session_state["env"]  # may be updated by select_project

    project = env.app
    app_settings = Path(env.apps_dir) / project / "src" / "app_settings.toml"

    # Discover views dynamically
    all_views = discover_views(env.AGILAB_VIEWS_ABS)

    # ---------- Main "Views" page ----------
    st.title("Views")

    if not all_views:
        st.info("No views found under AGILAB_VIEWS_ABS.")
        return

    cfg = _read_config(app_settings)
    cfg.setdefault("views", {})
    prev_selected: List[str] = cfg["views"].get("view_module", [])

    view_names = [p.stem for p in all_views]
    preselect = [v for v in prev_selected if v in view_names]

    selected = st.multiselect(
        "Select views to expose on the home page",
        view_names,
        default=preselect,
        help="These will appear as buttons below."
    )

    cfg["views"]["view_module"] = selected
    _write_config(app_settings, cfg)

    st.divider()
    cols = st.columns(min(len(selected), 4) or 1)

    if selected:
        for i, name in enumerate(selected):
            path = next((p for p in all_views if p.stem == name), None)
            if not path:
                st.error(f"View '{name}' not found.")
                continue
            with cols[i % len(cols)]:
                if st.button(name, use_container_width=True):
                    _set_qp(current_page=str(path.resolve()))
                    st.session_state["current_page"] = str(path.resolve())
                    st.rerun()
    else:
        st.write("No views selected. Pick some above.")

def render_view_page(view_path: Path):
    """Render a specific view by launching it as a sidecar app and iframing it."""
    back_col, title_col, _ = st.columns([1, 6, 1])
    with back_col:
        if st.button("← Back to Views"):
            # normalize/reset router
            if hasattr(st, "query_params"):
                try:
                    del st.query_params["current_page"]  # preferred
                except Exception:
                    st.query_params["current_page"] = "main"
            else:
                st.experimental_set_query_params(current_page="main")  # type: ignore[attr-defined]
            st.session_state["current_page"] = "main"
            st.rerun()
    with title_col:
        st.subheader(f"View: `{view_path.stem}`")

    if not view_path.exists():
        st.error(f"View script not found: {view_path}")
        return

    # Unique key for port hashing (works even if two views share the same filename)
    view_key = f"{view_path.stem}|{view_path.parent.as_posix()}"
    port = _port_for(view_key)

    # No per-view venv lookup (as requested) → pass venv=None
    _ensure_sidecar(view_key, None, view_path, port)

    host = os.getenv("AGILAB_VIEWS_HOST", "127.0.0.1")
    components.iframe(f"http://{host}:{port}/?embed=true", height=900)

# --------- Call main (NO top-level await) ---------
main()
