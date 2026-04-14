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
    cleanup_support,
    deployment_build_support,
    deployment_local_support,
    deployment_orchestration_support,
    deployment_prepare_support,
    deployment_remote_support,
    entrypoint_support,
    runtime_distribution_support,
    scheduler_io_support,
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
        return await entrypoint_support.run(
            AGI,
            env=env,
            scheduler=scheduler,
            workers=workers,
            workers_data_path=workers_data_path,
            verbose=verbose,
            mode=mode,
            rapids_enabled=rapids_enabled,
            workers_default=_workers_default,
            process_error_type=ProcessError,
            format_exception_chain_fn=_format_exception_chain,
            traceback_format_exc_fn=traceback.format_exc,
            log=logger,
            **args,
        )

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
        return scheduler_io_support.get_default_local_ip(
            socket_factory=socket.socket,
        )

    @staticmethod
    def find_free_port(start: int = 5000, end: int = 10000, attempts: int = 100) -> int:
        return scheduler_io_support.find_free_port(
            start=start,
            end=end,
            attempts=attempts,
            randint_fn=random.randint,
            socket_factory=socket.socket,
        )

    @staticmethod
    def _get_scheduler(ip_sched: Optional[Union[str, Dict[str, int]]] = None) -> Tuple[str, int]:
        return scheduler_io_support.get_scheduler(
            AGI,
            ip_sched,
            find_free_port_fn=AGI.find_free_port,
            gethostbyname_fn=socket.gethostbyname,
        )

    @staticmethod
    def _get_stdout(func: Any, *args: Any, **kwargs: Any) -> Tuple[str, Any]:
        return scheduler_io_support.get_stdout(func, *args, **kwargs)

    @staticmethod
    def _read_stderr(output_stream: Any) -> None:
        scheduler_io_support.read_stderr(
            AGI,
            output_stream,
            sleep_fn=time.sleep,
            log=logger,
        )

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
        cleanup_support.remove_dir_forcefully(
            path,
            rmtree_fn=shutil.rmtree,
            sleep_fn=time.sleep,
            access_fn=os.access,
            chmod_fn=os.chmod,
            log=logger,
        )

    @staticmethod
    async def _kill(ip: Optional[str] = None, current_pid: Optional[int] = None, force: bool = True) -> Optional[Any]:
        return await cleanup_support.kill_processes(
            AGI,
            ip=ip,
            current_pid=current_pid,
            force=force,
            gethostbyname_fn=socket.gethostbyname,
            run_fn=AgiEnv.run,
            copy_fn=shutil.copy,
            run_path_fn=runpy.run_path,
            sys_module=sys,
            path_cls=Path,
            log=logger,
        )

    @staticmethod
    async def _wait_for_port_release(ip: str, port: int, timeout: float = 5.0, interval: float = 0.2) -> bool:
        return await cleanup_support.wait_for_port_release(
            ip,
            port,
            timeout=timeout,
            interval=interval,
            gethostbyname_fn=socket.gethostbyname,
            socket_factory=socket.socket,
            sleep_fn=asyncio.sleep,
            monotonic_fn=time.monotonic,
        )

    @staticmethod
    def _clean_dirs_local() -> None:
        cleanup_support.clean_dirs_local(
            AGI,
            process_iter_fn=psutil.process_iter,
            getuser_fn=getpass.getuser,
            getpid_fn=os.getpid,
            rmtree_fn=shutil.rmtree,
            gettempdir_fn=gettempdir,
        )

    @staticmethod
    async def _clean_dirs(ip: str) -> None:
        await cleanup_support.clean_dirs(
            AGI,
            ip,
            makedirs_fn=os.makedirs,
            remove_dir_forcefully_fn=AGI._remove_dir_forcefully,
        )

    @staticmethod
    async def _clean_nodes(scheduler_addr: Optional[str], force: bool = True) -> Set[str]:
        return await deployment_orchestration_support.clean_nodes(
            AGI,
            scheduler_addr,
            force=force,
            is_local_fn=AgiEnv.is_local,
            gethostbyname_fn=socket.gethostbyname,
        )

    @staticmethod
    async def _clean_remote_procs(list_ip: Set[str], force: bool = True) -> None:
        await deployment_orchestration_support.clean_remote_procs(
            AGI,
            list_ip,
            force=force,
            is_local_fn=AgiEnv.is_local,
        )

    @staticmethod
    async def _clean_remote_dirs(list_ip: Set[str]) -> None:
        await deployment_orchestration_support.clean_remote_dirs(AGI, list_ip)

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
        await deployment_orchestration_support.deploy_application(
            AGI,
            scheduler_addr,
            time_fn=time.time,
            log=logger,
        )

    @staticmethod
    def _reset_deploy_state() -> None:
        """Initialize installation flags and run type."""
        deployment_orchestration_support.reset_deploy_state(AGI)

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
        await deployment_local_support.deploy_local_worker(
            AGI,
            src,
            wenv_rel,
            options_worker,
            agi_version_missing_on_pypi_fn=_agi__version_missing_on_pypi,
            worker_site_packages_dir_fn=_worker_site_packages_dir,
            write_staged_uv_sources_pth_fn=_write_staged_uv_sources_pth,
            runtime_file=__file__,
            run_fn=AgiEnv.run,
            set_env_var_fn=AgiEnv.set_env_var,
            log=logger,
        )

    @staticmethod
    async def _deploy_remote_worker(ip: str, env: AgiEnv, wenv_rel: Path, option: str) -> None:
        await deployment_remote_support.deploy_remote_worker(
            AGI,
            ip,
            env,
            wenv_rel,
            option,
            worker_site_packages_dir_fn=_worker_site_packages_dir,
            staged_uv_sources_pth_content_fn=_staged_uv_sources_pth_content,
            set_env_var_fn=AgiEnv.set_env_var,
            log=logger,
        )

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
        await entrypoint_support.install(
            AGI,
            env=env,
            scheduler=scheduler,
            workers=workers,
            workers_data_path=workers_data_path,
            modes_enabled=modes_enabled,
            verbose=verbose,
            args=args,
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
        await entrypoint_support.update(
            AGI,
            env=env,
            scheduler=scheduler,
            workers=workers,
            modes_enabled=modes_enabled,
            args=args,
        )

    @staticmethod
    async def get_distrib(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        return await entrypoint_support.get_distrib(
            AGI,
            env=env,
            scheduler=scheduler,
            workers=workers,
            args=args,
        )

    # Backward compatibility alias
    @staticmethod
    async def distribute(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        return await entrypoint_support.distribute(
            AGI,
            env=env,
            scheduler=scheduler,
            workers=workers,
            args=args,
        )

    @staticmethod
    async def _start_scheduler(scheduler: Optional[str]) -> bool:
        return await entrypoint_support.start_scheduler(
            AGI,
            scheduler,
            set_env_var_fn=AgiEnv.set_env_var,
            create_task_fn=asyncio.create_task,
            sleep_fn=asyncio.sleep,
            log=logger,
        )

    @staticmethod
    async def _connect_scheduler_with_retry(
        address: str,
        *,
        timeout: float,
        heartbeat_interval: int = 5000,
    ) -> Client:
        return await entrypoint_support.connect_scheduler_with_retry(
            address,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
            client_factory=Client,
            sleep_fn=asyncio.sleep,
            monotonic_fn=time.monotonic,
            log=logger,
        )

    @staticmethod
    async def _detect_export_cmd(ip: str) -> Optional[str]:
        return await entrypoint_support.detect_export_cmd(
            AGI,
            ip,
            is_local_fn=AgiEnv.is_local,
            local_export_bin=AgiEnv.export_local_bin,
        )

    @staticmethod
    def _dask_env_prefix() -> str:
        return runtime_distribution_support.dask_env_prefix(AGI)

    @staticmethod
    async def _start(scheduler: Optional[str]) -> bool:
        return await runtime_distribution_support.start(
            AGI,
            scheduler,
            set_env_var_fn=AgiEnv.set_env_var,
            create_task_fn=asyncio.create_task,
            log=logger,
        )

    @staticmethod
    async def _sync(timeout: int = 60) -> None:
        await runtime_distribution_support.sync(
            AGI,
            timeout=timeout,
            client_type=Client,
            sleep_fn=asyncio.sleep,
            time_fn=time.time,
            log=logger,
        )

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
        return await runtime_distribution_support.run_local(
            AGI,
            base_worker_cls=BaseWorker,
            validate_worker_uv_sources_fn=_validate_worker_uv_sources,
            run_async_fn=AgiEnv.run_async,
            log=logger,
        )

    @staticmethod
    async def _distribute() -> str:
        return await runtime_distribution_support.distribute(
            AGI,
            work_dispatcher_cls=WorkDispatcher,
            base_worker_cls=BaseWorker,
            time_fn=time.time,
            log=logger,
        )

    @staticmethod
    async def _main(scheduler: Optional[str]) -> Any:
        return await runtime_distribution_support.main(
            AGI,
            scheduler,
            background_job_manager_factory=bg.BackgroundJobManager,
            time_fn=time.time,
        )

    @staticmethod
    def _clean_job(cond_clean: bool) -> None:
        runtime_distribution_support.clean_job(AGI, cond_clean)

    @staticmethod
    def _scale_cluster() -> None:
        runtime_distribution_support.scale_cluster(AGI, log=logger)

    @staticmethod
    async def _stop() -> None:
        await runtime_distribution_support.stop(
            AGI,
            sleep_fn=asyncio.sleep,
            log=logger,
        )

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
        runtime_distribution_support.exec_bg(AGI, cmd, cwd)

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
