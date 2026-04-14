# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""Cluster workplan utilities for distributing AGILab workloads."""
import traceback
from typing import List, Optional, Tuple, Set  # Ajoute Tuple et Set
import asyncio
import inspect
import getpass
import io
import logging
import os
import pickle
import random
import re
import shutil
import socket
import sys
import time
import shlex
import warnings
import uuid
import posixpath
from copy import deepcopy
from datetime import timedelta
from ipaddress import ip_address as is_ip
from pathlib import Path, PurePosixPath
from tempfile import gettempdir, mkdtemp
from types import SimpleNamespace

from agi_cluster.agi_distributor import cli as distributor_cli
from agi_cluster.agi_distributor import (
    capacity_support,
    deployment_build_support,
    deployment_prepare_support,
    service_runtime_support,
    transport_support,
)

from agi_env import normalize_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# uv path-source rewriting helpers
# ---------------------------------------------------------------------------

def _envar_truthy(envars: dict, key: str) -> bool:
    """Return True when an env var value is truthy.

    Accepts common boolean-ish representations and defaults to False when unset
    or unparsable.
    """
    try:
        raw = envars.get(key)
    except Exception:
        return False
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        try:
            return int(raw) == 1
        except (TypeError, ValueError):
            return False
    value = str(raw).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _ensure_optional_extras(pyproject_file: Path, extras: Set[str]) -> None:
    """Ensure ``[project.optional-dependencies]`` contains the requested extras.

    Some worker environments are bootstrapped from a manager ``pyproject.toml`` that
    doesn't declare worker-only extras (e.g. ``polars-worker``). ``uv sync --extra``
    fails hard when the extra doesn't exist, even if it would be empty.
    """
    if not extras:
        return

    try:
        doc = tomlkit.parse(pyproject_file.read_text())
    except FileNotFoundError:
        doc = tomlkit.document()

    project_tbl = doc.get("project")
    if project_tbl is None:
        project_tbl = tomlkit.table()

    optional_tbl = project_tbl.get("optional-dependencies")
    if optional_tbl is None or not isinstance(optional_tbl, tomlkit.items.Table):
        optional_tbl = tomlkit.table()

    for extra in sorted({e for e in extras if isinstance(e, str) and e.strip()}):
        if extra not in optional_tbl:
            optional_tbl[extra] = tomlkit.array()

    project_tbl["optional-dependencies"] = optional_tbl
    doc["project"] = project_tbl
    pyproject_file.write_text(tomlkit.dumps(doc))


def _is_private_ssh_key_file(path: Path) -> bool:
    return transport_support.is_private_ssh_key_file(path)


def _discover_private_ssh_keys(ssh_dir: Path) -> List[str]:
    return transport_support.discover_private_ssh_keys(ssh_dir)


def _rewrite_uv_sources_paths_for_copied_pyproject(
    *,
    src_pyproject: Path,
    dest_pyproject: Path,
    log_rewrites: bool = False,
) -> None:
    """Rewrite ``[tool.uv.sources.*].path`` entries after copying a worker ``pyproject.toml``.

    Some worker projects use relative ``path = "../.."`` sources to depend on sibling
    worker packages (e.g. ``ilp_worker``). When the worker pyproject is copied into
    ``~/wenv/<app>_worker``, those relative paths no longer resolve, causing ``uv add``
    to fail with "Distribution not found at: file://...".

    This helper keeps the original source intent by resolving the path entries relative
    to the *source* pyproject location, then rewriting the copied pyproject to use
    paths relative to the destination directory.
    """

    try:
        src_data = tomlkit.parse(src_pyproject.read_text())
        dest_data = tomlkit.parse(dest_pyproject.read_text())
    except FileNotFoundError:
        return

    src_sources = (
        src_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(src_data, dict)
        else None
    )
    dest_sources = (
        dest_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(dest_data, dict)
        else None
    )
    if not isinstance(src_sources, dict) or not isinstance(dest_sources, dict):
        return

    dest_dir = dest_pyproject.parent
    rewrites: list[tuple[str, str, str]] = []

    for name, src_meta in src_sources.items():
        if not isinstance(src_meta, dict):
            continue
        src_path_value = src_meta.get("path")
        if not isinstance(src_path_value, str) or not src_path_value.strip():
            continue

        src_path = Path(src_path_value).expanduser()
        if not src_path.is_absolute():
            src_path = (src_pyproject.parent / src_path).resolve(strict=False)
        else:
            src_path = src_path.resolve(strict=False)
        if not src_path.exists():
            continue

        dest_meta = dest_sources.get(name)
        if not isinstance(dest_meta, dict):
            continue
        dest_path_value = dest_meta.get("path")

        dest_path = None
        if isinstance(dest_path_value, str) and dest_path_value.strip():
            dest_path = Path(dest_path_value).expanduser()
            if not dest_path.is_absolute():
                dest_path = (dest_dir / dest_path).resolve(strict=False)
            else:
                dest_path = dest_path.resolve(strict=False)

        # Keep valid existing paths (e.g. already rewritten by a previous run).
        if dest_path is not None and dest_path.exists():
            continue

        try:
            new_path_value = os.path.relpath(src_path, start=dest_dir)
        except Exception:
            new_path_value = str(src_path)

        if dest_path_value != new_path_value:
            dest_meta["path"] = new_path_value
            rewrites.append((name, str(dest_path_value or ""), new_path_value))

    if not rewrites:
        return

    dest_pyproject.write_text(tomlkit.dumps(dest_data))
    if log_rewrites:
        for name, old, new in rewrites:
            logger.info("Rewrote uv source '%s' path: %s -> %s", name, old or "<unset>", new)


def _copy_uv_source_tree(src_path: Path, dest_path: Path) -> None:
    """Copy a local uv source dependency into a self-contained staging area."""

    if dest_path.exists():
        if dest_path.is_dir():
            shutil.rmtree(dest_path, ignore_errors=True)
        else:
            try:
                dest_path.unlink()
            except FileNotFoundError:
                pass

    if src_path.is_dir():
        ignore = shutil.ignore_patterns(
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "build",
            "dist",
        )
        shutil.copytree(src_path, dest_path, ignore=ignore, dirs_exist_ok=True)
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)


def _stage_uv_sources_for_copied_pyproject(
    *,
    src_pyproject: Path,
    dest_pyproject: Path,
    stage_root: Path,
    log_rewrites: bool = False,
) -> list[Path]:
    """Stage local ``tool.uv.sources.*.path`` entries next to the copied pyproject.

    Rewriting a copied worker ``pyproject.toml`` to point back to the developer
    checkout works only when that checkout is available from the worker host.
    For local-source app dependencies such as ``ilp_worker``, we instead copy the
    referenced source trees into ``stage_root/_uv_sources`` and rewrite the copied
    pyproject to point at those staged copies. This makes the worker env payload
    self-contained for both local and remote installs.
    """

    try:
        src_data = tomlkit.parse(src_pyproject.read_text())
        dest_data = tomlkit.parse(dest_pyproject.read_text())
    except FileNotFoundError:
        return []

    src_sources = (
        src_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(src_data, dict)
        else None
    )
    dest_sources = (
        dest_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(dest_data, dict)
        else None
    )
    if not isinstance(src_sources, dict) or not isinstance(dest_sources, dict):
        return []

    dest_dir = dest_pyproject.parent
    staged_root = stage_root / "_uv_sources"
    rewrites: list[tuple[str, str, str]] = []
    staged_any = False

    for name, src_meta in src_sources.items():
        if not isinstance(src_meta, dict):
            continue
        src_path_value = src_meta.get("path")
        if not isinstance(src_path_value, str) or not src_path_value.strip():
            continue

        src_path = Path(src_path_value).expanduser()
        if not src_path.is_absolute():
            src_path = (src_pyproject.parent / src_path).resolve(strict=False)
        else:
            src_path = src_path.resolve(strict=False)
        if not src_path.exists():
            continue

        dest_meta = dest_sources.get(name)
        if not isinstance(dest_meta, dict):
            continue

        staged_target = staged_root / name
        _copy_uv_source_tree(src_path, staged_target)
        staged_any = True

        try:
            new_path_value = os.path.relpath(staged_target, start=dest_dir)
        except Exception:
            new_path_value = str(staged_target)

        old_path_value = dest_meta.get("path")
        if old_path_value != new_path_value:
            dest_meta["path"] = new_path_value
            rewrites.append((name, str(old_path_value or ""), new_path_value))

    if rewrites:
        dest_pyproject.write_text(tomlkit.dumps(dest_data))
        if log_rewrites:
            for name, old, new in rewrites:
                logger.info("Staged uv source '%s' path: %s -> %s", name, old or "<unset>", new)

    return [staged_root] if staged_any and staged_root.exists() else []


def _missing_uv_source_paths(pyproject_path: Path) -> list[tuple[str, str]]:
    """Return unresolved ``tool.uv.sources.*.path`` entries from a copied pyproject."""

    try:
        data = tomlkit.parse(pyproject_path.read_text())
    except FileNotFoundError:
        return []

    sources = (
        data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(data, dict)
        else None
    )
    if not isinstance(sources, dict):
        return []

    missing: list[tuple[str, str]] = []
    root = pyproject_path.parent
    for name, meta in sources.items():
        if not isinstance(meta, dict):
            continue
        path_value = meta.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        candidate = Path(path_value).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        if not candidate.exists():
            missing.append((str(name), path_value))

    return missing


def _validate_worker_uv_sources(pyproject_path: Path) -> None:
    """Fail fast when a copied worker pyproject still points at missing local sources."""

    missing = _missing_uv_source_paths(pyproject_path)
    if not missing:
        return

    details = ", ".join(f"{name} -> {path}" for name, path in missing[:4])
    if len(missing) > 4:
        details += f", +{len(missing) - 4} more"
    raise RuntimeError(
        "Worker environment is using unresolved local uv sources "
        f"from {pyproject_path}: {details}. "
        "This worker install is stale or incomplete. Rerun AGI.install for the app "
        "after updating AGILab so worker dependencies are staged into _uv_sources."
    )


def _worker_site_packages_dir(
    wenv_root: Path | PurePosixPath,
    pyvers: str,
    *,
    windows: bool = False,
) -> Path | PurePosixPath:
    """Return the worker venv site-packages path for the given Python version."""

    if windows:
        return wenv_root / ".venv" / "Lib" / "site-packages"

    parts = str(pyvers).split(".")
    major = parts[0] if parts else "3"
    minor_raw = parts[1] if len(parts) > 1 else "13"
    suffix = "t" if minor_raw.endswith("t") else ""
    minor = minor_raw[:-1] if suffix else minor_raw
    return wenv_root / ".venv" / "lib" / f"python{major}.{minor}{suffix}" / "site-packages"


def _staged_uv_sources_pth_content(
    site_packages_dir: Path | PurePosixPath,
    uv_sources_root: Path | PurePosixPath,
) -> str:
    """Return a relative `.pth` entry that exposes staged uv sources."""

    if isinstance(site_packages_dir, PurePosixPath) or isinstance(uv_sources_root, PurePosixPath):
        rel = posixpath.relpath(
            PurePosixPath(uv_sources_root).as_posix(),
            start=PurePosixPath(site_packages_dir).as_posix(),
        )
    else:
        rel = os.path.relpath(str(uv_sources_root), start=str(site_packages_dir))
    return f"{rel}\n"


def _write_staged_uv_sources_pth(
    site_packages_dir: Path,
    uv_sources_root: Path,
) -> Optional[Path]:
    """Write a `.pth` file so staged uv-source trees are importable at runtime."""

    pth_path = site_packages_dir / "agilab_uv_sources.pth"
    if not uv_sources_root.exists():
        try:
            pth_path.unlink()
        except FileNotFoundError:
            pass
        return None

    site_packages_dir.mkdir(parents=True, exist_ok=True)
    pth_path.write_text(
        _staged_uv_sources_pth_content(site_packages_dir, uv_sources_root),
        encoding="utf-8",
    )
    return pth_path

# ---------------------------------------------------------------------------
# Asyncio compatibility helpers (PyCharm debugger patches asyncio.run)
# ---------------------------------------------------------------------------
def _ensure_asyncio_run_signature() -> None:
    """Ensure ``asyncio.run`` accepts the ``loop_factory`` argument.

    PyCharm's debugger replaces ``asyncio.run`` with a shim that only accepts
    ``main`` and ``debug``.  Python 3.13 introduced a ``loop_factory`` keyword
    that ``distributed`` relies on; without it, AGI runs fail with
    ``TypeError``.  When we detect the truncated signature (and the replacement
    originates from ``pydevd``), we wrap it so ``loop_factory`` works again.
    """

    current = asyncio.run
    try:
        params = inspect.signature(current).parameters
    except (TypeError, ValueError):  # pragma: no cover - unable to introspect
        return
    if "loop_factory" in params:
        return

    if "pydevd" not in getattr(current, "__module__", ""):
        return

    original = current

    def _patched_run(main, *, debug=None, loop_factory=None):
        if loop_factory is None:
            return original(main, debug=debug)

        loop = loop_factory()
        try:
            try:
                asyncio.set_event_loop(loop)
            except RuntimeError:
                pass
            if debug is not None:
                loop.set_debug(debug)
            return loop.run_until_complete(main)
        finally:
            try:
                loop.close()
            finally:
                try:
                    asyncio.set_event_loop(None)
                except RuntimeError:
                    pass

    asyncio.run = _patched_run


