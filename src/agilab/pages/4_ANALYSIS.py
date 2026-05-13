# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
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
import html
import re
import inspect
from typing import Any, Union
import asyncio
import shlex
import importlib.util
import traceback
from urllib.parse import quote, urlencode
import shutil

from pathlib import Path

os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
import logging
import subprocess

_import_guard_path = Path(__file__).resolve().parents[1] / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_symbols = _import_guard_module.import_agilab_symbols
import_agilab_module = _import_guard_module.import_agilab_module
_page_docs_module = import_agilab_module(
    "agilab.page_docs",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
get_docs_menu_items = _page_docs_module.get_docs_menu_items
import_agilab_symbols(
    globals(),
    "agilab.analysis_page_state",
    {
        "build_analysis_view_selection_state": "build_analysis_view_selection_state",
        "normalize_view_name": "_analysis_normalize_view_name",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "analysis_page_state.py",
    fallback_name="agilab_analysis_page_state_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pinned_expander",
    {
        "render_pinned_expanders": "render_pinned_expanders",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.workflow_ui",
    {
        "render_page_context": "render_page_context",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.page_project_selector",
    {
        "render_project_selector": "render_project_selector",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_project_selector.py",
    fallback_name="agilab_page_project_selector_fallback",
)

# Use modern TOML libraries
import tomllib       # For reading TOML files (read as binary)
import tomli_w       # For writing TOML files (write as binary)

# Project utilities (unchanged)
from agi_gui.pagelib import (
    render_logo,
    on_project_change,
    inject_theme,
)
from agi_gui.ux_widgets import compact_choice
from agi_env import AgiEnv
from agi_env.app_settings_support import prepare_app_settings_for_write
from agi_gui.ui_support import load_last_active_app, store_last_active_app

logger = logging.getLogger(__name__)

_ANALYSIS_VIEW_PROFILES = {
    "view_maps": (
        "Map evidence",
        "Inspect trajectories, positions, and geographic consistency after a flight run.",
        "Start here for flight_project outputs.",
    ),
    "view_maps_3d": (
        "3D cartography",
        "Explore altitude-aware trajectories and spatial relationships.",
        "Use after the 2D map confirms the right dataset.",
    ),
    "view_maps_network": (
        "Network topology",
        "Inspect nodes, links, routing overlays, and connectivity metrics.",
        "Use for network-centric apps, not the default flight map.",
    ),
    "view_barycentric": (
        "Trade-off view",
        "Compare two axes and expose balance, drift, or outlier behavior.",
        "Use when you need a compact comparison plot.",
    ),
    "view_training_analysis": (
        "Training evidence",
        "Compare training runs, metrics, tags, and learning curves.",
        "Use after SB3, GA, or PPO training produces run artifacts.",
    ),
    "view_inference_analysis": (
        "Inference evidence",
        "Inspect routed demand, latency, bearer mix, and delivered traffic.",
        "Use after inference or network simulation exports allocations.",
    ),
    "view_release_decision": (
        "Release decision",
        "Aggregate run evidence into pass/fail release support.",
        "Use before publishing a demo, package, or validation result.",
    ),
    "view_shap_explanation": (
        "SHAP explanation",
        "Inspect local feature attributions exported by SHAPKit, shap, or compatible explainers.",
        "Use after a model workflow writes feature-attribution artifacts.",
    ),
    "view_forecast_analysis": (
        "Forecast evidence",
        "Review forecast metrics and predictions.",
        "Use after a forecasting pipeline writes analysis artifacts.",
    ),
    "view_queue_resilience": (
        "Queue resilience",
        "Review queue metrics, delivery, and overload symptoms.",
        "Use for failure-injection and queue-behavior examples.",
    ),
    "view_relay_resilience": (
        "Relay queue resilience",
        "Compare relay queue behavior across runs and degraded conditions.",
        "Use for relay-network resilience analysis.",
    ),
    "view_data_io_decision": (
        "Data decision",
        "Inspect data ingestion decisions and feature evidence.",
        "Use for data-quality and source-selection examples.",
    ),
    "view_autoencoder_latenspace": (
        "Latent-space view",
        "Inspect reduced-dimensional embeddings and clustering behavior.",
        "Use after dimensionality-reduction workflows.",
    ),
    "view_autoencoder_latentspace": (
        "Latent-space view",
        "Inspect reduced-dimensional embeddings and clustering behavior.",
        "Use after dimensionality-reduction workflows.",
    ),
}

_ANALYSIS_ARTIFACT_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".parquet",
    ".npz",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".html",
}

_NOTEBOOK_IGNORED_DIRS = {
    ".git",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "venv",
}

_MINIMAL_PAGE_TEMPLATE_PYPROJECT = """[project]
name = "view-{module_slug}"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "streamlit",
    "agi-env",
    "agi-node",
]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
"""

_MINIMAL_PAGE_TEMPLATE_SCRIPT = """from __future__ import annotations

import argparse
from pathlib import Path

import streamlit as st

try:
    from agi_env import AgiEnv
except (ImportError, ModuleNotFoundError, OSError) as exc:  # pragma: no cover - dependency hint
    AgiEnv = None
    _AGI_ENV_IMPORT_ERROR = exc
else:  # pragma: no cover
    _AGI_ENV_IMPORT_ERROR = None


PAGE_TITLE = "__TITLE__"


def _parse_active_app() -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app")
    args, _ = parser.parse_known_args()
    if args.active_app:
        return args.active_app

    # Support fallback query arguments in case page gets launched with custom params.
    for key in ("active_app", "active-app", "project"):
        value = st.query_params.get(key, "")
        if value:
            return value
    return ""


def _load_project_env(active_app: str):
    if AgiEnv is None:
        st.error(
            "This template requires the ``agi-env`` package available in this page environment."
        )
        st.error(f"Import error: {_AGI_ENV_IMPORT_ERROR}")
        st.stop()

    active_app_path = Path(active_app).expanduser().resolve()
    if not active_app_path.exists():
        st.error(f"Provided active project path does not exist: {active_app_path}")
        st.stop()

    return AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)


def main() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        layout="wide",
        menu_items=get_docs_menu_items(html_file="explore-help.html"),
    )
    st.title(PAGE_TITLE)

    active_app = _parse_active_app().strip()
    if not active_app:
        st.info(
            "Open this page from AGILAB Analysis so the active project is passed via --active-app."
        )
        return

    env = _load_project_env(active_app)
    st.subheader(f"Project: {env.app}")
    st.caption(f"Project path: {env.active_app}")

    dataset_root = env.app_data_rel / "dataset"
    if not dataset_root.exists():
        st.info("No dataset folder yet. Run your pipeline before exploring outputs here.")
        return

    csv_files = sorted(dataset_root.glob("*.csv"))
    if not csv_files:
        st.warning("No CSV file found in the dataset folder yet.")
        return

    st.success(f"{len(csv_files)} CSV file(s) available.")
    with st.expander("Dataset files", expanded=False):
        for file in csv_files:
            st.write(file.name)


if __name__ == "__main__":
    main()
"""

_MINIMAL_PAGE_TEMPLATE_README = """# {title}

This bundle was generated from AGILab's minimal custom page template.

Quick start:

- Open the page from Analysis after selecting a project.
- Use the embedded AGILAB sidecar runner; `--active-app` is automatically passed.
- Export results first, then refresh this page to inspect available CSV outputs.

Files:

- `pyproject.toml`: page-specific dependency declaration.
- `src/{module}/__init__.py`: package module marker.
- `src/{module}/{module}.py`: Streamlit page script.

You can extend this page with your own charts, plots, and actions.
"""


def _normalize_page_name(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    value = re.sub(r"\s+", "_", raw)
    value = re.sub(r"[^0-9a-zA-Z_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if value and value[0].isdigit():
        value = f"page_{value}"
    return value.lower() or "analysis_page"


def _next_page_name(base_name: str, pages_root: Path) -> str:
    name = _normalize_page_name(base_name)
    if not name:
        name = "analysis_view"
    candidate = name
    counter = 2
    while (pages_root / candidate).exists():
        candidate = f"{name}_{counter}"
        counter += 1
    return candidate


def _write_minimal_view_template(
    pages_root: Path, module_name: str
) -> tuple[Path, Path, Path]:
    """
    Create a minimal page bundle from template files.

    Returns:
        tuple: (bundle_root, entrypoint_path, readme_path)
    """
    pages_root = pages_root.resolve()
    bundle_root = pages_root / module_name
    src_root = bundle_root / "src" / module_name
    entrypoint = src_root / f"{module_name}.py"
    readme = bundle_root / "README.md"
    pyproject = bundle_root / "pyproject.toml"
    package_init = src_root / "__init__.py"
    bundle_root.mkdir(parents=True, exist_ok=True)
    src_root.mkdir(parents=True, exist_ok=True)

    page_title = module_name
    pyproject_payload = _MINIMAL_PAGE_TEMPLATE_PYPROJECT.replace("{module_slug}", module_name)
    script_payload = (
        _MINIMAL_PAGE_TEMPLATE_SCRIPT.replace("__TITLE__", page_title.replace('"', '\\"'))
        .replace("__MODULE__", module_name)
    )
    readme_payload = (
        _MINIMAL_PAGE_TEMPLATE_README.replace("{title}", page_title)
        .replace("{module}", module_name)
    )

    if not pyproject.exists():
        pyproject.write_text(pyproject_payload, encoding="utf-8")
    if not entrypoint.exists():
        entrypoint.write_text(script_payload, encoding="utf-8")
    if not package_init.exists():
        package_init.write_text("", encoding="utf-8")
    if not readme.exists():
        readme.write_text(readme_payload, encoding="utf-8")

    return bundle_root, entrypoint, readme

# =============== Streamlit page config ==================
st.set_page_config(
    layout="wide",
    menu_items=get_docs_menu_items(html_file="explore-help.html"),
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
    base_value = os.getenv("AGILAB_PAGES_BASE_PORT", os.getenv("AGILAB_PAGES_VENVS_ABS", "8600"))
    try:
        base = int(base_value)
    except (TypeError, ValueError):
        base = 8600
    span = 300
    h = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16)
    return base + (h % span)


def _resolve_page_project_root(view_page: Path) -> Path | None:
    """Return the best uv project root for a page file.

    We prefer the nearest ancestor that contains a pyproject.toml and fallback to a
    conservative parent-based path.
    """
    cursor = view_page
    if cursor.is_file():
        cursor = cursor.parent
    for parent in [cursor, *cursor.parents]:
        candidate = Path(parent)
        if (candidate / "pyproject.toml").exists():
            return candidate

    # Legacy layout fallback (matching existing page package structure).
    fallback = cursor
    for _ in range(3):
        if not fallback.parent:
            break
        fallback = fallback.parent
    if (fallback / "pyproject.toml").exists():
        return fallback
    return None


def _iter_page_project_roots(view_path: Path) -> list[Path]:
    """Return all ancestor directories containing a `pyproject.toml` for a page path."""
    cursor = view_path if view_path.is_dir() else view_path.parent
    candidates: list[Path] = []
    for parent in [cursor, *cursor.parents]:
        p = parent.resolve()
        if (p / "pyproject.toml").exists():
            candidates.append(p)
    return candidates


def _short_page_token(view_path: Path) -> str:
    return hashlib.sha1(str(view_path.resolve()).encode("utf-8")).hexdigest()[:10]


def _page_log_paths(view_path: Path, logs_root: Path) -> tuple[str, str]:
    stem = re.sub(r"[^0-9A-Za-z_-]", "_", view_path.stem) or "analysis_view"
    token = _short_page_token(view_path)
    base = logs_root / f"{stem}_{token}"
    return str(base.with_suffix(".log")), str(base.with_suffix(".err"))


def _page_pythonpath(*paths: Path) -> str:
    values = [str(path) for path in paths if str(path).strip()]
    existing = os.getenv("PYTHONPATH")
    if existing:
        values.append(existing)
    # Preserve deterministic order while deduplicating.
    ordered_unique: list[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered_unique.append(value)
    return os.pathsep.join(ordered_unique)


def _safe_existing_dir(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        return path.resolve() if path.exists() and path.is_dir() else None
    except OSError:
        return None


def _page_apps_path(current_file: str | Path = __file__) -> Path | None:
    """Return the bundled apps root for source and packaged page layouts."""
    current_path = Path(current_file).resolve()
    candidates: list[Path] = []
    parents = current_path.parents
    if len(parents) > 1:
        candidates.append(parents[1] / "apps")
    if len(parents) > 2:
        candidates.append(parents[2] / "agilab" / "apps")
        candidates.append(parents[2] / "apps")
    for candidate in candidates:
        existing = _safe_existing_dir(candidate)
        if existing is not None:
            return existing
    return None


def _candidate_app_paths(apps_path: Path | None, value: str | Path | None) -> list[Path]:
    if value is None:
        return []
    raw_value = str(value).strip()
    if not raw_value:
        return []
    try:
        provided = Path(raw_value).expanduser()
    except (RuntimeError, TypeError, ValueError):
        return []

    candidates: list[Path] = []
    if provided.is_absolute() or len(provided.parts) > 1:
        candidates.append(provided)
        candidates.append(provided.parent / "builtin" / provided.name)

    if apps_path is not None:
        root = Path(apps_path).expanduser()
        if len(provided.parts) == 1:
            candidates.append(root / raw_value)
        candidates.append(root / provided.name)
        candidates.append(root / "builtin" / provided.name)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _resolve_app_path(apps_path: Path | None, value: str | Path | None) -> Path | None:
    for candidate in _candidate_app_paths(apps_path, value):
        existing = _safe_existing_dir(candidate)
        if existing is not None:
            return existing
    return None


def _apps_path_for_active_app(active_app_path: Path) -> Path:
    parent = active_app_path.parent
    if parent.name == "builtin" and parent.parent.name == "apps":
        return parent.parent
    return parent


def _default_app_path(apps_path: Path | None) -> Path | None:
    """Return a deterministic default *_project, preferring bundled flight_project."""
    root = _safe_existing_dir(Path(apps_path).expanduser() if apps_path else None)
    if root is None:
        return None
    search_roots = [root]
    if root.name != "builtin":
        builtin_root = _safe_existing_dir(root / "builtin")
        if builtin_root is not None:
            search_roots.append(builtin_root)

    for search_root in search_roots:
        preferred = _safe_existing_dir(search_root / "flight_project")
        if preferred is not None:
            return preferred

    for search_root in search_roots:
        try:
            candidates = sorted(search_root.iterdir())
        except OSError:
            continue
        for candidate in candidates:
            existing = _safe_existing_dir(candidate)
            if existing is not None and existing.name.endswith("_project"):
                return existing
    return None


def _stored_active_app_path(env: AgiEnv) -> Path | None:
    active_app = getattr(env, "active_app", None)
    if active_app:
        try:
            return Path(active_app)
        except (RuntimeError, TypeError, ValueError):
            return None
    if getattr(env, "apps_path", None) and getattr(env, "app", None):
        return Path(env.apps_path) / str(env.app)
    return None


def _store_active_app(env: AgiEnv) -> None:
    active_app_path = _stored_active_app_path(env)
    if active_app_path is None:
        return
    try:
        store_last_active_app(active_app_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def _active_app_path_for_env(env: Any) -> Path | None:
    """Resolve the active project path from the current Analysis page environment."""
    apps_path_value = getattr(env, "apps_path", None)
    if apps_path_value:
        for name in (getattr(env, "target", None), getattr(env, "app", None)):
            if not name:
                continue
            resolved = _resolve_app_path(Path(apps_path_value), str(name))
            if resolved is not None:
                return resolved

    active_app_value = getattr(env, "active_app", None)
    if active_app_value:
        candidate = Path(active_app_value)
        if candidate.exists():
            return candidate
    return None


def _active_app_arg_for_env(env: Any) -> str:
    active_app_path = _active_app_path_for_env(env)
    if active_app_path is not None:
        return str(active_app_path)
    active_app_value = getattr(env, "active_app", None)
    return str(active_app_value) if active_app_value else ""


def _initialize_analysis_env(requested_app: str | None) -> AgiEnv:
    apps_path_value = st.session_state.get("apps_path")
    apps_path = Path(apps_path_value).expanduser() if apps_path_value else None
    if _safe_existing_dir(apps_path) is None:
        apps_path = _page_apps_path()

    active_app_path = _resolve_app_path(apps_path, requested_app)

    if active_app_path is None:
        active_app_path = _resolve_app_path(apps_path, st.session_state.get("app"))

    if active_app_path is None:
        active_app_path = _resolve_app_path(apps_path, os.environ.get("APP_DEFAULT"))

    if active_app_path is None:
        last_app = load_last_active_app()
        if last_app is not None:
            active_app_path = _resolve_app_path(apps_path or _apps_path_for_active_app(Path(last_app)), last_app)

    if active_app_path is None:
        active_app_path = _default_app_path(apps_path)

    if active_app_path is None:
        st.error(
            "Could not determine the active project. Please select a project first or set APP_DEFAULT."
        )
        st.stop()

    apps_path = _apps_path_for_active_app(active_app_path)
    app_name = active_app_path.name
    env = AgiEnv(
        apps_path=apps_path,
        app=app_name,
        verbose=0,
    )
    env.init_done = True
    st.session_state['env'] = env
    st.session_state['IS_SOURCE_ENV'] = env.is_source_env
    st.session_state['IS_WORKER_ENV'] = env.is_worker_env
    st.session_state['apps_path'] = str(apps_path)
    st.session_state['app'] = app_name
    try:
        store_last_active_app(active_app_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return env


def exec_bg(agi_env: AgiEnv, cmd: str, cwd: str, process_env: dict[str, str] | None = None) -> None:
    """
    Execute background command
    Args:
        cmd: the command to be run
        cwd: the current working directory
        process_env: optional explicit environment for subprocess

    Returns:
        """
    stdout = open(agi_env.out_log, "ab", buffering=0)
    stderr = open(agi_env.err_log, "ab", buffering=0)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if process_env:
        env.update(process_env)
    return subprocess.Popen(
        cmd,
        shell=isinstance(cmd, str),
        cwd=cwd,
        stdout=stdout,
        stderr=stderr,
        env=env,
    )


def _terminate_process_quietly(process: subprocess.Popen[Any]) -> None:
    """Terminate a background process without surfacing timeout noise in the UI."""
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        return

def _ensure_sidecar(view_key: str, view_page: Path, port: int, active_app: str) -> bool:
    """Start the view's Streamlit in a separate process (one per session)."""
    if _is_port_open(port):
        return True
    env = st.session_state['env']
    ip = "127.0.0.1"
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    uv = cmd_prefix + env.uv
    attempts: list[str] = []
    last_error = ""
    project_roots = _iter_page_project_roots(view_page)
    if not project_roots:
        env.logger.error("Could not determine project root for page: %s", view_page)
        attempts.append(f"No uv project root with pyproject.toml for {view_page}")
        last_error = f"No uv project root with pyproject.toml for {view_page}"
    log_file, err_file = _page_log_paths(view_page, env.AGILAB_LOG_ABS)
    env.out_log = log_file
    env.err_log = err_file

    view_arg = shlex.quote(str(view_page))
    active_app_quoted = shlex.quote(active_app) if active_app else ""

    for page_root in project_roots:
        page_home = str(page_root)
        page_home_quoted = shlex.quote(page_home)
        env.logger.info("Trying analysis page sidecar project root: %s", page_home)
        attempts.append(f"Trying uv project root: {page_home}")

        sync_cmd = f"{uv} --preview-features extra-build-dependencies --project {page_home_quoted} sync"
        env.logger.info(sync_cmd)
        sync_process = exec_bg(env, sync_cmd, cwd=page_home)
        sync_code = sync_process.wait()
        if sync_code != 0:
            last_error = f"sync failed with code {sync_code} for {page_home}"
            env.logger.error(last_error)
            continue

        if env.is_source_env:
            ensure_cmd = (
                f"{uv} --preview-features extra-build-dependencies --project {page_home_quoted} run python -m ensurepip"
            )
            env.logger.info(ensure_cmd)
            ensure_process = exec_bg(env, ensure_cmd, cwd=page_home)
            if ensure_process.wait() != 0:
                last_error = f"ensurepip failed with code {ensure_process.wait()} for {page_home}"
                env.logger.error(last_error)
                continue

            install_cmd = (
                f"{uv} --preview-features extra-build-dependencies --project {page_home_quoted} run python -m pip install -e {shlex.quote(str(env.env_pck.parent.parent))}"
            )
            env.logger.info(install_cmd)
            install_process = exec_bg(env, install_cmd, cwd=page_home)
            if install_process.wait() != 0:
                last_error = f"pip install failed with code {install_process.wait()} for {page_home}"
                env.logger.error(last_error)
                continue

        run_cmd = (
            f"{uv} run --project {page_home_quoted} python -m streamlit run {view_arg} "
            f"--server.port {port} --server.address 127.0.0.1 "
            f"--server.headless true --server.enableCORS false --server.enableXsrfProtection false "
            f"--browser.gatherUsageStats false"
        )
        if active_app_quoted:
            run_cmd += f" -- --active-app {active_app_quoted}"
        env.logger.info(run_cmd)
        run_process = exec_bg(env, run_cmd, cwd=page_home)

        # Wait a bit for the port to come up
        for _ in range(240):
            if _is_port_open(port):
                return True
            if run_process.poll() is not None:
                break
            time.sleep(0.1)

        if run_process.poll() is not None and run_process.returncode != 0:
            last_error = (
                f"Sidecar process exited with code {run_process.returncode} for {page_home}"
            )
            env.logger.error(last_error)
            attempts.append(last_error)
            continue
        if _is_port_open(port):
            return True

        if run_process.poll() is None:
            _terminate_process_quietly(run_process)
        last_error = f"Sidecar streamlit did not open port {port} for {page_home}"
        attempts.append(last_error)

    if last_error:
        env.logger.error("Failed to start analysis sidecar for %s", view_page)
        env.logger.error(last_error)
        page_venv = _find_venv_for(view_page)
        fallback_targets = []
        if page_venv is not None:
            python = _python_in_venv(page_venv)
            fallback_targets.append(
                (
                    f"local page venv ({page_venv})",
                    f"{shlex.quote(str(python))} -m streamlit run {view_arg} "
                    f"--server.port {port} --server.address 127.0.0.1 "
                    f"--server.headless true --server.enableCORS false --server.enableXsrfProtection false "
                    f"--browser.gatherUsageStats false"
                    + (f" -- --active-app {active_app_quoted}" if active_app_quoted else ""),
                    _page_pythonpath(view_page.parent),
                )
            )
        fallback_targets.append(
            (
                "manager python interpreter",
                f"{shlex.quote(str(sys.executable))} -m streamlit run {view_arg} "
                f"--server.port {port} --server.address 127.0.0.1 "
                f"--server.headless true --server.enableCORS false --server.enableXsrfProtection false "
                f"--browser.gatherUsageStats false"
                + (f" -- --active-app {active_app_quoted}" if active_app_quoted else ""),
                _page_pythonpath(view_page.parent, Path(env.env_pck).parent),
            )
        )

        for label, fallback_cmd, fallback_pythonpath in fallback_targets:
            attempts.append(f"Trying fallback command: {label}")
            run_process = exec_bg(
                env,
                fallback_cmd,
                cwd=str(view_page.parent),
                process_env={"PYTHONPATH": fallback_pythonpath},
            )
            for _ in range(240):
                if _is_port_open(port):
                    return True
                if run_process.poll() is not None:
                    break
                time.sleep(0.1)
            if run_process.poll() is not None and run_process.returncode != 0:
                last_error = (
                    f"Fallback command '{label}' exited with code "
                    f"{run_process.returncode} for {view_page}"
                )
                env.logger.error(last_error)
                attempts.append(last_error)
                continue

            if run_process.poll() is None:
                _terminate_process_quietly(run_process)
            if not _is_port_open(port):
                last_error = f"Fallback command '{label}' did not open port {port} for {view_page}"
                attempts.append(last_error)
                env.logger.error(last_error)
        st.session_state[f"sidecar_attempts__{view_key}"] = attempts
    return False


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

    if not pages_dir.exists():
        return []

    for entry in pages_dir.iterdir():
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.is_dir():
            entrypoint = _find_view_entrypoint(entry)
            if entrypoint is not None:
                out.add(entrypoint if entrypoint.is_file() else entrypoint.resolve())
            continue
        if entry.is_file() and entry.suffix.lower() == ".py" and entry.name != "__init__.py":
            out.add(entry.resolve())

    return sorted(out, key=lambda p: (p.as_posix(), p.name))


def discover_project_notebooks(project_root: str | Path | None) -> dict[str, Path]:
    """Return project notebook labels mapped to concrete files under <project>/notebooks."""
    if project_root is None:
        return {}
    try:
        notebooks_root = (Path(project_root).expanduser() / "notebooks").resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return {}
    if not notebooks_root.is_dir():
        return {}

    discovered: dict[str, Path] = {}
    try:
        notebook_paths = sorted(notebooks_root.rglob("*.ipynb"), key=lambda path: path.as_posix())
    except OSError:
        return {}
    for notebook_path in notebook_paths:
        try:
            rel_path = notebook_path.resolve().relative_to(notebooks_root)
        except (OSError, ValueError):
            continue
        if any(part in _NOTEBOOK_IGNORED_DIRS or part.startswith(".") for part in rel_path.parts):
            continue
        if notebook_path.name.endswith("-checkpoint.ipynb"):
            continue
        if notebook_path.is_file():
            discovered[rel_path.as_posix()] = notebook_path.resolve()
    return discovered


def _find_view_entrypoint(view_root: Path) -> Path | None:
    """
    Resolve a page package directory into the Streamlit entry script.
    """
    if not view_root.exists():
        return None

    if view_root.is_file():
        if view_root.suffix.lower() != ".py" or view_root.name == "__init__.py":
            return None
        return view_root.resolve()

    module = view_root.name
    candidates: list[Path] = [
        view_root / "src" / module / (module + ".py"),
        view_root / "src" / module / "main.py",
        view_root / "src" / module / "app.py",
        view_root / module / f"{module}.py",
        view_root / "main.py",
        view_root / "app.py",
        view_root / f"{module}.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    src_module = view_root / "src" / module
    if src_module.is_dir():
        py_files = [
            p.resolve()
            for p in src_module.glob("*.py")
            if p.is_file() and p.name != "__init__.py"
        ]
    else:
        py_files = []
    if len(py_files) == 1:
        return py_files[0]

    # Fallback: for custom or cloned pages where folder/module names differ, pick a
    # deterministic entry script under the page bundle.
    fallback_files = []
    skip_dir = {".venv", "venv", ".git", ".pytest_cache", "__pycache__", ".mypy_cache"}
    for dirpath, dirnames, filenames in os.walk(view_root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in skip_dir and not d.startswith(".") and not d.startswith("__")
        ]
        for filename in filenames:
            if not filename.endswith(".py") or filename == "__init__.py":
                continue
            fallback_files.append(Path(dirpath) / filename)

    fallback_files = sorted((p.resolve() for p in fallback_files), key=lambda p: (len(p.parts), p.as_posix()))
    if len(fallback_files) == 1:
        return fallback_files[0]
    preferred_names = ("main", "app")
    for p in fallback_files:
        if p.stem == module:
            return p
    for p in fallback_files:
        if p.parent.name == p.stem:
            return p
    for preferred in preferred_names:
        for p in fallback_files:
            if p.stem == preferred:
                return p
    if len(fallback_files) > 1:
        return fallback_files[0]
    return None


def _analysis_page_clone_ignore(src: str, names: list[str]) -> list[str]:
    ignored = {".venv", "venv", ".git", ".pytest_cache", "__pycache__", ".mypy_cache"}
    return [name for name in names if name in ignored]


def _clone_word_substitutions(content: str, rename_map: dict[str, str]) -> str:
    if not rename_map:
        return content
    for old, new in sorted(rename_map.items(), key=lambda item: len(item[0]), reverse=True):
        if not old:
            continue
        escaped_old = re.escape(old)
        pattern = re.compile(rf"(?<![0-9A-Za-z_]){escaped_old}(?![0-9A-Za-z_])")
        content = pattern.sub(new, content)
    return content


def _rename_segment(path_name: str, rename_map: dict[str, str]) -> str:
    if not rename_map:
        return path_name
    stem = Path(path_name).stem
    suffix = Path(path_name).suffix
    for old, new in sorted(rename_map.items(), key=lambda item: len(item[0]), reverse=True):
        if not old:
            continue
        if path_name == old:
            return new
        if stem == old:
            return f"{new}{suffix}"
    return path_name


def _build_page_clone_rename_map(
    source_entry: Path, source_root: Path, new_name: str
) -> dict[str, str]:
    source_root = source_root.resolve()
    source_entry = source_entry.resolve()
    rename_map: dict[str, str] = {}
    old_names: set[str] = {source_root.name}

    if source_entry.is_file():
        if source_entry.stem not in {"main", "app"}:
            old_names.add(source_entry.stem)
        old_names.add(source_entry.parent.name)
    else:
        old_names.add(source_entry.name)

    for old_name in sorted(old_names, key=len, reverse=True):
        if not old_name or old_name == new_name:
            continue
        rename_map[old_name] = new_name
        if "-" in old_name:
            rename_map[old_name.replace("-", "_")] = new_name
        if "_" in old_name:
            rename_map[old_name.replace("_", "-")] = new_name

    return rename_map


def _rename_paths_and_contents(
    bundle_root: Path, rename_map: dict[str, str]
) -> None:
    if not rename_map:
        return

    for current in sorted(
        (p for p in bundle_root.rglob("*") if p != bundle_root),
        key=lambda p: len(p.relative_to(bundle_root).parts),
        reverse=True,
    ):
        new_name = _rename_segment(current.name, rename_map)
        if new_name != current.name:
            new_path = current.with_name(new_name)
            if not new_path.exists():
                current.rename(new_path)

    replace_exts = {".py", ".toml", ".md", ".txt", ".json", ".yaml", ".yml"}
    for path in bundle_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in replace_exts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text = _clone_word_substitutions(text, rename_map)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")


def _clone_source_label(option_path: Path, pages_root: Path | None = None) -> str:
    normalized = option_path.name
    if option_path.suffix == ".py":
        normalized = option_path.stem
        if normalized in {"main", "app"} and option_path.parent.name:
            normalized = option_path.parent.name
    if pages_root is not None:
        try:
            rel = option_path.relative_to(pages_root)
            normalized = f"{normalized} ({rel.parent.as_posix()})"
        except (OSError, ValueError):
            normalized = f"{normalized} ({option_path})"
    else:
        normalized = f"{normalized} ({option_path})"
    return normalized


def _resolve_discovered_views(all_views: list[Path]) -> dict[str, Path]:
    """Build stable display labels for discovered analysis views, skipping broken entries."""
    resolved_pages: dict[str, Path] = {}
    for view_path in all_views:
        try:
            key = _normalize_view_name(view_path.stem)
            page_root = _resolve_page_project_root(view_path)
            if page_root is not None:
                root_key = _normalize_view_name(page_root.name)
                if root_key:
                    key = root_key
            if key in resolved_pages and resolved_pages[key] != view_path:
                suffix = 2
                while f"{key} ({suffix})" in resolved_pages:
                    suffix += 1
                key = f"{key} ({suffix})"
            resolved_pages[key] = _find_view_entrypoint(view_path) or view_path
        except (OSError, RuntimeError, ValueError):
            continue
    return resolved_pages


def _resolve_default_view(
    configured_default: object,
    available_views: list[str],
    resolved_pages: dict[str, Path],
    custom_view_lookup: dict[str, Path],
) -> tuple[str | None, Path | None]:
    """Return the configured default view key and path when it is available."""
    if not isinstance(configured_default, str):
        return None, None
    raw_value = configured_default.strip()
    if not raw_value:
        return None, None

    candidates = [raw_value]
    normalized = _normalize_view_name(raw_value)
    if normalized and normalized not in candidates:
        candidates.append(normalized)

    for candidate in candidates:
        if candidate not in available_views:
            continue
        view_path = resolved_pages.get(candidate) or custom_view_lookup.get(candidate)
        if view_path is not None:
            return candidate, view_path
    return None, None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _migrate_legacy_analysis_page_config(project: str | None, cfg: dict) -> bool:
    """Migrate stale per-user analysis settings after app defaults change."""
    if project not in {"flight", "flight_project"}:
        return False
    pages = cfg.setdefault("pages", {})
    if not isinstance(pages, dict):
        cfg["pages"] = pages = {}

    raw_modules = pages.get("view_module")
    raw_excluded = pages.get("excluded_views")
    has_network_module = isinstance(raw_modules, list) and any(
        value.strip() == "view_maps_network" for value in raw_modules if isinstance(value, str)
    )
    has_network_exclusion = isinstance(raw_excluded, list) and any(
        value.strip() == "view_maps_network" for value in raw_excluded if isinstance(value, str)
    )
    has_legacy_default = pages.get("default_view") == "view_maps_network"
    if not has_legacy_default and not has_network_module and not has_network_exclusion:
        return False

    changed = False
    if has_legacy_default:
        pages["default_view"] = "view_maps"
        changed = True

    if not isinstance(raw_modules, list):
        modules = ["view_maps", "view_maps_network"]
    else:
        modules = [
            value.strip()
            for value in raw_modules
            if isinstance(value, str) and value.strip()
        ]
        if "view_maps" not in modules:
            modules.insert(0, "view_maps")
        if "view_maps_network" not in modules:
            insert_at = (
                modules.index("view_maps") + 1
                if "view_maps" in modules
                else len(modules)
            )
            modules.insert(insert_at, "view_maps_network")
        modules = _dedupe_preserve_order(modules)

    if raw_modules != modules:
        pages["view_module"] = modules
        changed = True

    excluded = (
        [
            value.strip()
            for value in raw_excluded
            if isinstance(value, str)
            and value.strip()
            and value.strip() != "view_maps_network"
        ]
        if isinstance(raw_excluded, list)
        else []
    )
    excluded = _dedupe_preserve_order(excluded)
    if raw_excluded != excluded:
        if excluded:
            pages["excluded_views"] = excluded
        else:
            pages.pop("excluded_views", None)
        changed = True
    return changed


def _excluded_view_options(cfg: dict) -> set[str]:
    pages = cfg.get("pages")
    if not isinstance(pages, dict):
        return set()
    raw_excluded = pages.get("excluded_views")
    if not isinstance(raw_excluded, list):
        return set()
    return {
        _normalize_view_name(value)
        for value in raw_excluded
        if isinstance(value, str) and _normalize_view_name(value)
    }


def _configured_view_options(
    configured_views: list[str],
    available_views: list[str],
    resolved_pages: dict[str, Path],
) -> list[str]:
    """Resolve configured view names into available multiselect options."""
    available = set(available_views)
    options: list[str] = []
    for value in configured_views:
        if value in available:
            options.append(value)
            continue
        normalized = _normalize_view_name(value)
        if normalized in resolved_pages and normalized in available:
            options.append(normalized)
    return _dedupe_preserve_order(options)


def _normalize_notebook_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized


def _configured_notebook_options(
    configured_notebooks: object,
    available_notebooks: list[str],
) -> list[str]:
    """Resolve persisted notebook selections into available multiselect options."""
    if not isinstance(configured_notebooks, list):
        return []
    available = set(available_notebooks)
    options: list[str] = []
    for value in configured_notebooks:
        normalized = _normalize_notebook_name(value)
        if normalized in available:
            options.append(normalized)
    return _dedupe_preserve_order(options)


async def _render_selected_view_route(current_page: str | None) -> bool:
    """Render a selected analysis view route and surface one explicit user-facing failure."""
    if not current_page or current_page in ("", "main"):
        return False
    try:
        await render_view_page(Path(current_page))
    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError, ImportError) as exc:
        st.error(f"Failed to render view: {exc}")
        st.caption("Full traceback")
        st.code(traceback.format_exc(), language="text")
    return True


async def _render_selected_notebook_route(current_notebook: str | None) -> bool:
    """Render a selected notebook route and surface one explicit user-facing failure."""
    if not current_notebook or current_notebook in ("", "main"):
        return False
    try:
        await render_notebook_page(Path(current_notebook))
    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError, ImportError) as exc:
        st.error(f"Failed to render notebook: {exc}")
        st.caption("Full traceback")
        st.code(traceback.format_exc(), language="text")
    return True


def _create_analysis_page_bundle(pages_root: Path, page_name: str, clone_source: str) -> Path:
    """Create a new analysis page bundle from a blank template or an existing bundle."""
    if clone_source:
        source_entry = Path(clone_source)
        source_root = _resolve_clone_source_root(source_entry)
        target_root = pages_root / page_name
        return _clone_view_bundle(source_entry, source_root, target_root)
    _, entrypoint_path, _ = _write_minimal_view_template(pages_root, page_name)
    return entrypoint_path


def _resolve_clone_source_root(view_path: Path) -> Path:
    if view_path.is_file():
        project_root = _resolve_page_project_root(view_path)
        if project_root is not None:
            return project_root
        return view_path.parent
    return _resolve_page_project_root(view_path) or view_path


def _clone_view_bundle(
    source_path: Path, source_root: Path, target_root: Path
) -> Path:
    source_path = source_path.resolve()
    source_root = source_root.resolve()
    if not source_root.exists():
        raise FileNotFoundError(f"Source bundle root does not exist: {source_root}")
    if not source_path.exists():
        raise FileNotFoundError(f"Source page does not exist: {source_path}")
    if not target_root.exists():
        shutil.copytree(
            source_root,
            target_root,
            dirs_exist_ok=False,
            ignore=_analysis_page_clone_ignore,
        )
        rename_map = _build_page_clone_rename_map(source_path, source_root, target_root.name)
        _rename_paths_and_contents(target_root, rename_map)
    else:
        raise FileExistsError(f"Target page already exists: {target_root}")

    fallback = _find_view_entrypoint(target_root)
    if fallback is None:
        raise RuntimeError(
            "Cloned page did not produce a usable entrypoint. "
            f"Please check the source page layout: {source_path}"
        )
    cloned_entry = fallback
    return cloned_entry


def _find_view_entry(
    user_value: str, pages_root: Path | None = None
) -> tuple[str, Path] | None:
    """
    Resolve a custom user value into a canonical identifier and entry script path.
    """
    raw = (user_value or "").strip()
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() and pages_root is not None:
        candidate = Path(pages_root) / candidate
    candidate = candidate.resolve()
    entry_point = _find_view_entrypoint(candidate)
    if entry_point is None:
        return None
    return str(candidate), entry_point


def _view_label(option_id: str, builtin_names: set[str]) -> str:
    if option_id in builtin_names:
        return option_id
    try:
        path = Path(option_id).resolve()
    except OSError:
        return option_id
    return f"{path.name} (custom)"


def _resolve_view_path(
    view_name: str,
    resolved_pages: dict[str, Path],
    custom_view_lookup: dict[str, Path],
) -> Path | None:
    return resolved_pages.get(view_name) or custom_view_lookup.get(view_name)


def _analysis_view_profile(view_name: str) -> tuple[str, str, str]:
    normalized = _normalize_view_name(Path(str(view_name)).stem)
    if normalized in _ANALYSIS_VIEW_PROFILES:
        return _ANALYSIS_VIEW_PROFILES[normalized]
    return (
        "Custom analysis",
        "Open a project-specific Streamlit analysis page.",
        "Use this when a packaged view does not fit the artifact.",
    )


def _safe_analysis_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    try:
        return Path(value).expanduser()
    except (TypeError, ValueError, RuntimeError):
        return None


def _active_analysis_data_root(env: Any) -> Path | None:
    for attr in ("app_data_rel", "app_data_abs"):
        path = _safe_analysis_path(getattr(env, attr, None))
        if path is not None:
            return path
    return None


def _scan_analysis_artifacts(root: Path | None, *, limit: int = 5000) -> dict[str, Any]:
    if root is None:
        return {"count": 0, "latest": None, "examples": [], "root": None, "exists": False, "truncated": False}
    try:
        root = root.expanduser()
    except (OSError, RuntimeError):
        return {"count": 0, "latest": None, "examples": [], "root": root, "exists": False, "truncated": False}
    if not root.exists():
        return {"count": 0, "latest": None, "examples": [], "root": root, "exists": False, "truncated": False}

    ignored_dirs = {".venv", "venv", "__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
    count = 0
    latest: float | None = None
    examples: list[str] = []
    truncated = False
    try:
        for current_root, dirs, files in os.walk(root):
            dirs[:] = sorted(dirname for dirname in dirs if dirname not in ignored_dirs and not dirname.startswith("."))
            for filename in sorted(files):
                path = Path(current_root) / filename
                if path.suffix.lower() not in _ANALYSIS_ARTIFACT_SUFFIXES:
                    continue
                count += 1
                if len(examples) < 3:
                    try:
                        examples.append(path.relative_to(root).as_posix())
                    except ValueError:
                        examples.append(path.name)
                try:
                    latest = max(latest or path.stat().st_mtime, path.stat().st_mtime)
                except OSError:
                    pass
                if count >= limit:
                    truncated = True
                    raise StopIteration
    except StopIteration:
        pass
    except OSError:
        return {"count": count, "latest": latest, "examples": examples, "root": root, "exists": True, "truncated": truncated}
    return {"count": count, "latest": latest, "examples": examples, "root": root, "exists": True, "truncated": truncated}


def _format_analysis_latest(timestamp: float | None) -> str:
    if timestamp is None:
        return "no artifact yet"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


_INCOMPLETE_HEADER_VALUE_TOKENS = (
    "incomplete",
    "missing",
    "no artifact",
    "no default",
    "no output",
    "not configured",
    "not selected",
    "not set",
    "unknown",
)


def _header_value_state(value: str, caption: str = "") -> str:
    normalized = f"{value or ''} {caption or ''}".strip().lower()
    if not normalized:
        return "incomplete"
    if any(token in normalized for token in _INCOMPLETE_HEADER_VALUE_TOKENS):
        return "incomplete"
    return "ready"


def _render_analysis_metric(label: str, value: str, caption: str = "") -> None:
    state = _header_value_state(value, caption)
    st.markdown(
        (
            f"<div class='agilab-header-card agilab-header-card--{state}'>"
            f"<div class='agilab-header-label'>{html.escape(label)}</div>"
            f"<div class='agilab-header-value agilab-header-value--{state}'>{html.escape(str(value))}</div>"
            f"<div class='agilab-header-caption'>{html.escape(caption)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_analysis_workspace_overview(
    env: Any,
    *,
    selection_state: Any,
    available_view_count: int,
) -> None:
    artifact_summary = _scan_analysis_artifacts(_active_analysis_data_root(env))
    artifact_count = int(artifact_summary["count"])
    project_label = str(getattr(env, "app", "") or getattr(env, "target", "") or "project")
    selected_views = tuple(getattr(selection_state, "selected_views", ()) or ())
    selected_count = len(selected_views)
    latest_label = _format_analysis_latest(artifact_summary["latest"])
    latest_value = latest_label if artifact_count else "No output"
    latest_caption = "latest file timestamp" if artifact_count else "run a project first"
    views_caption = f"{selected_count} linked to {project_label}" if selected_count else "choose views below"

    with st.container(border=True):
        cols = st.columns(3)
        with cols[0]:
            suffix = "+" if artifact_summary["truncated"] else ""
            _render_analysis_metric("Output files", f"{artifact_count}{suffix}", latest_label)
        with cols[1]:
            _render_analysis_metric("Latest output", latest_value, latest_caption)
        with cols[2]:
            _render_analysis_metric("Views selected", f"{selected_count}/{available_view_count}", views_caption)

        if not artifact_summary["exists"]:
            st.info("Run ORCHESTRATE or WORKFLOW to create analysis outputs.")
        elif not artifact_summary["examples"]:
            st.info("No output files detected yet.")


def _analysis_sidebar_view_url(project: str | None, view_path: Path) -> str:
    params = {"current_page": str(view_path.resolve())}
    if project:
        params["active_app"] = project
    return f"?{urlencode(params)}"


def _analysis_sidebar_notebook_url(project: str | None, notebook_path: Path) -> str:
    params = {"current_notebook": str(notebook_path.resolve())}
    if project:
        params["active_app"] = project
    return f"?{urlencode(params)}"


def _render_analysis_sidebar_view_launcher(
    *,
    project: str | None,
    selected_views: list[str],
    view_names: list[str],
    resolved_pages: dict[str, Path],
    custom_view_lookup: dict[str, Path],
) -> None:
    launch_options = list(dict.fromkeys(selected_views or view_names))
    if not launch_options:
        st.sidebar.info("No analysis views available.")
        return

    builtin_names = set(resolved_pages.keys())
    linked_views = set(selected_views)
    st.sidebar.markdown("### Analysis views")
    link_rows: list[str] = []
    missing_views: list[str] = []
    for view_name in launch_options:
        view_path = _resolve_view_path(view_name, resolved_pages, custom_view_lookup)
        display_label = _view_label(view_name, builtin_names)
        if view_path is None:
            missing_views.append(display_label)
            continue
        link_href = html.escape(_analysis_sidebar_view_url(project, view_path), quote=True)
        link_label = html.escape(display_label)
        link_weight = "650" if view_name in linked_views else "450"
        link_rows.append(
            "<div class='agilab-analysis-view-link'>"
            f"<a href='{link_href}' style='font-weight:{link_weight};'>{link_label}</a>"
            "</div>"
        )

    if link_rows:
        st.sidebar.markdown(
            (
                "<style>"
                ".agilab-analysis-view-links{display:flex;flex-direction:column;"
                "gap:.12rem;margin:.1rem 0 .45rem 0;}"
                ".agilab-analysis-view-link a{font-size:.88rem;line-height:1.18;text-decoration:none;}"
                ".agilab-analysis-view-link a:hover{text-decoration:underline;}"
                "</style>"
                "<div class='agilab-analysis-view-links'>"
                + "".join(link_rows)
                + "</div>"
            ),
            unsafe_allow_html=True,
        )
    for display_label in missing_views:
        st.sidebar.caption(f"Missing: {display_label}")


def _render_analysis_sidebar_notebook_launcher(
    *,
    project: str | None,
    selected_notebooks: list[str],
    notebook_names: list[str],
    notebook_lookup: dict[str, Path],
) -> None:
    launch_options = list(dict.fromkeys(selected_notebooks or notebook_names))
    if not launch_options:
        return

    linked_notebooks = set(selected_notebooks)
    st.sidebar.markdown("### Notebooks")
    link_rows: list[str] = []
    missing_notebooks: list[str] = []
    for notebook_name in launch_options:
        notebook_path = notebook_lookup.get(notebook_name)
        display_label = notebook_name
        if notebook_path is None:
            missing_notebooks.append(display_label)
            continue
        link_href = html.escape(_analysis_sidebar_notebook_url(project, notebook_path), quote=True)
        link_label = html.escape(display_label)
        link_weight = "650" if notebook_name in linked_notebooks else "450"
        link_rows.append(
            "<div class='agilab-analysis-notebook-link'>"
            f"<a href='{link_href}' style='font-weight:{link_weight};'>{link_label}</a>"
            "</div>"
        )

    if link_rows:
        st.sidebar.markdown(
            (
                "<style>"
                ".agilab-analysis-notebook-links{display:flex;flex-direction:column;"
                "gap:.12rem;margin:.1rem 0 .45rem 0;}"
                ".agilab-analysis-notebook-link a{font-size:.88rem;line-height:1.18;text-decoration:none;}"
                ".agilab-analysis-notebook-link a:hover{text-decoration:underline;}"
                "</style>"
                "<div class='agilab-analysis-notebook-links'>"
                + "".join(link_rows)
                + "</div>"
            ),
            unsafe_allow_html=True,
        )
    for display_label in missing_notebooks:
        st.sidebar.caption(f"Missing notebook: {display_label}")


def _render_custom_analysis_page_authoring(
    *,
    project: str | None,
    pages_root: Path,
    clone_source_paths: list[str],
    clone_source_labels: dict[str, str],
    custom_view_lookup: dict[str, Path],
    all_available_views: list[str],
) -> list[str]:
    with st.expander("Create analysis view", expanded=False):
        template_name = st.text_input(
            "Page name",
            placeholder="my_analysis_view",
            key=f"analysis_template_view_name__{project or 'default'}",
        )
        clone_source = compact_choice(
            st,
            "Starting point",
            clone_source_paths,
            format_func=lambda value: clone_source_labels.get(value, value),
            key=f"analysis_template_clone_source__{project or 'default'}",
            inline_limit=5,
            help="Start from a blank template or duplicate an installed page bundle.",
        )
        create_template_view = st.button(
            "Create",
            type="primary",
            key=f"analysis_create_template_view__{project or 'default'}",
            width="stretch",
        )
        if create_template_view:
            if not template_name.strip():
                st.error("Page name must not be empty.")
            elif not pages_root:
                st.error("AGILAB pages root is not available.")
            else:
                normalized_name = _normalize_page_name(template_name)
                page_name = _next_page_name(
                    normalized_name or "analysis_view",
                    pages_root,
                )
                try:
                    entrypoint_path = _create_analysis_page_bundle(
                        pages_root, page_name, clone_source
                    )
                except (FileNotFoundError, OSError, shutil.Error, ValueError, RuntimeError) as e:
                    st.error(f"Failed to create template page: {e}")
                else:
                    entry_key = str(entrypoint_path)
                    custom_view_lookup[entry_key] = entrypoint_path
                    all_available_views = sorted(set(all_available_views) | {entry_key})
                    selection_key = f"view_selection__{project or 'default'}"
                    selected_for_project = list(st.session_state.get(selection_key, []))
                    if entry_key not in selected_for_project:
                        selected_for_project.append(entry_key)
                    st.session_state[selection_key] = selected_for_project
                    bundle_root = entrypoint_path.parent
                    if entrypoint_path.parent.name == "src" and len(entrypoint_path.parents) > 2:
                        bundle_root = entrypoint_path.parent.parent
                    elif (
                        entrypoint_path.parent.name == page_name
                        and entrypoint_path.parent.parent.name == "src"
                        and len(entrypoint_path.parents) > 2
                    ):
                        bundle_root = entrypoint_path.parent.parent.parent
                    st.success(
                        "Created page bundle at "
                        f"`{bundle_root.as_posix()}` and selected it."
                    )
                    st.rerun()
    return all_available_views


def _is_hosted_analysis_runtime(env: AgiEnv) -> bool:
    """Return True when the current AGILAB runtime is hosted behind a public HF Space."""
    envars = getattr(env, "envars", {}) or {}
    space_host = str(envars.get("SPACE_HOST", "") or os.environ.get("SPACE_HOST", "") or "").strip()
    space_id = str(envars.get("SPACE_ID", "") or os.environ.get("SPACE_ID", "") or "").strip()
    return bool(space_host or space_id)


async def _render_view_page_inline(view_path: Path, active_app: str) -> None:
    """Render an apps-page inline in the current Streamlit process."""
    resolved_view = Path(view_path).resolve()
    if not resolved_view.exists():
        raise FileNotFoundError(f"Analysis view does not exist: {resolved_view}")

    module_name = f"agilab_analysis_inline_{resolved_view.stem}_{_short_page_token(resolved_view)}"
    module_dir = str(resolved_view.parent)
    original_argv = list(sys.argv)
    original_set_page_config = getattr(st, "set_page_config", None)
    inserted_path = False
    sys.modules.pop(module_name, None)

    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
        inserted_path = True

    try:
        st.set_page_config = lambda *args, **kwargs: None
        sys.argv = [resolved_view.name]
        if active_app:
            sys.argv.extend(["--active-app", active_app])

        spec = importlib.util.spec_from_file_location(module_name, resolved_view)
        if spec is None or spec.loader is None:
            raise ModuleNotFoundError(f"Unable to load analysis view from {resolved_view}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        entrypoint = getattr(module, "main", None)
        if callable(entrypoint):
            result = entrypoint()
            if inspect.isawaitable(result):
                await result
    finally:
        sys.argv = original_argv
        if original_set_page_config is not None:
            st.set_page_config = original_set_page_config
        if inserted_path:
            try:
                sys.path.remove(module_dir)
            except ValueError:
                pass
        sys.modules.pop(module_name, None)


def _project_root_for_notebook(notebook_path: Path, active_app_path: Path | None) -> Path:
    resolved_notebook = notebook_path.resolve()
    if active_app_path is not None:
        try:
            resolved_notebook.relative_to((active_app_path / "notebooks").resolve())
            return active_app_path.resolve()
        except (OSError, ValueError):
            pass
    for parent in resolved_notebook.parents:
        if parent.name == "notebooks":
            return parent.parent
    return active_app_path.resolve() if active_app_path is not None else resolved_notebook.parent


def _notebook_log_paths(notebook_path: Path, logs_root: Path) -> tuple[str, str]:
    stem = re.sub(r"[^0-9A-Za-z_-]", "_", notebook_path.stem) or "notebook"
    token = _short_page_token(notebook_path)
    base = logs_root / f"notebook_{stem}_{token}"
    return str(base.with_suffix(".log")), str(base.with_suffix(".err"))


def _notebook_lab_tree_path(notebook_path: Path, project_root: Path) -> str:
    try:
        rel_path = notebook_path.resolve().relative_to(project_root.resolve())
    except (OSError, ValueError):
        rel_path = Path(notebook_path.name)
    return quote(rel_path.as_posix(), safe="/")


def _ensure_notebook_sidecar(
    notebook_key: str,
    notebook_path: Path,
    port: int,
    project_root: Path,
) -> bool:
    """Start a local JupyterLab sidecar rooted at the active project."""
    if _is_port_open(port):
        return True
    env = st.session_state["env"]
    ip = "127.0.0.1"
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    uv = cmd_prefix + env.uv
    attempts: list[str] = []
    last_error = ""

    log_file, err_file = _notebook_log_paths(notebook_path, env.AGILAB_LOG_ABS)
    env.out_log = log_file
    env.err_log = err_file

    project_home = str(project_root.resolve())
    project_home_quoted = shlex.quote(project_home)
    notebook_arg = shlex.quote(str(notebook_path.resolve()))
    run_cmd = (
        f"{uv} --preview-features extra-build-dependencies run "
        f"--project {project_home_quoted} --with jupyterlab --with ipykernel "
        f"jupyter lab {notebook_arg} --no-browser "
        f"--ServerApp.ip=127.0.0.1 --ServerApp.port={port} "
        f"--ServerApp.open_browser=False --ServerApp.token= --ServerApp.password= "
        f"--ServerApp.allow_origin={shlex.quote('*')} --ServerApp.disable_check_xsrf=True "
        f"--ServerApp.root_dir={project_home_quoted}"
    )
    env.logger.info("Starting project notebook sidecar: %s", run_cmd)
    attempts.append(f"Trying JupyterLab sidecar rooted at: {project_home}")
    run_process = exec_bg(env, run_cmd, cwd=project_home)

    for _ in range(240):
        if _is_port_open(port):
            return True
        if run_process.poll() is not None:
            break
        time.sleep(0.1)

    if run_process.poll() is not None and run_process.returncode != 0:
        last_error = f"Notebook sidecar exited with code {run_process.returncode} for {project_home}"
        attempts.append(last_error)
        env.logger.error(last_error)
    elif run_process.poll() is None:
        _terminate_process_quietly(run_process)
        last_error = f"Notebook sidecar did not open port {port} for {project_home}"
        attempts.append(last_error)
        env.logger.error(last_error)

    if last_error:
        env.logger.error("Failed to start notebook sidecar for %s", notebook_path)
    st.session_state[f"notebook_sidecar_attempts__{notebook_key}"] = attempts
    return False


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
                return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        st.error(f"Error loading configuration: {e}")
    return {}


def _normalize_view_name(value: str) -> str:
    """Normalize page bundle labels by removing leading icon glyphs/decoration."""
    return _analysis_normalize_view_name(value)

def _write_config(path: Path, cfg: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            tomli_w.dump(prepare_app_settings_for_write(cfg), f)
    except (OSError, ValueError) as e:
        st.error(f"Error updating configuration: {e}")

async def main():
    # Navigation by query param
    qp = st.query_params
    current_page = qp.get("current_page")
    current_notebook = qp.get("current_notebook")
    requested_app = qp.get("active_app")

    if 'env' not in st.session_state:
        env = _initialize_analysis_env(requested_app)
    else:
        env = st.session_state['env']

    if env.app:
        st.query_params["active_app"] = env.app

    # Sidebar header/logo
    render_logo()
    render_pinned_expanders(st)
    render_page_context(st, page_label="ANALYSIS", env=env)

    # Sidebar: project selection
    projects = env.projects
    current_project = env.app if env.app in projects else (projects[0] if projects else None)
    render_project_selector(st, projects, current_project, on_change=on_project_change)
    if env.app:
        st.query_params["active_app"] = env.app
    if env.app:
        _store_active_app(env)

    # Where to store selected pages per project
    project = env.app
    app_settings = env.resolve_user_app_settings_file(project)

    # Discover pages dynamically under AGILAB_PAGES_ABS
    all_views = discover_views(Path(env.AGILAB_PAGES_ABS))
    resolved_pages = _resolve_discovered_views(all_views)

    custom_view_lookup: dict[str, Path] = {}
    pages_root = Path(env.AGILAB_PAGES_ABS)

    # Route: only render a child surface when the param is concrete, not "main"/empty
    if await _render_selected_notebook_route(current_notebook):
        return
    if await _render_selected_view_route(current_page):
        return

    # ---------- Main analysis page ----------

    # Load config and ensure structure
    cfg = _read_config(app_settings)
    if "pages" not in cfg:
        cfg["pages"] = {}
    if _migrate_legacy_analysis_page_config(project, cfg):
        _write_config(app_settings, cfg)
    configured_views: list[str] = [
        str(v)
        for v in cfg.get("pages", {}).get("view_module", [])
        if isinstance(v, str)
    ]
    for config_value in configured_views:
        if config_value in resolved_pages:
            continue
        custom_entry = _find_view_entry(config_value, pages_root)
        if custom_entry is None:
            continue
        _, custom_path = custom_entry
        custom_view_lookup[str(custom_path)] = custom_path

    all_available_views = sorted(set(resolved_pages.keys()) | set(custom_view_lookup.keys()))
    if not all_available_views:
        st.info("No pages found under AGILAB_PAGES_ABS.")

    clone_source_paths = [""]
    clone_source_labels = {"": "Blank template"}
    for view_path in sorted(all_views, key=lambda p: p.as_posix()):
        path_str = str(view_path)
        label = _clone_source_label(view_path, pages_root)
        if path_str not in clone_source_labels:
            clone_source_paths.append(path_str)
            clone_source_labels[path_str] = label

    selection_key = f"view_selection__{project or 'default'}"
    pages_cfg = cfg.get("pages", {})
    pages_cfg = pages_cfg if isinstance(pages_cfg, dict) else {}
    has_view_session_selection = selection_key in st.session_state
    selection_state = build_analysis_view_selection_state(
        pages_cfg=pages_cfg,
        current_page=current_page,
        configured_views=configured_views,
        resolved_pages=resolved_pages,
        custom_view_lookup=custom_view_lookup,
        session_selection=st.session_state.get(selection_key),
        has_session_selection=has_view_session_selection,
    )
    view_names = list(selection_state.view_names)
    widget_selection = list(selection_state.widget_selection)
    if not has_view_session_selection:
        for default_view_name in reversed(tuple(getattr(selection_state, "default_view_names", ()) or ())):
            if default_view_name in view_names and default_view_name not in widget_selection:
                widget_selection.insert(0, default_view_name)
    if st.session_state.get(selection_key) != widget_selection:
        st.session_state[selection_key] = widget_selection

    active_app_path = _active_app_path_for_env(env)
    notebook_lookup = discover_project_notebooks(active_app_path)
    notebook_names = list(notebook_lookup.keys())
    notebook_selection_key = f"notebook_selection__{project or 'default'}"
    notebooks_cfg = cfg.get("notebooks", {})
    notebooks_cfg = notebooks_cfg if isinstance(notebooks_cfg, dict) else {}
    has_notebook_session_selection = notebook_selection_key in st.session_state
    if has_notebook_session_selection:
        notebook_widget_selection = _configured_notebook_options(
            st.session_state.get(notebook_selection_key, []),
            notebook_names,
        )
    else:
        notebook_widget_selection = _configured_notebook_options(
            notebooks_cfg.get("selected", []),
            notebook_names,
        )
    if st.session_state.get(notebook_selection_key) != notebook_widget_selection:
        st.session_state[notebook_selection_key] = notebook_widget_selection
    selected_notebooks = list(notebook_widget_selection)

    _render_analysis_workspace_overview(
        env,
        selection_state=selection_state,
        available_view_count=len(view_names),
    )

    with st.expander("Choose analysis views", expanded=False):
        st.caption("Select which views appear in the sidebar launcher for this project.")
        selected_views = st.multiselect(
            "Analysis views",
            view_names,
            key=selection_key,
            format_func=lambda option: _view_label(option, set(resolved_pages.keys())),
            help="Selected views are persisted in the active project's app settings.",
        )

    if notebook_names:
        with st.expander("Choose notebooks", expanded=False):
            selected_notebooks = st.multiselect(
                "Notebooks",
                notebook_names,
                key=notebook_selection_key,
                help="Selected notebooks are persisted in the active project's app settings.",
            )

    pages_cfg_for_selection = dict(pages_cfg)
    selected_view_set = set(selected_views)
    configured_default_views = [
        view_name
        for view_name in tuple(getattr(selection_state, "default_view_names", ()) or ())
        if view_name in selected_view_set
    ]
    if configured_default_views:
        pages_cfg_for_selection["default_views"] = configured_default_views
        pages_cfg_for_selection["default_view"] = configured_default_views[0]
    else:
        pages_cfg_for_selection.pop("default_views", None)
        pages_cfg_for_selection.pop("default_view", None)
    selection_for_state = list(selected_views)

    selection_state = build_analysis_view_selection_state(
        pages_cfg=pages_cfg_for_selection,
        current_page=current_page,
        configured_views=configured_views,
        resolved_pages=resolved_pages,
        custom_view_lookup=custom_view_lookup,
        session_selection=selection_for_state,
        has_session_selection=True,
    )
    selected_views = list(selection_state.selected_views)
    selected_notebooks = [name for name in selected_notebooks if name in notebook_lookup]
    _render_analysis_sidebar_view_launcher(
        project=project,
        selected_views=selected_views,
        view_names=view_names,
        resolved_pages=resolved_pages,
        custom_view_lookup=custom_view_lookup,
    )
    _render_analysis_sidebar_notebook_launcher(
        project=project,
        selected_notebooks=selected_notebooks,
        notebook_names=notebook_names,
        notebook_lookup=notebook_lookup,
    )

    persisted_pages = cfg.setdefault("pages", {})
    config_changed = False

    normalized_config = list(selection_state.config_view_module)
    if persisted_pages.get("view_module") != normalized_config:
        persisted_pages["view_module"] = normalized_config
        config_changed = True

    if "default_views" in persisted_pages:
        del persisted_pages["default_views"]
        config_changed = True
    if "default_view" in persisted_pages:
        del persisted_pages["default_view"]
        config_changed = True

    if notebook_names or isinstance(cfg.get("notebooks"), dict):
        persisted_notebooks = cfg.setdefault("notebooks", {})
        if not isinstance(persisted_notebooks, dict):
            persisted_notebooks = {}
            cfg["notebooks"] = persisted_notebooks
            config_changed = True
        if persisted_notebooks.get("selected") != selected_notebooks:
            persisted_notebooks["selected"] = selected_notebooks
            config_changed = True
    if config_changed:
        _write_config(app_settings, cfg)

    _render_custom_analysis_page_authoring(
        project=project,
        pages_root=pages_root,
        clone_source_paths=clone_source_paths,
        clone_source_labels=clone_source_labels,
        custom_view_lookup=custom_view_lookup,
        all_available_views=all_available_views,
    )


async def render_notebook_page(notebook_path: Path):
    """Render a project notebook by launching JupyterLab as a project-rooted sidecar."""
    env = st.session_state["env"]
    resolved_notebook = Path(notebook_path).expanduser().resolve()
    if resolved_notebook.suffix.lower() != ".ipynb":
        raise ValueError(f"Selected notebook is not an .ipynb file: {resolved_notebook}")
    if not resolved_notebook.exists():
        raise FileNotFoundError(f"Notebook does not exist: {resolved_notebook}")

    active_app_path = _active_app_path_for_env(env)
    project_root = _project_root_for_notebook(resolved_notebook, active_app_path)
    try:
        notebook_label = resolved_notebook.relative_to(project_root / "notebooks").as_posix()
    except ValueError:
        notebook_label = resolved_notebook.name

    _hide_parent_sidebar()

    back_col, title_col, _ = st.columns([1, 6, 1])
    with back_col:
        if st.button("← Back to Analysis", type="primary"):
            st.query_params["current_notebook"] = ""
            st.query_params["current_page"] = "main"
            st.rerun()
    with title_col:
        st.subheader(f"Notebook: `{notebook_label}`")

    if _is_hosted_analysis_runtime(env):
        st.warning("Notebook sidecars are available in local AGILAB runtimes only.")
        return

    notebook_key = f"{notebook_label}|{project_root.as_posix()}"
    port = _port_for(f"notebook|{notebook_key}")
    sidecar_ready = _ensure_notebook_sidecar(notebook_key, resolved_notebook, port, project_root)

    qp = st.query_params
    extras = {}
    for key, value in qp.items():
        if key in {"current_page", "current_notebook"}:
            continue
        extras[key] = value
    extras["embed"] = "true"
    query = urlencode(extras, doseq=True)
    notebook_url_path = _notebook_lab_tree_path(resolved_notebook, project_root)
    if not sidecar_ready:
        env.logger.error("Notebook sidecar failed to start for %s on port %s.", resolved_notebook, port)
        log_file, err_file = _notebook_log_paths(resolved_notebook, env.AGILAB_LOG_ABS)
        logs = Path(log_file)
        errors = Path(err_file)
        st.error("The notebook sidecar did not start correctly.", icon="⚠️")
        st.caption("If this persists, check logs and sidecar attempts below.")
        with st.expander("Notebook sidecar logs", expanded=True):
            if logs.exists():
                st.code(logs.read_text(encoding="utf-8", errors="ignore"), language="bash")
            else:
                st.write("No log file found.")
            if errors.exists():
                st.code(errors.read_text(encoding="utf-8", errors="ignore"), language="bash")
            else:
                st.write("No error log file found.")
            sidecar_attempts = st.session_state.get(f"notebook_sidecar_attempts__{notebook_key}", [])
            if sidecar_attempts:
                st.markdown("Attempt summary:")
                st.code("\n".join(sidecar_attempts), language="bash")
        return
    url = f"http://127.0.0.1:{port}/lab/tree/{notebook_url_path}?{query}"
    env.logger.info("notebook url: %s", url)
    st.iframe(url, height=900)


async def render_view_page(view_path: Path):
    """Render a specific view by launching it as a sidecar app in its own venv and iframing it."""
    env = st.session_state['env']
    # Hide THIS page's sidebar while a child view is displayed
    _hide_parent_sidebar()

    back_col, title_col, _ = st.columns([1, 6, 1])
    with back_col:
        if st.button("← Back to Analysis", type="primary"):
            st.session_state["current_page"] = "main"
            st.query_params["current_page"] = "main"
            st.rerun()
    with title_col:
        st.subheader(f"View: `{view_path.stem}`")

    # --- sidecar per-view run + iframe embed ---
    # Unique key for port hashing (works even if two Page share the same filename)
    view_key = f"{view_path.stem}|{view_path.parent.as_posix()}"
    active_app_arg = _active_app_arg_for_env(env)

    if _is_hosted_analysis_runtime(env):
        env.logger.info("Hosted runtime detected; rendering analysis view inline: %s", view_path)
        await _render_view_page_inline(view_path, active_app_arg)
        return

    port = _port_for(f"{view_key}|{active_app_arg}")
    sidecar_ready = _ensure_sidecar(view_key, view_path, port, active_app_arg)

    # Regular iframe (child keeps its own sidebar if it has one), preserve extra query params (e.g., datadir_rel)
    qp = st.query_params
    extras = {}
    for k, v in qp.items():
        if k in {"current_page", "current_notebook"}:
            continue
        extras[k] = v
    extras["embed"] = "true"
    query = urlencode(extras, doseq=True)
    if not sidecar_ready:
        env.logger.error("Sidecar failed to start for %s on port %s.", view_path, port)
        log_file, err_file = _page_log_paths(view_path, env.AGILAB_LOG_ABS)
        logs = Path(log_file)
        errors = Path(err_file)
        st.error("The analysis page sidecar did not start correctly.", icon="⚠️")
        st.caption("If this persists, check logs and sidecar attempts below.")
        with st.expander("Sidecar logs", expanded=True):
            if logs.exists():
                st.code(logs.read_text(encoding="utf-8", errors="ignore"), language="bash")
            else:
                st.write("No log file found.")
            if errors.exists():
                st.code(errors.read_text(encoding="utf-8", errors="ignore"), language="bash")
            else:
                st.write("No error log file found.")
            sidecar_attempts = st.session_state.get(f"sidecar_attempts__{view_key}", [])
            if sidecar_attempts:
                st.markdown("Attempt summary:")
                st.code("\n".join(sidecar_attempts), language="bash")
        return
    url = f"http://127.0.0.1:{port}/?{query}"
    env.logger.info("page url: %s", url)
    st.iframe(url, height=900)

    # --- end sidecar embed ---

if __name__ == "__main__":
    asyncio.run(main())
