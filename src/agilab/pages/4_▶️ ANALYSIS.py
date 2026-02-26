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
import re
from typing import Union
import asyncio
import shlex
from urllib.parse import urlencode
import shutil

from pathlib import Path

os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
import streamlit.components.v1 as components
from IPython.lib import backgroundjobs as bg
import logging
import subprocess

# Use modern TOML libraries
import tomllib       # For reading TOML files (read as binary)
import tomli_w       # For writing TOML files (write as binary)

# Project utilities (unchanged)
from agi_env.pagelib import (
    get_about_content,
    render_logo,
    select_project,
    inject_theme,
    load_last_active_app,
    store_last_active_app,
)
from agi_env import AgiEnv

logger = logging.getLogger(__name__)

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
except Exception as exc:  # pragma: no cover - dependency hint
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
        st.error(f"Provided active app path does not exist: {active_app_path}")
        st.stop()

    return AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
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

jobs = bg.BackgroundJobManager()


def _default_app_path(apps_path: Path | None) -> Path | None:
    """Return the first *_project directory found under apps_path."""
    if not apps_path or not apps_path.exists():
        return None
    for candidate in sorted(apps_path.iterdir()):
        if candidate.is_dir() and candidate.name.endswith("_project"):
            return candidate
    return None

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
            run_process.terminate()
            try:
                run_process.wait(timeout=1)
            except Exception:
                pass
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
                run_process.terminate()
                try:
                    run_process.wait(timeout=1)
                except Exception:
                    pass
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
        except Exception:
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
        except Exception:
            normalized = f"{normalized} ({option_path})"
    else:
        normalized = f"{normalized} ({option_path})"
    return normalized


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
    except Exception:
        return option_id
    return f"{path.name} (custom)"

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
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
    return {}