_ensure_asyncio_run_signature()


# --- Added minimal TestPyPI fallback for uv sync ---
def _agi__version_missing_on_pypi(project_path):
    """Return True if any pinned 'agi*' or 'agilab' dependency version in pyproject.toml
    is not available on pypi.org (so we should use TestPyPI fallback)."""
    try:
        import json, urllib.request, re
        pyproj = (project_path / 'pyproject.toml')
        if not pyproj.exists():
            return False
        text = pyproj.read_text(encoding='utf-8', errors='ignore')
        # naive scan for lines like: agi-core = "==1.2.3" or "1.2.3"
        deps = re.findall(r'^(?:\s*)(ag(?:i[-_].+|ilab))\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
        if not deps:
            return False
        # extract exact pins
        pairs = []
        for name, spec in deps:
            m = re.match(r'^(?:==\s*)?(\d+(?:\.\d+){1,2})$', spec.strip())
            if m:
                version = m.group(1)
                pairs.append((name.replace('_', '-'), version))
        if not pairs:
            return False
        # check first pair only to keep it minimal/fast
        pkg, ver = pairs[0]
        try:
            with urllib.request.urlopen(f'https://pypi.org/pypi/{pkg}/json', timeout=5) as r:
                data = json.load(r)
            exists = ver in data.get('releases', {})
            return not exists
        except Exception:
            # If pypi query fails, don't force fallback.
            return False
    except Exception:
        return False


# --- end added helper ---
from typing import Any, Dict, List, Optional, Union
import sysconfig
from contextlib import redirect_stdout, redirect_stderr
import errno

# External Libraries
import asyncssh
from asyncssh.process import ProcessError
from contextlib import asynccontextmanager
import humanize
import numpy as np
import polars as pl
import psutil
from dask.distributed import Client, wait
import json
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
import subprocess
import runpy
import tomlkit
from packaging.requirements import Requirement
from importlib.metadata import PackageNotFoundError, version as pkg_version

# Project Libraries:
from agi_env import AgiEnv, normalize_path

_node_src = str(Path(sys.prefix).parents[1] / "agi-node/src")
if _node_src not in sys.path:
    sys.path.append(_node_src)
from agi_node.agi_dispatcher import WorkDispatcher, BaseWorker

# os.environ["DASK_DISTRIBUTED__LOGGING__DISTRIBUTED__LEVEL"] = "INFO"
warnings.filterwarnings("ignore")
_workers_default = {socket.gethostbyname("localhost"): 1}

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)


class _BackgroundProcessJob:
    """Minimal job record for detached subprocess launches."""

    def __init__(self, process: subprocess.Popen[str]):
        self.process = process
        self.result = process
        self.num: int | None = None


class _BackgroundProcessManager:
    """Host-neutral replacement for IPython BackgroundJobManager."""

    def __init__(self):
        self._current_job_id = 0
        self.all: dict[int, _BackgroundProcessJob] = {}
        self.running: list[_BackgroundProcessJob] = []
        self.completed: list[_BackgroundProcessJob] = []
        self.dead: list[_BackgroundProcessJob] = []

    @staticmethod
    def _normalize_cwd(cwd: str | Path | None) -> str | None:
        if cwd in (None, ""):
            return None
        try:
            candidate = Path(cwd).expanduser()
        except Exception:
            return None
        return str(candidate) if candidate.is_dir() else None

    def _refresh(self) -> None:
        active: list[_BackgroundProcessJob] = []
        for job in self.running:
            status = job.process.poll()
            if status is None:
                active.append(job)
            elif status == 0:
                self.completed.append(job)
            else:
                self.dead.append(job)
        self.running = active

    def new(self, cmd: str, cwd: str | Path | None = None) -> _BackgroundProcessJob:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=self._normalize_cwd(cwd),
            start_new_session=True,
        )
        job = _BackgroundProcessJob(proc)
        job.num = self._current_job_id
        self._current_job_id += 1
        self.running.append(job)
        self.all[job.num] = job
        return job

    def result(self, num: int):
        self._refresh()
        job = self.all.get(num)
        if job is None:
            return None
        if job in self.dead:
            return None
        return job.result

    def flush(self) -> None:
        self._refresh()
        for job in self.completed + self.dead:
            self.all.pop(job.num, None)
        self.completed.clear()
        self.dead.clear()


bg = SimpleNamespace(BackgroundJobManager=_BackgroundProcessManager)