def _normalize_view_name(value: str) -> str:
    """Normalize page bundle labels by removing leading icon glyphs/decoration."""
    if not value:
        return ""
    normalized = re.sub(r"^\s*[^\w-]+", "", value).strip()
    return normalized or value.strip()

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
    requested_app = qp.get("active_app")

    if 'env' not in st.session_state:
        apps_path_value = st.session_state.get("apps_path")
        apps_path = Path(apps_path_value).expanduser() if apps_path_value else None
        if apps_path is None:
            repo_apps_path = Path(__file__).resolve().parents[2] / "apps"
            if repo_apps_path.exists():
                apps_path = repo_apps_path

        # Derive active app path
        active_app_path = None

        def _resolve_requested_app(value: str | None) -> Path | None:
            if not value:
                return None
            candidate = Path(value).expanduser()
            if candidate.is_absolute() and candidate.exists():
                return candidate
            if apps_path:
                candidate = Path(apps_path) / value
                if candidate.exists():
                    return candidate
            return None

        if requested_app:
            candidate = _resolve_requested_app(requested_app)
            if candidate is not None:
                active_app_path = candidate
                if apps_path is None:
                    apps_path = candidate.parent

        if active_app_path is None:
            stored_app = st.session_state.get("app")
            if stored_app and apps_path:
                candidate = apps_path / stored_app
                if candidate.exists():
                    active_app_path = candidate

        if active_app_path is None:
            env_app = os.environ.get("AGILAB_APP")
            if env_app:
                candidate = Path(env_app).expanduser()
                if candidate.exists():
                    active_app_path = candidate
                    if not apps_path:
                        apps_path = candidate.parent

        if active_app_path is None:
            last_app = load_last_active_app()
            if last_app is not None:
                active_app_path = last_app
                if not apps_path:
                    apps_path = last_app.parent

        if active_app_path is None:
            active_app_path = _default_app_path(apps_path)

        if active_app_path is None:
            st.error(
                "Could not determine the active app. Please select a project first or set AGILAB_APP."
            )
            st.stop()

        app_name = active_app_path.name
        if apps_path is None:
            apps_path = active_app_path.parent

        env = AgiEnv(
            apps_path=apps_path,
            app=app_name,
            verbose=0,
        )
        env.init_done = True
        st.session_state['env'] = env
        st.session_state['IS_SOURCE_ENV'] = env.is_source_env
        st.session_state['IS_WORKER_ENV'] = env.is_worker_env
        if apps_path:
            st.session_state['apps_path'] = str(apps_path)
        if app_name:
            st.session_state['app'] = app_name
        store_last_active_app(active_app_path)
    else:
        env = st.session_state['env']

    if env.app:
        st.query_params["active_app"] = env.app

    # Sidebar header/logo
    render_logo()

    # Sidebar: project selection
    projects = env.projects
    current_project = env.app if env.app in projects else (projects[0] if projects else None)
    select_project(projects, current_project)  # may be updated by select_project
    if env.app:
        st.query_params["active_app"] = env.app
    if env.app:
        store_last_active_app(Path(env.apps_path) / env.app)

    # Where to store selected pages per project
    project = env.app
    app_settings = Path(env.apps_path) / project / "src" / "app_settings.toml"

    # Discover pages dynamically under AGILAB_PAGES_ABS
    all_views = discover_views(Path(env.AGILAB_PAGES_ABS))
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
        except Exception:
            continue

    custom_view_lookup: dict[str, Path] = {}
    pages_root = Path(env.AGILAB_PAGES_ABS)

    # Route: only render a view when the param is a concrete path, not "main"/empty
    if current_page and current_page not in ("", "main"):
        try:
            await render_view_page(Path(current_page))
        except Exception as e:
            st.error(f"Failed to render view: {e}")
        return

    # ---------- Main analysis page ----------

    # Load config and ensure structure
    cfg = _read_config(app_settings)
    if "pages" not in cfg:
        cfg["pages"] = {}
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

    # Build preselection from stored config (legacy names + custom paths)
    preselect: list[str] = []
    for value in configured_views:
        if value in all_available_views:
            preselect.append(value)
            continue
        normalized = _normalize_view_name(value)
        if normalized in resolved_pages:
            preselect.append(normalized)

    clone_source_paths = [""]
    clone_source_labels = {"": "Blank template"}
    for view_path in sorted(all_views, key=lambda p: p.as_posix()):
        path_str = str(view_path)
        label = _clone_source_label(view_path, pages_root)
        if path_str not in clone_source_labels:
            clone_source_paths.append(path_str)
            clone_source_labels[path_str] = label

    with st.expander("Add custom analysis page", expanded=False):
        template_tab, add_tab = st.tabs(["Create from template", "Import Streamlit page"])

        with add_tab:
            st.caption("Import a Streamlit page from disk.")
            custom_view_input = st.text_input(
                "Streamlit page folder or Python file path",
                placeholder="/path/to/your_page or /path/to/page.py",
                key=f"analysis_custom_view_input__{project or 'default'}",
            )
            add_custom_view = st.button(
                "Import",
                type="secondary",
                key=f"analysis_add_custom_view__{project or 'default'}",
                use_container_width=True,
            )
            if add_custom_view:
                st.info("Import streamlit page is not implemented yet.")

        with template_tab:
            st.caption("Create a minimal analysis page and open it directly from this configuration.")
            template_name = st.text_input(
                "Page name",
                placeholder="my_analysis_view",
                key=f"analysis_template_view_name__{project or 'default'}",
            )
            clone_source = st.selectbox(
                "Clone from existing apps-page (optional)",
                options=clone_source_paths,
                format_func=lambda value: clone_source_labels.get(value, value),
                key=f"analysis_template_clone_source__{project or 'default'}",
            )
            create_template_view = st.button(
                "Create",
                type="primary",
                key=f"analysis_create_template_view__{project or 'default'}",
                use_container_width=True,
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
                        if clone_source:
                            source_entry = Path(clone_source)
                            source_root = _resolve_clone_source_root(source_entry)
                            target_root = pages_root / page_name
                            entrypoint_path = _clone_view_bundle(
                                source_entry, source_root, target_root
                            )
                        else:
                            _, entrypoint_path, _ = _write_minimal_view_template(
                                pages_root, page_name
                            )
                    except Exception as e:
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

    # Merge resolved pages and custom entries for display.
    view_names = sorted(set(resolved_pages.keys()) | set(custom_view_lookup.keys()))

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
        "Choose pages for analyzing the selected project",
        view_names,
        key=selection_key,
        format_func=lambda option: _view_label(option, set(resolved_pages.keys())),
        help="Selected pages are shown as quick-access shortcuts on the AGILAB start screen."
    )

    cleaned_selection = [v for v in selected_views if v in view_names]
    if cleaned_selection != selected_views:
        st.session_state[selection_key] = cleaned_selection
        selected_views = cleaned_selection

    if cfg.get("pages", {}).get("view_module") != selected_views:
        normalized_config = []
        for page_id in selected_views:
            if page_id in resolved_pages:
                normalized_config.append(page_id)
            else:
                normalized_config.append(str(Path(page_id).resolve()))
        cfg.setdefault("pages", {})["view_module"] = normalized_config
        _write_config(app_settings, cfg)

    # Show buttons for the selected pages
    st.divider()
    cols = st.columns(min(len(selected_views), 4) or 1)

    if selected_views:
        for i, view_name in enumerate(selected_views):
            view_path = resolved_pages.get(view_name)
            if not view_path:
                view_path = custom_view_lookup.get(view_name)
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
    active_app_path: Path | None = None
    if env.apps_path:
        for name in (env.target, env.app):
            if name:
                candidate = Path(env.apps_path) / name
                if candidate.exists():
                    active_app_path = candidate
                    break
    if active_app_path is None and env.active_app:
        candidate = Path(env.active_app)
        if candidate.exists():
            active_app_path = candidate

    if active_app_path is None and env.active_app:
        active_app_arg = str(env.active_app)
    else:
        active_app_arg = str(active_app_path) if active_app_path else ""
    port = _port_for(f"{view_key}|{active_app_arg}")
    sidecar_ready = _ensure_sidecar(view_key, view_path, port, active_app_arg)

    # Regular iframe (child keeps its own sidebar if it has one), preserve extra query params (e.g., datadir_rel)
    qp = st.query_params
    extras = {}
    for k, v in qp.items():
        if k == "current_page":
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
    components.iframe(url, height=900)

    # --- end sidecar embed ---

if __name__ == "__main__":
    asyncio.run(main())