class AGI:
    """Coordinate installation, scheduling, and execution of AGILab workloads."""

    # Constants as class attributes
    _TIMEOUT = 10
    PYTHON_MODE = 1
    CYTHON_MODE = 2
    DASK_MODE = 4
    RAPIDS_MODE = 16
    _INSTALL_MASK = 0b11 << DASK_MODE
    _INSTALL_MODE = 0b01 << DASK_MODE
    _UPDATE_MODE = 0b10 << DASK_MODE
    _SIMULATE_MODE = 0b11 << DASK_MODE
    _DEPLOYEMENT_MASK = 0b110000
    _RUN_MASK = 0b001111
    _RAPIDS_SET = 0b111111
    _RAPIDS_RESET = 0b110111
    _DASK_RESET = 0b111011
    _args: Optional[Dict[str, Any]] = None
    _dask_client: Optional[Client] = None
    _dask_scheduler: Optional[Any] = None
    _dask_workers: Optional[List[str]] = None
    _jobs: Optional[Any] = None
    _local_ip: List[str] = []
    _install_done_local: bool = False
    _mode: Optional[int] = None
    _mode_auto: bool = False
    _remote_ip: List[str] = []
    _install_done: bool = False
    _install_todo: Optional[int] = 0
    _scheduler: Optional[str] = None
    _scheduler_ip: Optional[str] = None
    _scheduler_port: Optional[int] = None
    _target: Optional[str] = None
    verbose: Optional[int] = None
    _worker_init_error: bool = False
    _workers: Optional[Dict[str, int]] = None
    _workers_data_path: Optional[str] = None
    _capacity: Optional[Dict[str, float]] = None
    _capacity_data_file: Optional[Path] = None
    _capacity_model_file: Optional[Path] = None
    _capacity_predictor: Optional[RandomForestRegressor] = None
    _worker_default: Dict[str, int] = _workers_default
    _run_time: Dict[str, Any] = {}
    _run_type: Optional[str] = None
    _run_types: List[str] = []
    _target_built: Optional[Any] = None
    _module_to_clean: List[str] = []
    _ssh_connections = {}
    _best_mode: Dict[str, Any] = {}
    _work_plan: Optional[Any] = None
    _work_plan_metadata: Optional[Any] = None
    debug: Optional[bool] = None  # Cache with default local IPs
    _dask_log_level: str = os.environ.get("AGI_DASK_LOG_LEVEL", "critical").strip()
    env: Optional[AgiEnv] = None
    _service_futures: Dict[str, Any] = {}
    _service_workers: List[str] = []
    _service_shutdown_on_stop: bool = True
    _service_stop_timeout: Optional[float] = 30.0
    _service_poll_interval: Optional[float] = None
    _service_queue_root: Optional[Path] = None
    _service_queue_pending: Optional[Path] = None
    _service_queue_running: Optional[Path] = None
    _service_queue_done: Optional[Path] = None
    _service_queue_failed: Optional[Path] = None
    _service_queue_heartbeats: Optional[Path] = None
    _service_heartbeat_timeout: Optional[float] = None
    _service_started_at: Optional[float] = None
    _service_cleanup_done_ttl_sec: float = 7 * 24 * 3600
    _service_cleanup_failed_ttl_sec: float = 14 * 24 * 3600
    _service_cleanup_heartbeat_ttl_sec: float = 24 * 3600
    _service_cleanup_done_max_files: int = 2000
    _service_cleanup_failed_max_files: int = 2000
    _service_cleanup_heartbeat_max_files: int = 1000
    _service_submit_counter: int = 0
    _service_worker_args: Dict[str, Any] = {}

    def __init__(self, target: str, verbose: int = 1):
        """
        Initialize a Agi object with a target and verbosity level.

        Args:
            target (str): The target for the env object.
            verbose (int): Verbosity level (0-3).

        Returns:
            None

        Raises:
            None
        """
        # At the top of __init__:
        if hasattr(AGI, "_instantiated") and AGI._instantiated:
            raise RuntimeError("AGI class is a singleton. Only one instance allowed per process.")
        AGI._instantiated = True

    @staticmethod
    async def run(
            env: AgiEnv,  # some_default_value must be defined
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            workers_data_path: Optional[str] = None,
            verbose: int = 0,
            mode: Optional[Union[int, List[int], str]] = None,
            rapids_enabled: bool = False,
            **args: Any,
    ) -> Any:
        """
        Compiles the target module in Cython and runs it on the cluster.

        Args:
            target (str): The target Python module to run.
            scheduler (str, optional): IP and port address of the Dask scheduler. Defaults to '127.0.0.1:8786'.
            workers (dict, optional): Dictionary of worker IPs and their counts. Defaults to `workers_default`.
            verbose (int, optional): Verbosity level. Defaults to 0.
            mode (int | list[int] | str | None, optional): Mode(s) for execution. Defaults to None.
                When an int is provided, it is treated as a 4-bit mask controlling RAPIDS/Dask/Cython/Pool features.
                When a string is provided, it must match r"^[dcrp]+$" (letters enable features).
                When a list is provided, the modes are benchmarked sequentially.
            rapids_enabled (bool, optional): Flag to enable RAPIDS. Defaults to False.
            **args (Any): Additional keyword arguments.

        Returns:
            Any: Result of the execution.

        Raises:
            ValueError: If `mode` is invalid.
            RuntimeError: If the target module fails to load.
        """
        AGI.env = env

        if not workers:
            workers = _workers_default
        elif not isinstance(workers, dict):
            raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

        AGI.target_path = env.manager_path
        AGI._target = env.target
        AGI._rapids_enabled = rapids_enabled
        if env.verbose > 0:
            logger.info(f"AGI instance created for target {env.target} with verbosity {env.verbose}")

        if mode is None or isinstance(mode, list):
            mode_range = range(8) if mode is None else sorted(mode)
            return await AGI._benchmark(
                env, scheduler, workers, verbose, mode_range, rapids_enabled, **args
            )
        else:
            if isinstance(mode, str):
                pattern = r"^[dcrp]+$"
                if not re.fullmatch(pattern, mode.lower()):
                    raise ValueError("parameter <mode> must only contain the letters 'd', 'c', 'r', 'p'")
                AGI._mode = env.mode2int(mode)
            elif isinstance(mode, int):
                AGI._mode = int(mode)
            else:
                raise ValueError("parameter <mode> must be an int, a list of int or a string")

            AGI._run_types = ["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"]
            if AGI._mode:
                if AGI._mode & AGI._RUN_MASK not in range(0, AGI.RAPIDS_MODE):
                    raise ValueError(f"mode {AGI._mode} not implemented")
            else:
                # 16 first modes are "run" type, then there 16, 17 and 18
                AGI._run_type = AGI._run_types[(AGI._mode & AGI._DEPLOYEMENT_MASK) >> AGI.DASK_MODE]
            AGI._args = args
            AGI.verbose = verbose
            AGI._workers = workers
            AGI._workers_data_path = workers_data_path
            AGI._run_time = {}

            AGI._capacity_data_file = env.resources_path / "balancer_df.csv"
            AGI._capacity_model_file = env.resources_path / "balancer_model.pkl"
            path = Path(AGI._capacity_model_file)

            if path.is_file():
                with open(path, "rb") as f:
                    AGI._capacity_predictor = pickle.load(f)
            else:
                AGI._train_capacity(Path(env.home_abs))

        # import of derived Class of WorkDispatcher, name target_inst which is typically instance of Flight or MyCode
        AGI.agi_workers = {
            "AgiDataWorker": "pandas-worker",
            "PolarsWorker": "polars-worker",
            "PandasWorker": "pandas-worker",
            "FireducksWorker": "fireducks-worker",
            "DagWorker": "dag-worker",
        }
        base_worker_cls = getattr(env, "base_worker_cls", None)
        if not base_worker_cls:
            target_worker_class = getattr(env, "target_worker_class", None) or "<worker class>"
            worker_path = getattr(env, "worker_path", None) or "<worker path>"
            supported = ", ".join(sorted(AGI.agi_workers.keys()))
            raise ValueError(
                f"Missing {target_worker_class} definition; expected {worker_path}. "
                f"Ensure the app worker exists and inherits from a supported base worker ({supported})."
            )
        try:
            AGI.install_worker_group = [AGI.agi_workers[base_worker_cls]]
        except KeyError as exc:
            supported = ", ".join(sorted(AGI.agi_workers.keys()))
            raise ValueError(
                f"Unsupported base worker class '{base_worker_cls}'. Supported values: {supported}."
            ) from exc

        try:
            return await AGI._main(scheduler)

        except ProcessError as e:
            logger.error(f"failed to run \n{e}")
            return

        except ConnectionError as e:
            message = str(e).strip() or "Failed to connect to remote host."
            logger.info(message)
            print(message, file=sys.stderr, flush=True)
            return {"status": "error", "message": message, "kind": "connection"}

        except ModuleNotFoundError as e:
            logger.error(f"failed to load module \n{e}")
            return

        except Exception as err:
            message = _format_exception_chain(err)
            logger.error(f"Unhandled exception in AGI.run: {message}")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Traceback:\n%s", traceback.format_exc())
            raise

    @staticmethod
    def _wrap_worker_chunk(payload: Any, worker_index: int) -> Any:
        return service_runtime_support.wrap_worker_chunk(payload, worker_index)

    @staticmethod
    def _service_queue_paths(queue_root: Path) -> Dict[str, Path]:
        return service_runtime_support.service_queue_paths(queue_root)

    @staticmethod
    def _service_apply_queue_root(
            queue_root: Union[str, Path],
            *,
            create: bool = False,
    ) -> Dict[str, Path]:
        return service_runtime_support.service_apply_queue_root(AGI, queue_root, create=create)

    @staticmethod
    def _service_state_path(env: AgiEnv) -> Path:
        return service_runtime_support.service_state_path(env)

    @staticmethod
    def _service_read_state(env: AgiEnv) -> Optional[Dict[str, Any]]:
        return service_runtime_support.service_read_state(AGI, env, log=logger)

    @staticmethod
    def _service_write_state(env: AgiEnv, payload: Dict[str, Any]) -> None:
        service_runtime_support.service_write_state(AGI, env, payload)

    @staticmethod
    def _service_clear_state(env: AgiEnv) -> None:
        service_runtime_support.service_clear_state(AGI, env, log=logger)

    @staticmethod
    def _service_health_path(
            env: AgiEnv,
            health_output_path: Optional[Union[str, Path]] = None,
    ) -> Path:
        return service_runtime_support.service_health_path(
            env,
            health_output_path=health_output_path,
        )

    @staticmethod
    def _service_health_payload(env: AgiEnv, result_payload: Dict[str, Any]) -> Dict[str, Any]:
        return service_runtime_support.service_health_payload(env, result_payload)

    @staticmethod
    def _service_write_health_payload(
            env: AgiEnv,
            health_payload: Dict[str, Any],
            *,
            health_output_path: Optional[Union[str, Path]] = None,
    ) -> Optional[str]:
        return service_runtime_support.service_write_health_payload(
            AGI,
            env,
            health_payload,
            health_output_path=health_output_path,
            log=logger,
        )

    @staticmethod
    def _service_finalize_response(
            env: AgiEnv,
            result_payload: Dict[str, Any],
            *,
            health_output_path: Optional[Union[str, Path]] = None,
            health_only: bool = False,
    ) -> Dict[str, Any]:
        return service_runtime_support.service_finalize_response(
            AGI,
            env,
            result_payload,
            health_output_path=health_output_path,
            health_only=health_only,
        )

    @staticmethod
    async def _service_connected_workers(client: Client) -> List[str]:
        return await service_runtime_support.service_connected_workers(client)

    @staticmethod
    async def _service_recover(
            env: AgiEnv,
            *,
            allow_stale_cleanup: bool = False,
    ) -> bool:
        return await service_runtime_support.service_recover(
            AGI,
            env,
            allow_stale_cleanup=allow_stale_cleanup,
            log=logger,
        )

    @staticmethod
    def _reset_service_queue_state() -> None:
        service_runtime_support.reset_service_queue_state(AGI)

    @staticmethod
    def _init_service_queue(
            env: AgiEnv,
            service_queue_dir: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Path]:
        return service_runtime_support.init_service_queue(
            AGI,
            env,
            service_queue_dir=service_queue_dir,
        )

    @staticmethod
    def _service_queue_counts() -> Dict[str, int]:
        return service_runtime_support.service_queue_counts(AGI)

    @staticmethod
    def _service_cleanup_artifacts() -> Dict[str, int]:
        return service_runtime_support.service_cleanup_artifacts(AGI)

    @staticmethod
    def _service_public_args(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return service_runtime_support.service_public_args(args)

    @staticmethod
    def _service_safe_worker_name(worker: str) -> str:
        return service_runtime_support.service_safe_worker_name(worker)

    @staticmethod
    def _service_heartbeat_timeout_value() -> float:
        return service_runtime_support.service_heartbeat_timeout_value(AGI)

    @staticmethod
    def _service_apply_runtime_config(
            *,
            heartbeat_timeout: Optional[float] = None,
            cleanup_done_ttl_sec: Optional[float] = None,
            cleanup_failed_ttl_sec: Optional[float] = None,
            cleanup_heartbeat_ttl_sec: Optional[float] = None,
            cleanup_done_max_files: Optional[int] = None,
            cleanup_failed_max_files: Optional[int] = None,
            cleanup_heartbeat_max_files: Optional[int] = None,
    ) -> None:
        service_runtime_support.service_apply_runtime_config(
            AGI,
            heartbeat_timeout=heartbeat_timeout,
            cleanup_done_ttl_sec=cleanup_done_ttl_sec,
            cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
            cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
            cleanup_done_max_files=cleanup_done_max_files,
            cleanup_failed_max_files=cleanup_failed_max_files,
            cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
        )

    @staticmethod
    def _service_state_payload(env: AgiEnv) -> Dict[str, Any]:
        return service_runtime_support.service_state_payload(AGI, env)

    @staticmethod
    def _service_read_heartbeats() -> Dict[str, float]:
        return service_runtime_support.service_read_heartbeats(AGI)

    @staticmethod
    def _service_read_heartbeat_payloads() -> Dict[str, Dict[str, Any]]:
        return service_runtime_support.service_read_heartbeat_payloads(AGI)

    @staticmethod
    def _service_worker_health(workers: List[str]) -> List[Dict[str, Any]]:
        return service_runtime_support.service_worker_health(AGI, workers)

    @staticmethod
    def _service_unhealthy_workers(workers: List[str]) -> Dict[str, str]:
        return service_runtime_support.service_unhealthy_workers(AGI, workers)

    @staticmethod
    async def _service_restart_workers(
            env: AgiEnv,
            client: Client,
            workers_to_restart: List[str],
    ) -> List[str]:
        return await service_runtime_support.service_restart_workers(
            AGI,
            env,
            client,
            workers_to_restart,
            log=logger,
        )

    @staticmethod
    async def _service_auto_restart_unhealthy(
            env: AgiEnv,
            client: Client,
    ) -> Dict[str, Any]:
        return await service_runtime_support.service_auto_restart_unhealthy(
            AGI,
            env,
            client,
        )

    @staticmethod
    async def serve(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            mode: Optional[Union[int, str]] = None,
            rapids_enabled: bool = False,
            action: str = "start",
            poll_interval: Optional[float] = None,
            shutdown_on_stop: bool = True,
            stop_timeout: Optional[float] = 30.0,
            service_queue_dir: Optional[Union[str, Path]] = None,
            heartbeat_timeout: Optional[float] = None,
            cleanup_done_ttl_sec: Optional[float] = None,
            cleanup_failed_ttl_sec: Optional[float] = None,
            cleanup_heartbeat_ttl_sec: Optional[float] = None,
            cleanup_done_max_files: Optional[int] = None,
            cleanup_failed_max_files: Optional[int] = None,
            cleanup_heartbeat_max_files: Optional[int] = None,
            health_output_path: Optional[Union[str, Path]] = None,
            **args: Any,
    ) -> Dict[str, Any]:
        return await service_runtime_support.serve(
            AGI,
            env,
            scheduler=scheduler,
            workers=workers,
            verbose=verbose,
            mode=mode,
            rapids_enabled=rapids_enabled,
            action=action,
            poll_interval=poll_interval,
            shutdown_on_stop=shutdown_on_stop,
            stop_timeout=stop_timeout,
            service_queue_dir=service_queue_dir,
            heartbeat_timeout=heartbeat_timeout,
            cleanup_done_ttl_sec=cleanup_done_ttl_sec,
            cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
            cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
            cleanup_done_max_files=cleanup_done_max_files,
            cleanup_failed_max_files=cleanup_failed_max_files,
            cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
            health_output_path=health_output_path,
            background_job_manager_factory=bg.BackgroundJobManager,
            wait_fn=wait,
            log=logger,
            **args,
        )

    @staticmethod
    async def submit(
            env: Optional[AgiEnv] = None,
            workers: Optional[Dict[str, int]] = None,
            work_plan: Optional[Any] = None,
            work_plan_metadata: Optional[Any] = None,
            task_id: Optional[str] = None,
            task_name: Optional[str] = None,
            **args: Any,
    ) -> Dict[str, Any]:
        return await service_runtime_support.submit(
            AGI,
            env=env,
            workers=workers,
            work_plan=work_plan,
            work_plan_metadata=work_plan_metadata,
            task_id=task_id,
            task_name=task_name,
            **args,
        )

    @staticmethod
    async def _benchmark(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            mode_range: Optional[Union[List[int], range]] = None,
            rapids_enabled: Optional[bool] = None,
            **args: Any,
    ) -> str:
        return await capacity_support.benchmark(
            AGI,
            env,
            scheduler=scheduler,
            workers=workers,
            verbose=verbose,
            mode_range=list(mode_range) if mode_range is not None else None,
            rapids_enabled=bool(rapids_enabled),
            **args,
        )

    @staticmethod
    async def _benchmark_dask_modes(
        env: AgiEnv,
        scheduler: Optional[str],
        workers: Optional[Dict[str, int]],
        mode_range: List[int],
        rapids_mode_mask: int,
        runs: Dict[int, Dict[str, Any]],
        **args: Any,
    ) -> None:
        await capacity_support.benchmark_dask_modes(
            AGI,
            env,
            scheduler,
            workers,
            mode_range,
            rapids_mode_mask,
            runs,
            **args,
        )

    @staticmethod
    def get_default_local_ip() -> str:
        """
        Get the default local IP address of the machine.

        Returns:
            str: The default local IP address.

        Raises:
            Exception: If unable to determine the local IP address.
        """
        """ """
        try:
            # Attempt to connect to a non-local address and capture the local endpoint's IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "Unable to determine local IP"

    @staticmethod
    def find_free_port(start: int = 5000, end: int = 10000, attempts: int = 100) -> int:
        for _ in range(attempts):
            port = random.randint(start, end)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                # set SO_REUSEADDR to avoid 'address already in use' issues during testing
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("localhost", port))
                    # if binding succeeds, the port is free; close socket and return port
                    return port
                except OSError:
                    # port is already in use, try another
                    continue
        raise RuntimeError("No free port found in the specified range.")

    @staticmethod
    def _get_scheduler(ip_sched: Optional[Union[str, Dict[str, int]]] = None) -> Tuple[str, int]:
        """get scheduler ip V4 address
        when no scheduler provided, scheduler address is localhost or the first address if workers are not local.
        port is random

        Args:
          ip_sched:

        Returns:

        """
        port = AGI.find_free_port()
        if not ip_sched:
            if AGI._workers:
                ip = list(AGI._workers)[0]
            else:
                ip = socket.gethostbyname("localhost")
        elif isinstance(ip_sched, dict):
            # end-user already has provided a port
            ip, port = list(ip_sched.items())[0]
        elif not isinstance(ip_sched, str):
            raise ValueError("Scheduler ip address is not valid")
        else:
            ip = ip_sched
        AGI._scheduler = f"{ip}:{port}"
        return ip, port

    @staticmethod
    def _get_stdout(func: Any, *args: Any, **kwargs: Any) -> Tuple[str, Any]:
        """to get the stdout stream

        Args:
          func: param args:
          kwargs: return: the return of the func
          *args:
          **kwargs:

        Returns:
          : the return of the func

        """
        f = io.StringIO()
        with redirect_stdout(f):
            result = func(*args, **kwargs)
        return f.getvalue(), result

    @staticmethod
    def _read_stderr(output_stream: Any) -> None:
        """Read remote stderr robustly on Linux (UTF-8), Windows OEM (CP850), then ANSI (CP1252)."""

        def decode_bytes(bs: bytes) -> str:
            # try UTF-8, then OEM (CP850) for console accents, then ANSI (CP1252)
            for enc in ('utf-8', 'cp850', 'cp1252'):
                try:
                    return bs.decode(enc)
                except Exception:
                    continue
            # final fallback
            return bs.decode('cp850', errors='replace')

        chan = getattr(output_stream, 'channel', None)
        if chan is None:
            # simple iteration fallback
            for raw in output_stream:
                if isinstance(raw, bytes):
                    decoded = decode_bytes(raw)
                else:
                    decoded = decode_bytes(raw.encode('latin-1', errors='replace'))
                line = decoded.strip()
                logger.info(line)
                AGI._worker_init_error = line.endswith('[ProjectError]')
            return

        # non-blocking channel read
        while True:
            if chan.recv_stderr_ready():
                try:
                    raw = chan.recv_stderr(1024)
                except Exception:
                    continue
                if not raw:
                    break
                decoded = decode_bytes(raw)
                for part in decoded.splitlines():
                    line = part.strip()
                    logger.info(line)
                    AGI._worker_init_error = line.endswith('[ProjectError]')
            elif chan.exit_status_ready():
                break
            else:
                time.sleep(0.1)

    @staticmethod
    async def send_file(
            env: AgiEnv,
            ip: str,
            local_path: Path,
            remote_path: Path,
            user: str = None,
            password: str = None
    ):
        await transport_support.send_file(
            env,
            ip,
            local_path,
            remote_path,
            user=user,
            password=password,
            log=logger,
        )

    @staticmethod
    async def send_files(env: AgiEnv, ip: str, files: list[Path], remote_dir: Path, user: str = None):
        await transport_support.send_files(
            AGI,
            env,
            ip,
            files,
            remote_dir,
            user=user,
        )

    @staticmethod
    def _remove_dir_forcefully(path):
        import shutil
        import os
        import time

        def onerror(func, path, exc_info):
            import stat
            if not os.access(path, os.W_OK):
                os.chmod(path, stat.S_IWUSR)
                func(path)
            else:
                logger.info(f"{path} not removed due to {exc_info[1]}")

        try:
            shutil.rmtree(path, onerror=onerror)
        except Exception as e:
            logger.error(f"Exception while deleting {path}: {e}")
            time.sleep(1)
            try:
                shutil.rmtree(path, onerror=onerror)
            except Exception as e2:
                logger.error(f"Second failure deleting {path}: {e2}")
                raise

    @staticmethod
    async def _kill(ip: Optional[str] = None, current_pid: Optional[int] = None, force: bool = True) -> Optional[Any]:
        """
        Terminate 'uv' and Dask processes on the given host and clean up pid files.

        Args:
            ip (str, optional): IP address of the host to kill processes on. Defaults to local host.
            current_pid (int, optional): PID of this process to exclude. Defaults to this process.
            force (bool, optional): Whether to kill all 'dask' processes by name. Defaults to True.
        Returns:
            The result of the last kill command (dict or None).
        """
        env = AGI.env
        uv = env.uv
        localhost = socket.gethostbyname("localhost")
        ip = ip or localhost
        current_pid = current_pid or os.getpid()

        # 1) Collect PIDs from any pid files and remove those files
        pids_to_kill: list[int] = []
        for pid_file in Path(env.wenv_abs.parent).glob("*.pid"):
            try:
                text = pid_file.read_text().strip()
                pid = int(text)
                if pid != current_pid:
                    pids_to_kill.append(pid)
            except Exception:
                logger.warning(f"Could not read PID from {pid_file}, skipping")
            try:
                pid_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove pid file {pid_file}: {e}")

        cmds: list[str] = []
        cli_rel = env.wenv_rel.parent / "cli.py"
        cli_abs = env.wenv_abs.parent / cli_rel.name
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        kill_prefix = f'{cmd_prefix}{uv} run --no-sync python'
        if env.is_local(ip):
            if not (cli_abs).exists():
                shutil.copy(env.cluster_pck / "agi_distributor/cli.py", cli_abs)
            if force:
                exclude_arg = f" {current_pid}" if current_pid else ""
                cmd = f"{kill_prefix} '{cli_abs}' kill{exclude_arg}"
                cmds.append(cmd)
        else:
            if force:
                cmd = f"{kill_prefix} '{cli_rel.as_posix()}' kill"
                cmds.append(cmd)

        last_res = None
        for cmd in cmds:
            # choose working directory based on local vs remote
            cwd = env.agi_cluster if ip == localhost else str(env.wenv_abs)
            if env.is_local(ip):
                if env.debug:
                    sys.argv = cmd.split('python ')[1].split(" ")
                    runpy.run_path(sys.argv[0], run_name="__main__")
                else:
                    await AgiEnv.run(cmd, cwd)
            else:
                last_res = await AGI.exec_ssh(ip, cmd)

            # handle tuple or dict result
            if isinstance(last_res, dict):
                out = last_res.get("stdout", "")
                err = last_res.get("stderr", "")
                logger.info(out)
                if err:
                    logger.error(err)

        return last_res

    @staticmethod
    async def _wait_for_port_release(ip: str, port: int, timeout: float = 5.0, interval: float = 0.2) -> bool:
        """Poll until no process is listening on (ip, port)."""
        ip = ip or socket.gethostbyname("localhost")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind((ip, port))
            except OSError:
                await asyncio.sleep(interval)
            else:
                sock.close()
                return True
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
        return False

    @staticmethod
    def _clean_dirs_local() -> None:
        """Clean up local worker env directory

        Args:
          wenv: worker environment dictionary

        Returns:

        """
        me = getpass.getuser()
        self_pid = os.getpid()
        for p in psutil.process_iter(['pid', 'username', 'cmdline']):
            try:
                if (
                        p.info['username'] and p.info['username'].endswith(me)
                        and p.info['pid'] and p.info['pid'] != self_pid
                        and p.info['cmdline']
                        and any('dask' in s.lower() for s in p.info['cmdline'])
                ):
                    p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        for d in [
            f"{gettempdir()}/dask-scratch-space",
            f"{AGI.env.wenv_abs}",
        ]:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except (OSError, TypeError):
                pass

    @staticmethod
    async def _clean_dirs(ip: str) -> None:
        """Clean up remote worker

        Args:
          ip: address of remote worker

        Returns:

        """
        env = AGI.env
        uv = env.uv
        wenv_abs = env.wenv_abs
        if wenv_abs.exists():
            AGI._remove_dir_forcefully(str(wenv_abs))
        os.makedirs(wenv_abs / "src", exist_ok=True)
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        wenv = env.wenv_rel
        cli = wenv.parent / 'cli.py'
        cmd = (f"{cmd_prefix}{uv} run --no-sync -p {env.python_version} python {cli.as_posix()} clean {wenv}")
        await AGI.exec_ssh(ip, cmd)

    @staticmethod
    async def _clean_nodes(scheduler_addr: Optional[str], force: bool = True) -> Set[str]:
        # Compose list of IPs: workers plus scheduler's IP
        list_ip = set(list(AGI._workers) + [AGI._get_scheduler(scheduler_addr)[0]])
        localhost_ip = socket.gethostbyname("localhost")
        if not list_ip:
            list_ip.add(localhost_ip)

        for ip in list_ip:
            if AgiEnv.is_local(ip):
                # Assuming this cleans local dirs once per IP (or should be once per call)
                AGI._clean_dirs_local()

        await AGI._clean_remote_procs(list_ip=list_ip, force=force)
        await AGI._clean_remote_dirs(list_ip=list_ip)

        return list_ip

    @staticmethod
    async def _clean_remote_procs(list_ip: Set[str], force: bool = True) -> None:
        tasks = []
        for ip in list_ip:
            if not AgiEnv.is_local(ip):
                tasks.append(asyncio.create_task(AGI._kill(ip, os.getpid(), force=force)))

        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    async def _clean_remote_dirs(list_ip: Set[str]) -> None:
        tasks = []
        for ip in list_ip:
            tasks.append(asyncio.create_task(AGI._clean_dirs(ip)))
        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    async def _prepare_local_env() -> None:
        await deployment_prepare_support.prepare_local_env(
            AGI,
            envar_truthy_fn=_envar_truthy,
            detect_export_cmd_fn=AGI._detect_export_cmd,
            set_env_var_fn=AgiEnv.set_env_var,
            run_fn=AgiEnv.run,
            python_version_fn=distributor_cli.python_version,
            log=logger,
        )

    @staticmethod
    async def _prepare_cluster_env(scheduler_addr: Optional[str]) -> None:
        await deployment_prepare_support.prepare_cluster_env(
            AGI,
            scheduler_addr,
            envar_truthy_fn=_envar_truthy,
            detect_export_cmd_fn=AGI._detect_export_cmd,
            ensure_optional_extras_fn=_ensure_optional_extras,
            stage_uv_sources_fn=_stage_uv_sources_for_copied_pyproject,
            run_exec_ssh_fn=AGI.exec_ssh,
            send_files_fn=AGI.send_files,
            kill_fn=AGI._kill,
            clean_dirs_fn=AGI._clean_dirs,
            mkdtemp_fn=mkdtemp,
            process_error_type=ProcessError,
            set_env_var_fn=AgiEnv.set_env_var,
            log=logger,
        )

    @staticmethod
    async def _deploy_application(scheduler_addr: Optional[str]) -> None:
        AGI._reset_deploy_state()
        env = AGI.env
        app_path = env.active_app
        wenv_rel = env.wenv_rel
        if isinstance(env.base_worker_cls, str):
            options_worker = " --extra " + " --extra ".join(AGI.install_worker_group)

        # node_ips = await AGI._clean_nodes(scheduler)
        node_ips = set(list(AGI._workers) + [AGI._get_scheduler(scheduler_addr)[0]])
        AGI._venv_todo(node_ips)
        start_time = time.time()
        if env.verbose > 0:
            logger.info(f"Installing {app_path} on 127.0.0.1")

        await AGI._deploy_local_worker(app_path, Path(wenv_rel), options_worker)
        # logger.info(AGI.run(cmd, wenv_abs))
        if AGI._mode & 4:
            tasks = []
            for ip in node_ips:
                if env.verbose > 0:
                    logger.info(f"Installing worker on {ip}")
                if not env.is_local(ip):
                    tasks.append(asyncio.create_task(
                        AGI._deploy_remote_worker(ip, env, wenv_rel, options_worker)
                    ))
            await asyncio.gather(*tasks)

        if AGI.verbose:
            duration = AGI._format_elapsed(time.time() - start_time)
            if env.verbose > 0:
                logger.info(f"uv {AGI._run_type} completed in {duration}")

    @staticmethod
    def _reset_deploy_state() -> None:
        """Initialize installation flags and run type."""
        AGI._run_type = AGI._run_types[(AGI._mode & AGI._DEPLOYEMENT_MASK) >> 4]
        AGI._install_done_local = False
        AGI._install_done = False
        AGI._worker_init_error = False

    @staticmethod
    def _hardware_supports_rapids() -> bool:
        try:
            subprocess.run(
                ["nvidia-smi"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @staticmethod
    async def _deploy_local_worker(src: Path, wenv_rel: Path, options_worker: str) -> None:
        """
        Installe l’environnement localement.

        Args:
            src: chemin vers la racine du projet local
            wenv_rel: chemin relatif vers l’environnement virtuel local
            options_worker: le setup
        """
        env = AGI.env
        run_type = AGI._run_type
        if (not env.is_source_env) and (not env.is_worker_env) and isinstance(run_type, str) and "--dev" in run_type:
            run_type = " ".join(part for part in run_type.split() if part != "--dev")
        ip = "127.0.0.1"
        hw_rapids_capable = AGI._hardware_supports_rapids() and AGI._rapids_enabled
        env.hw_rapids_capable = hw_rapids_capable
        repo_root: Path | None = None
        repo_env_project: Path | None = None
        repo_node_project: Path | None = None
        repo_core_project: Path | None = None
        repo_cluster_project: Path | None = None
        repo_agilab_root: Path | None = None
        dependency_info: dict[str, dict[str, Any]] = {}
        dep_versions: dict[str, str] = {}
        worker_pyprojects: set[str] = set()

        def _force_remove(path: Path) -> None:
            """Suppression robuste : tente shutil, puis bascule sur rmdir /s /q en cas d'échec."""
            if not path.exists():
                return

            def _on_err(func, p, exc):
                os.chmod(p, stat.S_IWRITE)
                try:
                    func(p)
                except Exception:
                    pass

            try:
                shutil.rmtree(path, onerror=_on_err)
            except Exception:
                pass

            if path.exists():
                AGI.env.logger.warn("Path {} still exists, using subprocess cmd to delete it.".format(path))
                subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)], shell=True, check=False)

        def _cleanup_editable(site_packages: Path) -> None:
            patterns = (
                '__editable__.agi_env*.pth',
                '__editable__.agi_node*.pth',
                '__editable__.agi_core*.pth',
                '__editable__.agi_cluster*.pth',
                '__editable__.agilab*.pth',
            )
            for pattern in patterns:
                for editable in site_packages.glob(pattern):
                    try:
                        editable.unlink()
                    except FileNotFoundError:
                        pass

        async def _ensure_pip(uv_cmd: str, project: Path) -> None:
            cmd = f"{uv_cmd} run --project '{project}' python -m ensurepip --upgrade"
            await AgiEnv.run(cmd, project)

        def _format_dependency_spec(name: str, extras: set[str], specifiers: list[str]) -> str:
            extras_part = ''
            if extras:
                extras_part = '[' + ','.join(sorted(extras)) + ']'
            spec_part = ''
            if specifiers:
                spec_part = ','.join(specifiers)
            return f"{name}{extras_part}{spec_part}"

        def _is_within_repo(path: Path, root: Path | None) -> bool:
            if root is None:
                return False
            try:
                return path.resolve().is_relative_to(root.resolve())
            except Exception:
                return False

        def _infer_repo_root_from_runtime() -> Path | None:
            try:
                inferred = Path(__file__).resolve().parents[5]
            except IndexError:
                return None
            if (inferred / "core" / "agi-env").exists() and (inferred / "apps").exists():
                return inferred
            return None

        def _update_pyproject_dependencies(
            pyproject_file: Path,
            pinned_versions: dict[str, str] | None,
            *,
            filter_to_worker: bool = False,
        ) -> None:
            try:
                data = tomlkit.parse(pyproject_file.read_text())
            except FileNotFoundError:
                data = tomlkit.document()

            project_tbl = data.get("project")
            if project_tbl is None:
                project_tbl = tomlkit.table()

            deps = project_tbl.get("dependencies")
            if deps is None:
                deps = tomlkit.array()
            else:
                if not isinstance(deps, tomlkit.items.Array):
                    arr = tomlkit.array()
                    for item in deps:
                        arr.append(item)
                    deps = arr

            existing = {str(item) for item in deps}
            existing_keys: set[tuple[str, tuple[str, ...]]] = set()
            for item in deps:
                try:
                    req = Requirement(str(item))
                except Exception:
                    continue
                existing_keys.add((req.name.lower(), tuple(sorted(req.extras))))
            for key, meta in dependency_info.items():
                if filter_to_worker and worker_pyprojects and not (meta['sources'] & worker_pyprojects):
                    continue
                dep_key = (key, tuple(sorted(meta['extras'])))
                if dep_key in existing_keys:
                    continue
                version = (pinned_versions or {}).get(key)
                if version:
                    extras_part = ''
                    if meta['extras']:
                        extras_part = '[' + ','.join(sorted(meta['extras'])) + ']'
                    spec = f"{meta['name']}{extras_part}=={version}"
                else:
                    spec = _format_dependency_spec(
                        meta['name'],
                        meta['extras'],
                        meta['specifiers'],
                    )
                if spec not in existing:
                    deps.append(spec)
                    existing.add(spec)
                    existing_keys.add(dep_key)

            project_tbl["dependencies"] = deps
            data["project"] = project_tbl
            pyproject_file.write_text(tomlkit.dumps(data))


        def _gather_dependency_specs(projects: list[Path | None]) -> None:
            seen_pyprojects: set[Path] = set()
            for project_path in projects:
                if not project_path:
                    continue
                pyproject_file = project_path / 'pyproject.toml'
                try:
                    resolved_pyproject = pyproject_file.resolve(strict=True)
                except FileNotFoundError:
                    continue
                if resolved_pyproject in seen_pyprojects:
                    continue
                seen_pyprojects.add(resolved_pyproject)
                try:
                    project_doc = tomlkit.parse(resolved_pyproject.read_text())
                except Exception:
                    continue
                deps = project_doc.get('project', {}).get('dependencies')
                if not deps:
                    continue
                for dep in deps:
                    try:
                        req = Requirement(str(dep))
                    except Exception:
                        continue
                    if req.marker and not req.marker.evaluate():
                        continue
                    normalized = req.name.lower()
                    if normalized.startswith('agi-') or normalized == 'agilab':
                        continue
                    meta = dependency_info.setdefault(
                        normalized,
                        {
                            'name': req.name,
                            'extras': set(),
                            'specifiers': [],
                            'has_exact': False,
                            'sources': set(),
                        },
                    )
                    if req.extras:
                        meta['extras'].update(req.extras)
                    meta['sources'].add(str(resolved_pyproject))
                    if req.specifier:
                        for specifier in req.specifier:
                            spec_str = str(specifier)
                            if specifier.operator in {'==', '==='}:
                                meta['has_exact'] = True
                                if not meta['specifiers'] or meta['specifiers'][0] != spec_str:
                                    meta['specifiers'] = [spec_str]
                                break
                            if meta['has_exact']:
                                continue
                            if spec_str not in meta['specifiers']:
                                meta['specifiers'].append(spec_str)


        if env.install_type == 0:
            repo_root = AgiEnv.read_agilab_path()
            if repo_root is None:
                repo_root = _infer_repo_root_from_runtime()
            if repo_root:
                repo_env_project = repo_root / "core" / "agi-env"
                repo_node_project = repo_root / "core" / "agi-node"
                repo_core_project = repo_root / "core" / "agi-core"
                repo_cluster_project = repo_root / "core" / "agi-cluster"
                try:
                    repo_agilab_root = repo_root.parents[1]
                except IndexError:
                    repo_agilab_root = None

            env_project = (
                repo_env_project
                if repo_env_project and repo_env_project.exists()
                else env.agi_env
            )
            node_project = (
                repo_node_project
                if repo_node_project and repo_node_project.exists()
                else env.agi_node
            )
            core_project = (
                repo_core_project
                if repo_core_project and repo_core_project.exists()
                else None
            )
            cluster_project = (
                repo_cluster_project
                if repo_cluster_project and repo_cluster_project.exists()
                else None
            )
            agilab_project = (
                repo_agilab_root
                if repo_agilab_root and repo_agilab_root.exists()
                else None
            )

            projects_for_specs = [
                agilab_project,
                env_project,
                node_project,
                core_project,
                cluster_project,
            ]
            _gather_dependency_specs(projects_for_specs)
            for project_path in (env_project, node_project, core_project, cluster_project):
                if not project_path:
                    continue
                pyproject_file = project_path / "pyproject.toml"
                try:
                    worker_pyprojects.add(str(pyproject_file.resolve(strict=True)))
                except FileNotFoundError:
                    continue
        else:
            env_project = env.agi_env
            node_project = env.agi_node
            core_project = None
            cluster_project = None
            agilab_project = None
            worker_pyprojects = set()

        wenv_abs = env.wenv_abs
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        uv = cmd_prefix + env.uv
        pyvers = env.python_version

        if hw_rapids_capable:
            AgiEnv.set_env_var(ip, "hw_rapids_capable")
        else:
            AgiEnv.set_env_var(ip, "no_rapids_hw")

        if env.verbose > 0:
            logger.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

        # =========
        # MANAGER install command with and without rapids capable
        # =========

        app_path = env.active_app
        manager_pyproject = app_path / "pyproject.toml"
        manager_pyproject_is_repo_file = _is_within_repo(manager_pyproject, repo_root)
        if (not env.is_source_env) and (not env.is_worker_env) and dependency_info:
            if manager_pyproject_is_repo_file:
                logger.info(
                    "Skipping dependency rewrite for %s to avoid mutating source checkout.",
                    manager_pyproject,
                )
            else:
                _update_pyproject_dependencies(
                    manager_pyproject,
                    pinned_versions=None,
                    filter_to_worker=False,
                )
        extra_indexes = ""
        if str(run_type).strip().startswith("sync") and _agi__version_missing_on_pypi(app_path):
            extra_indexes = (
                "PIP_INDEX_URL=https://test.pypi.org/simple "
                "PIP_EXTRA_INDEX_URL=https://pypi.org/simple "
            )
        if hw_rapids_capable:
            cmd_manager = (
                f"{extra_indexes}{uv} {run_type} --config-file uv_config.toml --project '{app_path}'"
            )
        else:
            cmd_manager = f"{extra_indexes}{uv} {run_type} --project '{app_path}'"

        # USE ROBUST REMOVE
        _force_remove(app_path / ".venv")

        try:
            (app_path / "uv.lock").unlink()
        except FileNotFoundError:
            pass

        if env.verbose > 0:
            logger.info(f"Installing manager: {cmd_manager}")
        await AgiEnv.run(cmd_manager, app_path)

        if (not env.is_source_env) and (not env.is_worker_env):
            await _ensure_pip(uv, app_path)

            for project_path in (
                agilab_project,
                env_project,
                node_project,
                core_project,
                cluster_project,
            ):
                if project_path and project_path.exists():
                    if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                        continue
                    cmd = (
                        f"{uv} run --project '{app_path}' python -m pip install "
                        f"--upgrade --no-deps '{project_path}'"
                    )
                    await AgiEnv.run(cmd, app_path)

            resources_src = env_project / 'src/agi_env/resources'
            if not resources_src.exists():
                resources_src = env.env_pck / 'resources'
            manager_resources = app_path / 'agilab/core/agi-env/src/agi_env/resources'
            if resources_src.exists():
                logger.info(f"mkdir {manager_resources.parent}")
                manager_resources.parent.mkdir(parents=True, exist_ok=True)
                if manager_resources.exists():
                    _force_remove(manager_resources)
                shutil.copytree(resources_src, manager_resources, dirs_exist_ok=True)

            site_packages_manager = env.env_pck.parent
            _cleanup_editable(site_packages_manager)

            if dependency_info:
                dep_versions = {}
                for key, meta in dependency_info.items():
                    try:
                        dep_versions[key] = pkg_version(meta['name'])
                    except PackageNotFoundError:
                        logger.debug("Dependency %s not installed in manager environment", meta['name'])

        if env.is_source_env:
            cmd = f"{uv} pip install -e '{env.agi_env}'"
            await AgiEnv.run(cmd, app_path)
            cmd = f"{uv} pip install -e '{env.agi_node}'"
            await AgiEnv.run(cmd, app_path)
            cmd = f"{uv} pip install -e '{env.agi_cluster}'"
            await AgiEnv.run(cmd, app_path)
            cmd = f"{uv} pip install -e ."
            await AgiEnv.run(cmd, app_path)

        # in case of core src has changed
        await AGI._build_lib_local()

        # ========
        # WORKER install command with and without rapids capable
        # ========

        uv_worker = cmd_prefix + env.uv_worker
        pyvers_worker = env.pyvers_worker

        worker_extra_indexes = ""
        if str(run_type).strip().startswith("sync") and _agi__version_missing_on_pypi(wenv_abs):
            worker_extra_indexes = (
                "PIP_INDEX_URL=https://test.pypi.org/simple; "
                "PIP_EXTRA_INDEX_URL=https://pypi.org/simple; "
            )

        if (not env.is_source_env) and (not env.is_worker_env) and dep_versions:
            _update_pyproject_dependencies(
                wenv_abs / "pyproject.toml",
                dep_versions,
                filter_to_worker=True,
            )

        _force_remove(wenv_abs / ".venv")

        worker_core_add_paths: list[Path] = []
        if env.is_source_env:
            worker_core_add_paths = [env.agi_env, env.agi_node]
        elif (
            (not env.is_worker_env)
            and env.install_type == 0
            and env_project
            and node_project
            and env_project.exists()
            and node_project.exists()
        ):
            worker_core_add_paths = [env_project, node_project]

        if worker_core_add_paths:
            quoted_paths = " ".join(f"\"{path}\"" for path in worker_core_add_paths)
            cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add {quoted_paths}"
            await AgiEnv.run(cmd_worker, wenv_abs)
        else:
            # add missing agi-anv and agi-node as there are not in pyproject.toml as wished
            cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-env"
            await AgiEnv.run(cmd_worker, wenv_abs)

            cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-node"
            await AgiEnv.run(cmd_worker, wenv_abs)

        if hw_rapids_capable:
            cmd_worker = (
                f"{worker_extra_indexes}{uv_worker} {run_type} --python {pyvers_worker} "
                f"--config-file uv_config.toml --project \"{wenv_abs}\""
            )
        else:
            cmd_worker = (
                f"{worker_extra_indexes}{uv_worker} {run_type} {options_worker} "
                f"--python {pyvers_worker} --project \"{wenv_abs}\""
            )

        if env.verbose > 0:
            logger.info(f"Installing workers: {cmd_worker}")
        await AgiEnv.run(cmd_worker, wenv_abs)

        _write_staged_uv_sources_pth(
            _worker_site_packages_dir(wenv_abs, env.pyvers_worker, windows=(os.name == "nt")),  # type: ignore[arg-type]
            wenv_abs / "_uv_sources",
        )

        #############
        # install env
        ##############

        if (not env.is_source_env) and (not env.is_worker_env):
            await _ensure_pip(uv_worker, wenv_abs)

            worker_resources_src = env_project / 'src/agi_env/resources'
            if not worker_resources_src.exists():
                worker_resources_src = env.env_pck / 'resources'
            resources_dest = wenv_abs / 'agilab/core/agi-env/src/agi_env/resources'
            logger.info(f"mkdir {resources_dest.parent}")
            resources_dest.parent.mkdir(parents=True, exist_ok=True)
            if resources_dest.exists():
                _force_remove(resources_dest)
            if worker_resources_src.exists():
                shutil.copytree(worker_resources_src, resources_dest, dirs_exist_ok=True)

            for project_path in (
                agilab_project,
                env_project,
                node_project,
                core_project,
                cluster_project,
            ):
                if project_path and project_path.exists():
                    if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                        continue
                    cmd = (
                        f"{uv_worker} run --project \"{wenv_abs}\" python -m pip install "
                        f"--upgrade --no-deps \"{project_path}\""
                    )
                    await AgiEnv.run(cmd, wenv_abs)

            python_dirs = env.pyvers_worker.split(".")
            if python_dirs[-1].endswith("t"):
                python_dir = f"{python_dirs[0]}.{python_dirs[1]}t"
            else:
                python_dir = f"{python_dirs[0]}.{python_dirs[1]}"
            site_packages_worker = (
                wenv_abs / ".venv" / "lib" / f"python{python_dir}" / "site-packages"
            )
            _cleanup_editable(site_packages_worker)

        else:
            # build agi_env*.whl
            menv = env.agi_env
            cmd = f"{uv} --project \"{menv}\" build --wheel"
            await AgiEnv.run(cmd, menv)
            src = menv / "dist"
            try:
                whl = next(iter(src.glob("agi_env*.whl")))
                # shutil.copy2(whl, wenv_abs)
            except StopIteration:
                raise RuntimeError(cmd)

            cmd = f"{uv_worker} pip install --project \"{wenv_abs}\" -e \"{env.agi_env}\""
            await AgiEnv.run(cmd, wenv_abs)

            # build agi_node*.whl
            menv = env.agi_node
            cmd = f"{uv} --project \"{menv}\" build --wheel"
            await AgiEnv.run(cmd, menv)
            src = menv / "dist"
            try:
                whl = next(iter(src.glob("agi_node*.whl")))
                shutil.copy2(whl, wenv_abs)
            except StopIteration:
                raise RuntimeError(cmd)

            cmd = f"{uv_worker} pip install --project \"{wenv_abs}\" -e \"{env.agi_node}\""
            await AgiEnv.run(cmd, wenv_abs)

        # Install the app sources into the worker venv using the absolute app path
        cmd = f"{uv_worker} pip install --project \"{wenv_abs}\" -e \"{env.active_app}\""
        await AgiEnv.run(cmd, wenv_abs)

        # dataset archives
        dest = wenv_abs / "src" / env.target_worker
        os.makedirs(dest, exist_ok=True)

        archives: list[Path] = []
        src = env.dataset_archive
        if isinstance(src, Path) and src.exists():
            archives.append(src)

        # Some apps ship additional optional archives (e.g. Trajectory.7z) under src/.
        # Copy those alongside dataset.7z so post_install can extract them if needed.
        try:
            active_src = Path(env.active_app) / "src"
            if active_src.exists():
                for candidate in active_src.rglob("Trajectory.7z"):
                    if candidate.is_file():
                        archives.append(candidate)
        except Exception:  # pragma: no cover - defensive guard
            pass

        if archives:
            try:
                share_root = env.share_root_path()
                install_dataset_dir = share_root
                logger.info(f"mkdir {install_dataset_dir}")
                os.makedirs(install_dataset_dir, exist_ok=True)

                seen_archives: set[str] = set()
                for archive_path in archives:
                    # Avoid copying satellite trajectory bundles when they can be reused from
                    # an already-installed sat_trajectory dataset on the share.
                    if archive_path.name == "Trajectory.7z":
                        try:
                            sat_trajectory_root = (Path(share_root) / "sat_trajectory").resolve(
                                strict=False
                            )
                            candidates = (
                                sat_trajectory_root / "dataframe" / "Trajectory",
                                sat_trajectory_root / "dataset" / "Trajectory",
                            )
                            has_samples = False
                            for candidate in candidates:
                                if candidate.is_dir():
                                    samples = []
                                    for pattern in ("*.csv", "*.parquet", "*.pq", "*.parq"):
                                        samples.extend(candidate.glob(pattern))
                                        if len(samples) >= 2:
                                            has_samples = True
                                            break
                                if has_samples:
                                    break
                            if has_samples:
                                logger.info(
                                    "Skipping %s copy; sat_trajectory trajectories already available at %s.",
                                    archive_path.name,
                                    sat_trajectory_root,
                                )
                                continue
                        except Exception:  # pragma: no cover - best-effort optimisation
                            pass

                    key = str(archive_path)
                    if key in seen_archives:
                        continue
                    seen_archives.add(key)
                    shutil.copy2(archive_path, dest / archive_path.name)
            except (FileNotFoundError, PermissionError, RuntimeError) as exc:
                logger.warning(
                    "Skipping dataset archive copy to %s: %s",
                    install_dataset_dir if "install_dataset_dir" in locals() else "<share root>",
                    exc,
                )

        post_install_cmd = (
            f"{uv_worker} run --no-sync --project \"{wenv_abs}\" "
            f"--python {pyvers_worker} python -m {env.post_install_rel} "
            f"{wenv_rel.stem}"
        )

        if env.user and env.user != getpass.getuser():
            try:
                await AGI.exec_ssh("127.0.0.1", post_install_cmd) #workaround for certain usecase (dont know which one)
            except ConnectionError as exc:
                logger.warning("SSH execution failed on localhost (%s), falling back to local run.", exc)
                await AgiEnv.run(post_install_cmd, wenv_abs)
        else:
            await AgiEnv.run(post_install_cmd, wenv_abs)

        # Cleanup modules
        await AGI._uninstall_modules()
        AGI._install_done_local = True

        cli = wenv_abs.parent / "cli.py"
        if not cli.exists():
            try:
                shutil.copy(env.cluster_pck / "agi_distributor/cli.py", cli)
            except FileNotFoundError as exc:
                logger.error("Missing cli.py for local worker: %s", exc)
                raise
        cmd = f"{uv_worker} run --no-sync --project \"{wenv_abs}\" python \"{cli}\" threaded"
        await AgiEnv.run(cmd, wenv_abs)

    @staticmethod
    async def _deploy_remote_worker(ip: str, env: AgiEnv, wenv_rel: Path, option: str) -> None:
        """Install packages and set up the environment on a remote node."""

        wenv_abs = env.wenv_abs
        wenv_rel = env.wenv_rel
        dist_rel = env.dist_rel
        dist_abs = env.dist_abs
        pyvers = env.pyvers_worker
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        uv = cmd_prefix + env.uv_worker

        # 1) set AGI_CLUSTER_SHARE on workers
        if AGI._workers_data_path:
            await AGI.exec_ssh(ip, "mkdir -p .agilab")
            await AGI.exec_ssh(ip, f"echo 'AGI_CLUSTER_SHARE=\"{Path(AGI._workers_data_path).expanduser().as_posix()}\"' > .agilab/.env")

        if env.is_source_env:
            # Then send the files to the remote directory
            egg_file = next(iter(dist_abs.glob(f"{env.target_worker}*.egg")), None)
            if egg_file is None:
                egg_file = next(iter(dist_abs.glob(f"{env.app}*.egg")), None)
            if egg_file is None:
                logger.error(f"searching for {dist_abs / env.target_worker}*.egg or {dist_abs / env.app}*.egg")
                raise FileNotFoundError(f"no existing egg file in {dist_abs / env.target_worker}* or {dist_abs / env.app}*")

            wenv = env.agi_env / 'dist'
            try:
                env_whl = next(iter(wenv.glob("agi_env*.whl")))
            except StopIteration:
                raise FileNotFoundError(f"no existing whl file in {wenv / 'agi_env*'}")

            # build agi_node*.whl
            wenv = env.agi_node / 'dist'
            try:
                node_whl = next(iter(wenv.glob("agi_node*.whl")))
            except StopIteration:
                raise FileNotFoundError(f"no existing whl file in {wenv / 'agi_node*'}")

            dist_remote = wenv_rel / "dist"
            logger.info(f"mkdir {dist_remote}")
            await AGI.exec_ssh(ip, f"mkdir -p '{dist_remote}'")
            await AGI.send_files(env, ip, [egg_file], wenv_rel)
            await AGI.send_files(env, ip, [node_whl, env_whl], dist_remote)
        else:
            # Then send the files to the remote directory
            egg_file = next(iter(dist_abs.glob(f"{env.target_worker}*.egg")), None)
            if egg_file is None:
                egg_file = next(iter(dist_abs.glob(f"{env.app}*.egg")), None)
            if egg_file is None:
                logger.error(f"searching for {dist_abs / env.target_worker}*.egg or {dist_abs / env.app}*.egg")
                raise FileNotFoundError(f"no existing egg file in {dist_abs / env.target_worker}* or {dist_abs / env.app}*")

            await AGI.send_files(env, ip, [egg_file], wenv_rel)

        # 5) Check remote Rapids hardware support via nvidia-smi
        hw_rapids_capable = False
        if AGI._rapids_enabled:
            check_rapids = 'nvidia-smi'

            try:
                result = await AGI.exec_ssh(ip, check_rapids)
            except Exception as e:
                logger.error(f"rapids is requested but not supported by node [{ip}]")
                raise

            hw_rapids_capable = (result != "") and AGI._rapids_enabled
            env.hw_rapids_capable = hw_rapids_capable
            if hw_rapids_capable:
                AgiEnv.set_env_var(ip, "hw_rapids_capable")
            logger.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

        # unzip egg to get src/
        cli = env.wenv_rel.parent / "cli.py"
        cmd = f"{uv} run -p {pyvers} python  {cli.as_posix()} unzip {wenv_rel.as_posix()}"
        await AGI.exec_ssh(ip, cmd)

        #############
        # install env
        #############

        cmd = f"{uv} --project {wenv_rel.as_posix()} run -p {pyvers} python -m ensurepip"
        await AGI.exec_ssh(ip, cmd)

        if env.is_source_env:
            env_pck = wenv_rel / "dist" / env_whl.name
            node_pck = wenv_rel / "dist" / node_whl.name
        else:
            env_pck = "agi-env"
            node_pck = "agi-node"

        def _pkg_ref(pkg: Union[str, Path]) -> str:
            return pkg.as_posix() if isinstance(pkg, Path) else str(pkg)

        # install env
        cmd = f"{uv} --project {wenv_rel.as_posix()} add -p {pyvers} --upgrade {_pkg_ref(env_pck)}"
        await AGI.exec_ssh(ip, cmd)

        # install node
        cmd = f"{uv} --project {wenv_rel.as_posix()} add -p {pyvers} --upgrade {_pkg_ref(node_pck)}"
        await AGI.exec_ssh(ip, cmd)

        remote_site_packages = _worker_site_packages_dir(
            PurePosixPath(wenv_rel.as_posix()),
            pyvers,
            windows=False,
        )
        remote_uv_sources = PurePosixPath(wenv_rel.as_posix()) / "_uv_sources"
        pth_content = _staged_uv_sources_pth_content(remote_site_packages, remote_uv_sources)
        tmp_pth = Path(gettempdir()) / f"agilab_uv_sources_{uuid.uuid4().hex}.pth"
        tmp_pth.write_text(pth_content, encoding="utf-8")
        try:
            await AGI.exec_ssh(ip, f"mkdir -p '{remote_site_packages.as_posix()}'")
            await AGI.send_file(
                env,
                ip,
                tmp_pth,
                remote_site_packages / "agilab_uv_sources.pth",
            )
        finally:
            try:
                tmp_pth.unlink()
            except FileNotFoundError:
                pass

        # unzip egg to get src/
        cli = env.wenv_rel.parent / "cli.py"
        cmd = f"{uv} --project {wenv_rel.as_posix()}  run --no-sync -p {pyvers} python {cli.as_posix()} unzip {wenv_rel.as_posix()}"
        await AGI.exec_ssh(ip, cmd)

        # Post-install script
        cmd = (
            f"{uv} --project {wenv_rel.as_posix()} run --no-sync -p {pyvers} python -m "
            f"{env.post_install_rel} {wenv_rel.stem}"
        )
        await AGI.exec_ssh(ip, cmd)

        # build target_worker lib from src/
        if env.verbose > 1:
            cmd = (
                f"{uv} --project '{wenv_rel.as_posix()}' run --no-sync -p {pyvers} python -m "
                f"agi_node.agi_dispatcher.build  --app-path  '{wenv_rel.as_posix()}' build_ext -b '{wenv_rel.as_posix()}'"
            )
        else:
            cmd = (
                f"{uv} --project '{wenv_rel.as_posix()}' run --no-sync -p {pyvers} python -m "
                f"agi_node.agi_dispatcher.build --app-path '{wenv_rel.as_posix()}' -q build_ext -b '{wenv_rel.as_posix()}'"
            )
        await AGI.exec_ssh(ip, cmd)

    @staticmethod
    def _should_install_pip() -> bool:
        return str(getpass.getuser()).startswith("T0") and not (Path(sys.prefix) / "Scripts/pip.exe").exists()

    @staticmethod
    async def _uninstall_modules() -> None:
        await deployment_prepare_support.uninstall_modules(
            AGI,
            AGI.env,
            run_fn=AgiEnv.run,
            log=logger,
        )

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """Format the duration from seconds to a human-readable format.

        Args:
            seconds (float): The duration in seconds.

        Returns:
            str: The formatted duration.
        """
        return humanize.precisedelta(timedelta(seconds=seconds))

    @staticmethod
    def _venv_todo(list_ip: Set[str]) -> None:
        deployment_prepare_support.venv_todo(AGI, list_ip, log=logger)

    @staticmethod
    async def install(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            workers_data_path: Optional[str] = None,
            modes_enabled: int = _RUN_MASK,
            verbose: Optional[int] = None,
            **args: Any,
    ) -> None:
        """
        Update the cluster's virtual environment.

        Args:
            project_path (Path):
                The name of the module to install or the path to the module.
            list_ip (List[str], optional):
                A list of IPv4 addresses with SSH access. Each IP should have Python,
                `psutil`, and `pdm` installed. Defaults to None.
            modes_enabled (int, optional):
                Bitmask indicating enabled modes. Defaults to `0b0111`.
            verbose (int, optional):
                Verbosity level (0-3). Higher numbers increase the verbosity of the output.
                Defaults to 1.
            **args:
                Additional keyword arguments.

        Returns:
            bool:
                `True` if the installation was successful, `False` otherwise.

        Raises:
            ValueError:
                If `module_name_or_path` is invalid.
            ConnectionError:
        """
        AGI._run_type = "sync"
        mode = (AGI._INSTALL_MODE | modes_enabled)
        await AGI.run(
            env=env,
            scheduler=scheduler,
            workers=workers,
            workers_data_path=workers_data_path,
            mode=mode,
            rapids_enabled=AGI._INSTALL_MODE & modes_enabled,
            verbose=verbose, **args
        )

    @staticmethod
    async def update(
            env: Optional[AgiEnv] = None,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            modes_enabled: int = _RUN_MASK,
            verbose: Optional[int] = None,
            **args: Any,
    ) -> None:
        """
        install cluster virtual environment
        Parameters
        ----------
        package: any Agi target apps or project created with AGILAB
        list_ip: any ip V4 with ssh access and python (upto you to link it to python3) with psutil and uv synced
        mode_enabled: this is typically a mode mask to know for example if cython or rapids are required
        force_update: make a Spud.update before the installation, default is True
        verbose: verbosity [0-3]

        Returns
        -------

        """
        AGI._run_type = "upgrade"
        await AGI.run(env=env, scheduler=scheduler, workers=workers,
                      mode=(AGI._UPDATE_MODE | modes_enabled) & AGI._DASK_RESET,
                      rapids_enabled=AGI._UPDATE_MODE & modes_enabled, **args)

    @staticmethod
    async def get_distrib(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        """
        check the distribution with a dry run
        Parameters
        ----------
        package: any Agi target apps or project created by AGILAB
        list_ip: any ip V4 with ssh access and python (upto you to link it to python3) with psutil and uv synced
        verbose: verbosity [0-3]

        Returns
        the distribution tree
        -------
        """
        AGI._run_type = "simulate"
        return await AGI.run(env, scheduler, workers, mode=AGI._SIMULATE_MODE, **args)

    # Backward compatibility alias
    @staticmethod
    async def distribute(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        return await AGI.get_distrib(env, scheduler, workers, verbose=verbose, **args)

    @staticmethod
    async def _start_scheduler(scheduler: Optional[str]) -> bool:
        """
        Start Dask scheduler either locally or remotely.

        Returns:
            bool: True on success.

        Raises:
            FileNotFoundError: if worker initialization error occurs.
            SystemExit: on fatal error starting scheduler or Dask client.
        """
        env = AGI.env
        cli_rel = env.wenv_rel.parent / "cli.py"

        if (AGI._mode_auto and AGI._mode == AGI.DASK_MODE) or not AGI._mode_auto:
            env.hw_rapids_capable = True
            if AGI._mode & AGI.DASK_MODE:
                if scheduler is None:
                    if list(AGI._workers) == ["127.0.0.1"]:
                        scheduler = "127.0.0.1"
                    else:
                        logger.info("AGI.run(...scheduler='scheduler ip address' is required -> Stop")

                AGI._scheduler_ip, AGI._scheduler_port = AGI._get_scheduler(scheduler)

            # Clean worker
            for ip in list(AGI._workers):
                await AGI.send_file(
                    env,
                    ip,
                    env.cluster_pck / "agi_distributor/cli.py",
                    cli_rel,
                )
                hw_rapids_capable = env.envars.get(ip, None)
                if not hw_rapids_capable or hw_rapids_capable == "no_rapids_hw":
                    env.hw_rapids_capable = False
                try:
                    await AGI._kill(ip, os.getpid(), force=True)
                except Exception as e:
                    raise

            # clean scheduler (avoid duplicate kill when scheduler host already handled as worker)
            if AGI._scheduler_ip not in AGI._workers:
                try:
                    await AGI._kill(AGI._scheduler_ip, os.getpid(), force=True)
                except Exception as e:
                    raise

            toml_local = env.active_app / "pyproject.toml"
            wenv_rel = env.wenv_rel
        else:
            toml_local = env.active_app / "pyproject.toml"
            wenv_rel = env.wenv_rel
        wenv_abs = env.wenv_abs
        if env.is_local(AGI._scheduler_ip):
            released = await AGI._wait_for_port_release(AGI._scheduler_ip, AGI._scheduler_port)
            if not released:
                new_port = AGI.find_free_port()
                logger.warning(
                    "Scheduler port %s:%s still busy. Switching scheduler port to %s.",
                    AGI._scheduler_ip,
                    AGI._scheduler_port,
                    new_port,
                )
                AGI._scheduler_port = new_port
                AGI._scheduler = f"{AGI._scheduler_ip}:{AGI._scheduler_port}"
            elif AGI._mode_auto:
                # Rotate ports between benchmark iterations to avoid TIME_WAIT collisions.
                new_port = AGI.find_free_port()
                AGI._scheduler_ip, AGI._scheduler_port = AGI._get_scheduler(
                    {AGI._scheduler_ip: new_port}
                )

        cmd_prefix = env.envars.get(f"{AGI._scheduler_ip}_CMD_PREFIX", "")
        if not cmd_prefix:
            try:
                cmd_prefix = await AGI._detect_export_cmd(AGI._scheduler_ip) or ""
            except Exception:
                cmd_prefix = ""
            if cmd_prefix:
                AgiEnv.set_env_var(f"{AGI._scheduler_ip}_CMD_PREFIX", cmd_prefix)

        dask_env = AGI._dask_env_prefix()
        if env.is_local(AGI._scheduler_ip):
            await asyncio.sleep(1)  # non-blocking sleep
            local_prefix = cmd_prefix or env.export_local_bin or ""
            cmd = (
                f"{local_prefix}{dask_env}{env.uv} run --no-sync --project {env.wenv_abs} "
                f"dask scheduler "
                f"--port {AGI._scheduler_port} "
                f"--host {AGI._scheduler_ip} "
                f"--dashboard-address :0 "
                f"--pid-file {wenv_abs.parent / 'dask_scheduler.pid'} "
            )
            logger.info(f"Starting dask scheduler locally: {cmd}")
            result = AGI._exec_bg(cmd, env.app)
            if result:  # assuming _exec_bg is sync
                logger.info(result)
        else:
            # Create remote directory
            cmd = (
                f"{cmd_prefix}{env.uv} run --no-sync python -c "
                f"\"import os; os.makedirs('{wenv_rel}', exist_ok=True)\""
            )
            await AGI.exec_ssh(AGI._scheduler_ip, cmd)

            toml_wenv = wenv_rel / "pyproject.toml"
            await AGI.send_file(env, AGI._scheduler_ip, toml_local, toml_wenv)

            cmd = (
                f"{cmd_prefix}{dask_env}{env.uv} --project {wenv_rel} run --no-sync "
                f"dask scheduler "
                f"--port {AGI._scheduler_port} "
                f"--host {AGI._scheduler_ip} --dashboard-address :0 --pid-file dask_scheduler.pid"
            )
            # Run scheduler asynchronously over SSH without awaiting completion (fire and forget)
            asyncio.create_task(AGI.exec_ssh_async(AGI._scheduler_ip, cmd))

        await asyncio.sleep(1)  # Give scheduler a moment to spin up
        try:
            client = await AGI._connect_scheduler_with_retry(
                AGI._scheduler,
                timeout=max(AGI._TIMEOUT * 3, 15),
                heartbeat_interval=5000,
            )
            AGI._dask_client = client
        except Exception as e:
            logger.error("Dask Client instantiation trouble, run aborted due to:")
            logger.info(e)
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError("Failed to instantiate Dask Client") from e

        AGI._install_done = True
        if AGI._worker_init_error:
            raise FileNotFoundError(f"Please run AGI.install([{AGI._scheduler_ip}])")

        return True

    @staticmethod
    async def _connect_scheduler_with_retry(
        address: str,
        *,
        timeout: float,
        heartbeat_interval: int = 5000,
    ) -> Client:
        """Attempt to connect to the scheduler until ``timeout`` elapses."""

        deadline = time.monotonic() + max(timeout, 1)
        attempt = 0
        last_exc: Optional[Exception] = None
        while time.monotonic() < deadline:
            attempt += 1
            remaining = max(deadline - time.monotonic(), 0.5)
            try:
                return await Client(
                    address,
                    heartbeat_interval=heartbeat_interval,
                    timeout=remaining,
                )
            except Exception as exc:
                last_exc = exc
                sleep_for = min(1.0 * attempt, 5.0)
                logger.debug(
                    "Dask scheduler at %s not ready (attempt %s, retrying in %.1fs): %s",
                    address,
                    attempt,
                    sleep_for,
                    exc,
                )
                await asyncio.sleep(sleep_for)

        raise RuntimeError("Failed to instantiate Dask Client") from last_exc

    @staticmethod
    async def _detect_export_cmd(ip: str) -> Optional[str]:
        if AgiEnv.is_local(ip):
            return AgiEnv.export_local_bin

        # probe remote OS via SSH
        try:
            os_id = await AGI.exec_ssh(ip, "uname -s")
        except Exception:
            os_id = ''

        if any(x in os_id for x in ('Linux', 'Darwin', 'BSD')):
            return 'export PATH="$HOME/.local/bin:$PATH";'
        else:
            return ""  # 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'

    @staticmethod
    def _dask_env_prefix() -> str:
        level = AGI._dask_log_level
        if not level:
            return ""
        env_vars = [
            f"DASK_DISTRIBUTED__LOGGING__distributed={level}",
        ]
        return "".join(f"{var} " for var in env_vars)

    @staticmethod
    async def _start(scheduler: Optional[str]) -> bool:
        """_start(
        Start Dask workers locally and remotely,
        launching remote workers detached in background,
        compatible with Windows and POSIX.
        """
        env = AGI.env
        dask_env = AGI._dask_env_prefix()

        # Start scheduler first
        if not await AGI._start_scheduler(scheduler):
            return False

        for i, (ip, n) in enumerate(AGI._workers.items()):
            is_local = env.is_local(ip)
            cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
            if not cmd_prefix:
                try:
                    cmd_prefix = await AGI._detect_export_cmd(ip) or ""
                except Exception:
                    cmd_prefix = ""
                if cmd_prefix:
                    AgiEnv.set_env_var(f"{ip}_CMD_PREFIX", cmd_prefix)

            for j in range(n):
                try:
                    logger.info(f"Starting worker #{i}.{j} on [{ip}]")
                    pid_file = f"dask_worker_{i}_{j}.pid"
                    if is_local:
                        wenv_abs = env.wenv_abs
                        cmd = (
                            f'{cmd_prefix}{dask_env}{env.uv} --project {wenv_abs} run --no-sync '
                            f'dask worker '
                            f'tcp://{AGI._scheduler} --no-nanny '
                            f'--pid-file {wenv_abs / pid_file}'
                        )
                        # Run locally in background (non-blocking)
                        AGI._exec_bg(cmd, str(wenv_abs))
                    else:
                        wenv_rel = env.wenv_rel
                        cmd = (
                            f'{cmd_prefix}{dask_env}{env.uv} --project {wenv_rel} run --no-sync '
                            f'dask worker '
                            f'tcp://{AGI._scheduler} --no-nanny --pid-file {wenv_rel.parent / pid_file}'
                        )
                        asyncio.create_task(AGI.exec_ssh_async(ip, cmd))
                        logger.info(f"Launched remote worker in background on {ip}: {cmd}")

                except Exception as e:
                    logger.error(f"Failed to start worker on {ip}: {e}")
                    raise

                if AGI._worker_init_error:
                    raise FileNotFoundError(f"Please run AGI.install([{ip}])")

        await AGI._sync(timeout=AGI._TIMEOUT)

        if not AGI._mode_auto or (AGI._mode_auto and AGI._mode == 0):
            await AGI._build_lib_remote()
            if AGI._mode & AGI.DASK_MODE:
                # load lib
                for egg_file in (AGI.env.wenv_abs / "dist").glob("*.egg"):
                    AGI._dask_client.upload_file(str(egg_file))

    @staticmethod
    async def _sync(timeout: int = 60) -> None:
        if not isinstance(AGI._dask_client, Client):
            return
        start = time.time()
        expected_workers = sum(AGI._workers.values())

        while True:
            try:
                info = AGI._dask_client.scheduler_info()
                workers_info = info.get("workers")
                if workers_info is None:
                    logger.info("Scheduler info 'workers' not ready yet.")
                    await asyncio.sleep(3)
                    if time.time() - start > timeout:
                        logger.error(f"Timeout waiting for scheduler workers info.")
                        raise TimeoutError("Timed out waiting for scheduler workers info")
                    continue

                runners = list(workers_info.keys())
                current_count = len(runners)
                remaining = expected_workers - current_count

                if runners:
                    logger.info(f"Current workers connected: {runners}")
                logger.info(f"Waiting for number of workers to attach: {remaining} remaining...")

                if current_count >= expected_workers:
                    break

                if remaining <= 0:
                    break

                if time.time() - start > timeout:
                    logger.error("Timeout waiting for all workers. {remaining} workers missing.")
                    raise TimeoutError("Timed out waiting for all workers to attach")
                await asyncio.sleep(3)

            except Exception as e:
                logger.info(f"Exception in _sync: {e}")
                await asyncio.sleep(1)
                if time.time() - start > timeout:
                    raise TimeoutError(f"Timeout waiting for all workers due to exception: {e}")

        logger.info("All workers successfully attached to scheduler")

    @staticmethod
    async def _build_lib_local():
        await deployment_build_support.build_lib_local(
            AGI,
            ensure_optional_extras_fn=_ensure_optional_extras,
            stage_uv_sources_fn=_stage_uv_sources_for_copied_pyproject,
            validate_worker_uv_sources_fn=_validate_worker_uv_sources,
            run_fn=AgiEnv.run,
            log=logger,
        )

    @staticmethod
    async def _build_lib_remote() -> None:
        await deployment_build_support.build_lib_remote(AGI, log=logger)

    @staticmethod
    async def _run() -> Any:
        """

        Returns:

        """
        env = AGI.env
        env.hw_rapids_capable = env.envars.get("127.0.0.1", "hw_rapids_capable")

        # check first that install is done
        if not (env.wenv_abs / ".venv").exists():
            logger.info("Worker installation not found")
            raise FileNotFoundError("Worker installation (.venv) not found")
        _validate_worker_uv_sources(env.wenv_abs / "pyproject.toml")

        pid_file = "dask_worker_0.pid"
        current_pid = os.getpid()
        with open(pid_file, "w") as f:
            f.write(str(current_pid))

        await AGI._kill(current_pid=current_pid, force=True)

        if AGI._mode & AGI.CYTHON_MODE:
            wenv_abs = env.wenv_abs
            cython_lib_path = Path(wenv_abs)

        logger.info(f"debug={env.debug}")

        if env.debug:
            BaseWorker._new(env=env, mode=AGI._mode, verbose=env.verbose, args=AGI._args)
            res = await BaseWorker._run(env=env, mode=AGI._mode, workers=AGI._workers, verbose=env.verbose,
                                       args=AGI._args)
        else:
            cmd = (
                f"{env.uv} run --preview-features python-upgrade --no-sync --project {env.wenv_abs} python -c \""
                f"from agi_node.agi_dispatcher import  BaseWorker\n"
                f"import asyncio\n"
                f"async def main():\n"
                f"  BaseWorker._new(app='{env.target_worker}', mode={AGI._mode}, verbose={env.verbose}, args={AGI._args})\n"
                f"  res = await BaseWorker._run(mode={AGI._mode}, workers={AGI._workers}, args={AGI._args})\n"
                f"  print(res)\n"
                f"if __name__ == '__main__':\n"
                f"  asyncio.run(main())\""
            )

            res = await AgiEnv.run_async(cmd, env.wenv_abs)

        if res:
            if isinstance(res, list):
                return res
            else:
                res_lines = res.split('\n')
                if len(res_lines) < 2:
                    return res
                else:
                    return res.split('\n')[-2]

    @staticmethod
    async def _distribute() -> str:
        """
        workers run calibration and targets job
        """
        env = AGI.env

        # AGI distribute work on cluster
        AGI._dask_workers = [
            worker.split("/")[-1]
            for worker in list(AGI._dask_client.scheduler_info()["workers"].keys())
        ]
        logger.info(f"AGI run mode={AGI._mode} on {list(AGI._dask_workers)} ... ")

        AGI._workers, workers_plan, workers_plan_metadata = await WorkDispatcher._do_distrib(
            env, AGI._workers, AGI._args
        )
        AGI._work_plan = workers_plan
        AGI._work_plan_metadata = workers_plan_metadata

        AGI._scale_cluster()

        if AGI._mode == AGI._INSTALL_MODE:
            workers_plan

        dask_workers = list(AGI._dask_workers)
        client = AGI._dask_client

        AGI._dask_client.gather(
            [
                client.submit(
                    BaseWorker._new,
                    env=0 if env.debug else None,
                    app=env.target_worker,
                    mode=AGI._mode,
                    verbose=AGI.verbose,
                    worker_id=dask_workers.index(worker),
                    worker=worker,
                    args=AGI._args,
                    workers=[worker],
                )
                for worker in dask_workers
            ]
        )

        await AGI._calibration()

        t = time.time()

        futures = {}
        for worker_idx, worker_addr in enumerate(dask_workers):
            plan_payload = AGI._wrap_worker_chunk(workers_plan or [], worker_idx)
            metadata_payload = AGI._wrap_worker_chunk(workers_plan_metadata or [], worker_idx)
            futures[worker_addr] = client.submit(
                BaseWorker._do_works,
                plan_payload,
                metadata_payload,
                workers=[worker_addr],
            )

        gathered_logs = client.gather(list(futures.values())) if futures else []
        worker_logs: Dict[str, str] = {}
        for idx, worker_addr in enumerate(futures.keys()):
            log_value = gathered_logs[idx] if idx < len(gathered_logs) else ""
            worker_logs[worker_addr] = log_value or ""
        if AGI.debug and not worker_logs:
            worker_logs = {worker: "" for worker in dask_workers}

        # LOG ONLY, no print:
        for worker, log in worker_logs.items():
            logger.info(f"\n=== Worker {worker} logs ===\n{log}")

        runtime = time.time() - t
        logger.info(f"{env.mode2str(AGI._mode)} {runtime}")
        return f"{env.mode2str(AGI._mode)} {runtime}"

    @staticmethod
    async def _main(scheduler: Optional[str]) -> Any:
        cond_clean = True

        AGI._jobs = bg.BackgroundJobManager()

        if (AGI._mode & AGI._DEPLOYEMENT_MASK) == AGI._SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = await AGI._run()

        elif AGI._mode >= AGI._INSTALL_MODE:
            # case install modes
            t = time.time()

            AGI._clean_dirs_local()
            await AGI._prepare_local_env()

            if AGI._mode & AGI.DASK_MODE:
                await AGI._prepare_cluster_env(scheduler)

            await AGI._deploy_application(scheduler)

            res = time.time() - t

        elif (AGI._mode & AGI._DEPLOYEMENT_MASK) == AGI._SIMULATE_MODE:
            # case simulate mode #0b11xxxx
            res = await AGI._run()

        elif AGI._mode & AGI.DASK_MODE:

            await AGI._start(scheduler)

            res = await AGI._distribute()
            AGI._update_capacity()

            # stop the cluster
            await AGI._stop()
        else:
            # case local run
            res = await AGI._run()

        AGI._clean_job(cond_clean)

        return res

    @staticmethod
    def _clean_job(cond_clean: bool) -> None:
        """

        Args:
          cond_clean:

        Returns:

        """
        # clean background job
        if AGI._jobs and cond_clean:
            if AGI.verbose:
                AGI._jobs.flush()
            else:
                with open(os.devnull, "w") as f, redirect_stdout(f), redirect_stderr(f):
                    AGI._jobs.flush()

    @staticmethod
    def _scale_cluster() -> None:
        """Remove unnecessary workers"""
        if AGI._dask_workers:
            nb_kept_workers = {}
            workers_to_remove = []
            for dask_worker in AGI._dask_workers:
                ip = dask_worker.split(":")[0]
                if ip in AGI._workers:
                    if ip not in nb_kept_workers:
                        nb_kept_workers[ip] = 0
                    if nb_kept_workers[ip] >= AGI._workers[ip]:
                        workers_to_remove.append(dask_worker)
                    else:
                        nb_kept_workers[ip] += 1
                else:
                    workers_to_remove.append(dask_worker)

            if workers_to_remove:
                logger.info(f"unused workers: {len(workers_to_remove)}")
                for worker in workers_to_remove:
                    AGI._dask_workers.remove(worker)

    @staticmethod
    async def _stop() -> None:
        """Stop the Dask workers and scheduler"""
        env = AGI.env
        logger.info("stop Agi core")

        retire_attempts = 0
        while retire_attempts < AGI._TIMEOUT:
            try:
                scheduler_info = await AGI._dask_client.scheduler_info()
            except Exception as exc:
                logger.debug("Unable to fetch scheduler info during shutdown: %s", exc)
                break

            workers = scheduler_info.get("workers") or {}
            if not workers:
                break

            retire_attempts += 1
            try:
                await AGI._dask_client.retire_workers(
                    workers=list(workers.keys()),
                    close_workers=True,
                    remove=True,
                )
            except Exception as exc:
                logger.debug("retire_workers failed: %s", exc)
                break

            await asyncio.sleep(1)

        try:
            if (
                AGI._mode_auto and (AGI._mode == 7 or AGI._mode == 15)
            ) or not AGI._mode_auto:
                await AGI._dask_client.shutdown()
        except Exception as exc:
            logger.debug("Dask client shutdown raised: %s", exc)

        await AGI._close_all_connections()

    @staticmethod
    async def _calibration() -> None:
        await capacity_support.calibration(AGI, log=logger)

    @staticmethod
    def _train_capacity(train_home: Path) -> None:
        capacity_support.train_capacity(AGI, train_home, log=logger)

    @staticmethod
    def _update_capacity() -> None:
        capacity_support.update_capacity(AGI)

    @staticmethod
    def _exec_bg(cmd: str, cwd: str) -> None:
        """
        Execute background command
        Args:
            cmd: the command to be run
            cwd: the current working directory

        Returns:
            """
        job = AGI._jobs.new(cmd, cwd=cwd)
        job_id = getattr(job, "num", 0)
        if not AGI._jobs.result(job_id):
            raise RuntimeError(f"running {cmd} at {cwd}")

    @asynccontextmanager
    async def get_ssh_connection(ip: str, timeout_sec: int = 5):
        async with transport_support.get_ssh_connection(
            AGI,
            ip,
            timeout_sec=timeout_sec,
            discover_private_keys_fn=_discover_private_ssh_keys,
            log=logger,
        ) as conn:
            yield conn

    @staticmethod
    async def exec_ssh(ip: str, cmd: str) -> str:
        return await transport_support.exec_ssh(
            AGI,
            ip,
            cmd,
            process_error_cls=ProcessError,
            log=logger,
        )

    @staticmethod
    async def exec_ssh_async(ip: str, cmd: str) -> str:
        return await transport_support.exec_ssh_async(AGI, ip, cmd)

    @staticmethod
    async def _close_all_connections():
        await transport_support.close_all_connections(AGI)


def _format_exception_chain(exc: BaseException) -> str:
    """Return a compact representation of the exception chain, capturing root causes."""
    messages: List[str] = []
    norms: List[str] = []
    visited = set()
    current: Optional[BaseException] = exc

    def _normalize(text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        lowered = text.lower()
        for token in ("error:", "exception:", "warning:", "runtimeerror:", "valueerror:", "typeerror:"):
            if lowered.startswith(token):
                return text[len(token):].strip()
        if ": " in text:
            head, tail = text.split(": ", 1)
            if head.endswith(("Error", "Exception", "Warning")):
                return tail.strip()
        return text

    while current and id(current) not in visited:
        visited.add(id(current))
        tb_exc = traceback.TracebackException.from_exception(current)
        text = "".join(tb_exc.format_exception_only()).strip()
        if not text:
            text = f"{current.__class__.__name__}: {current}"
        if text:
            norm = _normalize(text)
            if messages:
                last_norm = norms[-1]
                if not norm:
                    norm = text
                if norm == last_norm:
                    pass
                elif last_norm.endswith(norm):
                    messages[-1] = text
                    norms[-1] = norm
                elif norm.endswith(last_norm):
                    # Current message is a superset; keep existing shorter variant.
                    pass
                else:
                    messages.append(text)
                    norms.append(norm)
            else:
                messages.append(text)
                norms.append(norm if norm else text)

        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None and not getattr(current, "__suppress_context__", False):
            current = current.__context__
        else:
            break

    if not messages:
        return str(exc).strip() or repr(exc)
    return " -> ".join(messages)
