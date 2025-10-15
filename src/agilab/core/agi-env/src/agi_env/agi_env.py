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
"""AGILab environment bootstrapper and utility helpers.

The module exposes the :class:`AgiEnv` class which orchestrates project discovery,
virtual-environment management, packaging helpers, and convenience utilities used
by installers as well as runtime workers. Supporting free functions provide small
parsing and path utilities leveraged during setup.

Notes on singleton and pre‑init behavior
---------------------------------------
- ``AgiEnv`` behaves as a true singleton. Instance attributes are the source of
  truth; class attribute reads proxy to the singleton instance when initialised.
  Methods and descriptors are never shadowed by the delegation.
- A small subset of helpers is pre‑init safe and can be used before constructing
  an instance: :func:`AgiEnv.set_env_var`, :func:`AgiEnv.read_agilab_path`,
  :func:`AgiEnv._build_env`, and :func:`AgiEnv.log_info`. These functions avoid
  hard failures when the shared logger/environment has not been configured yet.
  Logging in that mode is best‑effort and may fall back to ``print``.
"""
import shlex
try:
    from IPython.core.ultratb import FormattedTB
except Exception:  # Optional dependency; fallback if absent
    FormattedTB = None  # type: ignore
import ast
import asyncio
import getpass
import os
import re
import shutil
import psutil
import socket
import subprocess
import sys
import traceback
from functools import lru_cache
from pathlib import Path, PureWindowsPath, PurePosixPath
import tempfile
from dotenv import dotenv_values, set_key
import tomlkit
import logging
import astor
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
import py7zr
import urllib.request
import inspect
import ctypes
from ctypes import wintypes
import importlib.util
import importlib.resources as importlib_resources
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from agi_env.agi_logger import AgiLogger
import inspect as _inspect
if FormattedTB is not None:
    # Get constructor parameters of FormattedTB
    _sig = inspect.signature(FormattedTB.__init__).parameters

    _tb_kwargs = dict(mode='Verbose', call_pdb=True)
    if 'color_scheme' in _sig:
        _tb_kwargs['color_scheme'] = 'NoColor'
    else:
        _tb_kwargs['theme_name'] = 'NoColor'

    sys.excepthook = FormattedTB(**_tb_kwargs)

# logger = AgiLogger.get_logger(__name__)


@lru_cache(maxsize=None)
def _resolve_worker_hook(filename: str) -> Path | None:
    """Return the path to the shared worker hook.

    Resolution order:
    1) If ``agi_node.agi_dispatcher`` is importable, use its installed files.
    2) In source checkouts, look for ``core/agi-node/src/agi_node/agi_dispatcher/<filename>``
       relative to this module location.
    3) As a last resort, try reading the resource via importlib.resources when the
       package is importable from a zip.
    """

    # 1) Try the installed package first
    try:
        spec = importlib.util.find_spec("agi_node.agi_dispatcher")
    except ModuleNotFoundError:
        spec = None
    candidates: list[Path] = []

    if spec is not None:
        search_locations = list(spec.submodule_search_locations or [])
        for location in search_locations:
            if location:
                candidates.append(Path(location) / filename)

        if spec.origin:
            origin_path = Path(spec.origin)
            if origin_path.name == "__init__.py":
                candidates.append(origin_path.parent / filename)
            else:
                candidates.append(origin_path.with_name(filename))

        for candidate in candidates:
            if candidate.exists():
                return candidate

    # 2) Fallback for source-tree usage (no agi_node installed)
    # This file lives at: .../core/agi-env/src/agi_env/agi_env.py
    here = Path(__file__).resolve()
    try:
        repo_agilab_dir = here.parents[4]  # .../src/agilab
        core_root = repo_agilab_dir / "core"
        src_hook = core_root / "agi-node/src/agi_node/agi_dispatcher" / filename
        pkg_hook = core_root / "agi-node/agi_dispatcher" / filename
        for candidate in (src_hook, pkg_hook):
            if candidate.exists():
                return candidate
    except Exception:
        # Best-effort only; ignore path probing errors
        pass

    # 3) Attempt extracting from package resources (zip installs)
    try:
        package_root = importlib_resources.files("agi_node.agi_dispatcher")
    except (ModuleNotFoundError, AttributeError):
        return None

    resource = package_root / filename
    if not resource.is_file():
        return None

    cache_dir = Path(tempfile.gettempdir()) / "agi_node_hooks"
    cache_dir.mkdir(exist_ok=True)
    cached = cache_dir / filename
    try:
        with importlib_resources.as_file(resource) as resource_path:
            if resource_path != cached:
                shutil.copy2(resource_path, cached)
    except FileNotFoundError:
        return None

    return cached if cached.exists() else None


def _select_hook(local_candidate: Path, fallback_filename: str, hook_label: str) -> tuple[Path, bool]:
    """Return the hook to execute and whether it comes from the shared baseline."""

    if local_candidate.exists():
        return local_candidate, False

    fallback = _resolve_worker_hook(fallback_filename)
    if fallback and fallback.exists():
        return fallback, True

    raise FileNotFoundError(
        f"Unable to resolve {hook_label} script: expected {local_candidate} or shared agi-node copy."
    )

# Compile regex once globally
LEVEL_RES = [
    # Optional leading time like "11:20:03 " or "11:20:03,123 "
    re.compile(r'^\s*(?:\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+)?(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b', re.IGNORECASE),
    # Bracketed level: "[ERROR] something"
    re.compile(r'^\s*\[\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\]\b', re.IGNORECASE),
    # Key/value style: "level=error ..."
    re.compile(r'\blevel\s*=\s*(debug|info|warning|error|critical)\b', re.IGNORECASE),
]
TIME_LEVEL_PREFIX = re.compile(
    r'^\s*(?:\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*[:-]?\s*',
    re.IGNORECASE,
)


def normalize_path(path):
    """Return ``path`` coerced to a normalised string representation.

    ``Path`` objects are converted to a string that matches the current platform
    conventions so the value can safely be stored in configuration files or
    environment variables.
    """

    return (
        str(PureWindowsPath(Path(path)))
        if os.name == "nt"
        else str(PurePosixPath(Path(path)))
    )


def parse_level(line, default_level):
    """Resolve a logging level token found in ``line``.

    Parameters
    ----------
    line:
        The text that might contain a logging level marker.
    default_level:
        The integer level returned when no explicit marker is present.

    Returns
    -------
    int
        The numeric logging level understood by :mod:`logging`.
    """

    for rx in LEVEL_RES:
        m = rx.search(line)
        if m:
            return getattr(logging, m.group(1).upper(), default_level)
    return default_level

def strip_time_level_prefix(line: str) -> str:
    """Remove a ``HH:MM:SS LEVEL`` prefix commonly emitted by log handlers."""

    return TIME_LEVEL_PREFIX.sub('', line, count=1)

def is_packaging_cmd(cmd: str) -> bool:
    """Return ``True`` when ``cmd`` appears to invoke ``uv`` or ``pip``."""

    s = cmd.strip()
    return s.startswith("uv ") or s.startswith("pip ") or "uv" in s or "pip" in s

class _AgiEnvMeta(type):
    """Delegate AgiEnv class attribute access to the singleton instance.

    This keeps existing call-sites that use ``AgiEnv.attr`` working while
    allowing the implementation to set values only on the instance. Methods
    and descriptors are never shadowed.
    """

    def __getattribute__(cls, name):  # type: ignore[override]
        # Core attributes always from the class
        if name in {"_instance", "_lock", "current", "reset", "__dict__", "__weakref__"}:
            return super().__getattribute__(name)

        # Try to get class attribute; remember if it exists even when value is None
        found_on_class = False
        try:
            obj = super().__getattribute__(name)
            found_on_class = True
            if (
                _inspect.isfunction(obj)
                or _inspect.ismethoddescriptor(obj)
                or isinstance(obj, (property, staticmethod, classmethod, type))
            ):
                return obj
        except AttributeError:
            obj = None

        # Prefer the instance attribute when available
        try:
            inst = super().__getattribute__("_instance")
        except AttributeError:
            inst = None
        if inst is not None and hasattr(inst, name):
            return getattr(inst, name)

        # Fall back to the class attribute (may be None)
        if found_on_class:
            return obj

        # Nothing found
        raise AttributeError(f"type object '{cls.__name__}' has no attribute '{name}'")

    def __setattr__(cls, name, value):  # type: ignore[override]
        if name in {"_instance", "_lock"} or (name.startswith("__") and name.endswith("__")):
            return super().__setattr__(name, value)
        # Always set callables/descriptors on the class itself to allow patching/overrides
        if (
            _inspect.isfunction(value)
            or _inspect.ismethoddescriptor(value)
            or isinstance(value, (property, staticmethod, classmethod, type))
        ):
            return super().__setattr__(name, value)
        inst = getattr(cls, "_instance", None)
        if inst is not None:
            setattr(inst, name, value)
        else:
            super().__setattr__(name, value)


class AgiEnv(metaclass=_AgiEnvMeta):
    """Encapsulates filesystem and configuration state for AGILab deployments.

    Singleton access
    ----------------
    - Repeated instantiation reuses the same instance. Use :func:`AgiEnv.reset`
      to drop it, or :func:`AgiEnv.current` to retrieve it.
    - Reading ``AgiEnv.attr`` proxies to the singleton's attribute when the
      instance exists; callables/properties are always returned from the class.
    """
    _instance: "AgiEnv | None" = None
    _lock: RLock = RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def current(cls) -> "AgiEnv":
        """Return the currently initialised environment instance."""

        if cls._instance is None:
            raise RuntimeError("AgiEnv has not been initialised yet")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the cached singleton so a fresh environment can be bootstrapped."""

        with cls._lock:
            cls._instance = None
    install_type = None  # deprecated: derived from flags for backward compatibility
    apps_dir = None
    app = None
    target = None
    TABLE_MAX_ROWS = None
    GUI_SAMPLING = None
    init_done = False
    hw_rapids_capable = None
    is_worker_env = False
    _is_managed_pc = None
    debug = False
    uv = None
    benchmark = None
    verbose = None
    pyvers_worker = None
    logger = None
    out_log = None
    err_log = None
    # Minimal class-level fallbacks to support limited static usage pre-init
    resources_path: Path | None = Path.home() / ".agilab"
    envars: dict | None = {}
    # Simplified environment flags
    is_source_env: bool = False
    is_local_worker: bool = False
    _ip_local_cache: set = set({"127.0.0.1", "::1"})
    INDEX_URL="https://test.pypi.org/simple"
    EXTRA_INDEX_URL="https://pypi.org/simple"
    snippet_tail = "asyncio.get_event_loop().run_until_complete(main())"
    _pythonpath_entries: list[str] = []

    def __init__(self,
                 apps_dir: Path | None = None,
                 app: str | None = None,
                 verbose: int | None = None,
                 debug: bool = False,
                 python_variante: str = '',
                 **kwargs):

        # Backward/forward compat: accept 'active_app' alias for 'app'
        if app is None and 'active_app' in kwargs:
            val = kwargs.pop('active_app')
            try:
                app = Path(val).name
            except Exception:
                app = str(val) if val is not None else None

        def _resolve_install_type(apps_dir: str | None,
                                  agilab_pck: Path,
                                  envars: dict | None) -> int:
            """Infer install type without requiring an explicit argument.

            Precedence:
            1. honour explicit overrides from environment variables (``AGILAB_INSTALL_TYPE``
               or ``INSTALL_TYPE``) when they are valid integers;
            2. when no ``apps_dir`` is provided, assume a worker-only environment (type 2);
            3. otherwise rely on the directory layout to distinguish source checkouts (type 1)
               from packaged installs (type 0), falling back to the legacy heuristic based on
               ``agilab_pck`` when needed.
            """
            try:
                # Heuristic: if apps_dir is not provided (BaseWorker.new) or it resides inside a worker env folder (wenv/*_worker),
                # treat this as a worker-only environment regardless of source/layout markers.
                if apps_dir is None or "wenv" in set(apps_dir.resolve().parts):
                    self.is_worker_env = True
                    return 2

                elif apps_dir.parents[1].name == "src":
                    return 1

            except Exception:
                pass

            return 0

        def _package_dir(package: str) -> Path:
            try:
                spec = importlib.util.find_spec(package)
            except (ModuleNotFoundError, ValueError):
                spec = None

            if spec:
                search_locations = getattr(spec, "submodule_search_locations", None)
                if search_locations:
                    for location in search_locations:
                        if location:
                            path = Path(location)
                            if path.exists():
                                return path.resolve()

                origin = getattr(spec, "origin", None)
                if origin:
                    path = Path(origin).parent
                    if path.exists():
                        return path.resolve()

            raise ModuleNotFoundError(
                f"Package '{package}' is not installed in the current environment."
            )

        self.is_managed_pc = getpass.getuser().startswith("T0")
        self._is_managed_pc = self.is_managed_pc
        self._agi_resources = Path("resources/.agilab")
        home_abs = Path.home() / "MyApp" if self.is_managed_pc else Path.home()
        self.home_abs = home_abs

        if verbose is None:
            verbose = 0
        self.uv = "uv"
        if verbose < 3:
            self.uv = "uv --quiet"
        elif verbose >= 3:
            self.uv = "uv --verbose"
        
        self.resources_path = home_abs / self._agi_resources.name
        env_path = self.resources_path / ".env"
        self.benchmark = self.resources_path / "benchmark.json"
        self.envars = dotenv_values(dotenv_path=env_path, verbose=verbose)
        envars = self.envars
        repo_agilab_dir = Path(__file__).resolve().parents[4]

        agilab_spec = importlib.util.find_spec("agilab")
        if agilab_spec and getattr(agilab_spec, "origin", None):
            agilab_pkg_dir = Path(agilab_spec.origin).resolve().parent
        else:
            agilab_pkg_dir = repo_agilab_dir
        agilab_pkg_dir = agilab_pkg_dir.resolve()
        agilab_pck = agilab_pkg_dir.parent.resolve()
        markers = {"site-packages", "dist-packages"}
        is_agilab_installed = any(part in markers for part in agilab_pkg_dir.parts) or any(
            part.startswith(".venv") for part in agilab_pkg_dir.parts
        )

        if apps_dir is not None:
            apps_dir = Path(apps_dir).expanduser()
            try:
                apps_dir = apps_dir.resolve()
            except FileNotFoundError:
                pass

        install_type = _resolve_install_type(apps_dir, agilab_pck, self.envars)

        # Default apps_dir for non-worker envs when not provided
        if not self.is_worker_env and apps_dir is None:
            try:
                apps_dir = (agilab_pck / "apps").resolve()
            except Exception:
                apps_dir = agilab_pck / "apps"

        if self.is_worker_env:
            if not app:
                raise ValueError("app is required when self.is_worker_env")
            active_app = home_abs / "wenv" / app
        else:
            if app is None:
                app = envars.get("APP_DEFAULT", 'flight_project')
            base_dir = apps_dir if apps_dir is not None else Path()
            try:
                base_dir = base_dir.resolve()
            except Exception:
                pass
            active_app = base_dir / app

        if not app.endswith('_project') and not app.endswith('_worker'):
            raise ValueError(f"{app} must end with '_project' or '_worker'")

        self.app = app
        try:
            self.active_app = active_app.resolve()
        except Exception:
            self.active_app = active_app
        self.apps_dir = apps_dir

        target = app.replace("_project", "").replace("_worker","").replace("-", "_")

        self.verbose = verbose
        self.python_variante = python_variante
        self.logger = AgiLogger.configure(verbose=verbose, base_name="agi_env")
        self.debug = debug

        # Simplified environment flags
        self.is_source_env = not is_agilab_installed
        self.is_local_worker = False
        # Backward-compat: map booleans to legacy install_type
        self.install_type = 1 if self.is_source_env else (2 if self.is_worker_env else 0)

        if self.is_source_env:
            pkg_dirs = {
                "env": "agi-env/src/agi_env",
                "node": "agi-node/src/agi_node",
                "core": "agi-core/src/agi_core",
                "cluster": "agi-cluster/src/agi_cluster",
            }
            # Force source layout to the repo checkout when available
            self.agilab_pck = repo_agilab_dir
            core_root = self.agilab_pck / "core"
            self.env_pck = core_root / pkg_dirs["env"]
            self.node_pck = core_root / pkg_dirs["node"]
            self.core_pck = core_root / pkg_dirs["core"]
            self.cluster_pck = core_root / pkg_dirs["cluster"]
            self.cli = self.cluster_pck / "agi_distributor/cli.py"
        else:
            self.agilab_pck = agilab_pkg_dir
            self.env_pck = _package_dir("agi_env")
            self.node_pck = _package_dir("agi_node")
            try:
                self.core_pck = _package_dir("agi_core")
            except ModuleNotFoundError:
                self.core_pck = Path(_package_dir("agi_env")).parent
            try:
                self.cluster_pck = _package_dir("agi_cluster")
            except ModuleNotFoundError:
                # In minimal worker environments, agi_cluster may be absent; fall back near env/core
                self.cluster_pck = self.core_pck
            try:
                cli_spec = importlib.util.find_spec("agi_cluster.agi_distributor.cli")
            except ModuleNotFoundError:
                cli_spec = None
            self.cli = Path(cli_spec.origin) if cli_spec and getattr(cli_spec, "origin", None) else self.cluster_pck / "agi_distributor/cli.py"

        resolve = self._resolve_package
        self.env_pck = resolve(self.env_pck)
        self.node_pck = resolve(self.node_pck)
        self.core_pck = resolve(self.core_pck)
        self.cluster_pck = resolve(self.cluster_pck)
        self.agi_env = self.env_pck.parents[1]
        self.agi_node = self.node_pck.parents[1]
        self.agi_core = self.core_pck.parents[1]
        self.agi_cluster = self.cluster_pck.parents[1]

        if self.is_source_env:
            resource_candidates = [
                self.agilab_pck / "resources",
                self.agilab_pck / "agilab/resources",
            ]
        else:
            resource_candidates = [
                self.agilab_pck / "resources",
                self.agilab_pck / "agilab/resources",
            ]
        for candidate in resource_candidates:
            if candidate.exists():
                self.st_resources = candidate
                break
        else:
            self.st_resources = resource_candidates[-1]

        apps_root = self.agilab_pck / "apps"
        if (not self.is_source_env) and (not self.is_worker_env):
            os.makedirs(apps_dir, exist_ok=True)

            link_source = self._get_private_apps_root()
            if link_source is None:
                agilab_path = self.read_agilab_path()
                if agilab_path:
                    candidate = agilab_path / "apps"
                    if candidate.exists():
                        link_source = candidate

            if link_source is not None and link_source.exists():
                for src_app in link_source.glob("*_project"):
                    dest_app = apps_dir / src_app.relative_to(link_source)
                    # Avoid creating self-referential symlinks when the public
                    # destination already resides inside the private tree.
                    if dest_app.resolve(strict=False) == src_app.resolve():
                        AgiEnv.logger.info(
                            f"Skipping symlink for app {src_app} because destination matches source"
                        )
                        continue
                    try:
                        if dest_app.is_symlink():
                            same_target = False
                            if dest_app.exists():
                                try:
                                    same_target = dest_app.resolve() == src_app.resolve()
                                except OSError:
                                    same_target = False
                            if same_target:
                                continue
                            dest_app.unlink()
                        elif dest_app.exists():
                            shutil.rmtree(dest_app)
                    except FileNotFoundError:
                        pass

                    if os.name == "nt":
                        AgiEnv.create_symlink_windows(Path(src_app), dest_app)
                    else:
                        os.symlink(src_app, dest_app, target_is_directory=True)
                    AgiEnv.logger.info(f"Created symbolic link for app: {src_app} -> {dest_app}")
            elif apps_root.exists():
                self.copy_existing_projects(apps_root, active_app.parent)
            else:
                AgiEnv.logger.info(f"Warning: {apps_root} does not exist, nothing to copy!")

            if not active_app.exists() and apps_root.exists():
                packaged_app = apps_root / app
                if packaged_app.exists():
                    try:
                        shutil.copytree(
                            packaged_app,
                            active_app,
                            dirs_exist_ok=True
                        )
                        AgiEnv.logger.info(
                            "Copied packaged app %s into %s", packaged_app, active_app
                        )
                    except Exception as exc:
                        AgiEnv.logger.warning(
                            f"Failed to copy packaged app {packaged_app}: {exc}"
                        )
                else:
                    AgiEnv.logger.info(
                        "Private apps root missing %s; copying packaged examples instead",
                        app,
                    )
                    self.copy_existing_projects(apps_root, apps_dir)


        resources_root = self.env_pck if self.is_source_env else ""
        if not self.is_worker_env:
            self._init_resources(resources_root / self._agi_resources)
        self.TABLE_MAX_ROWS = int(envars.get("TABLE_MAX_ROWS", 1000))
        self.GUI_SAMPLING = int(envars.get("GUI_SAMPLING", 20))

        self.target = target
        wenv_root = Path("wenv")
        target_worker = f"{target}_worker"
        self.target_worker = target_worker
        wenv_rel = wenv_root / target_worker
        target_class = "".join(x.title() for x in target.split("_"))
        self.target_class = target_class
        worker_class = target_class + "Worker"
        self.target_worker_class = worker_class

        self.wenv_rel = wenv_rel
        self.dist_rel = wenv_rel / 'dist'
        wenv_abs = home_abs / wenv_rel
        self.wenv_abs = wenv_abs
        os.makedirs(self.wenv_abs, exist_ok=True)

        self.pre_install =  self.node_pck / "agi_dispatcher/pre_install.py"
        self.post_install = self.node_pck / "agi_dispatcher/post_install.py"
        self.post_install_rel =   "agi_node.agi_dispatcher.post_install"

        dist_abs = wenv_abs / 'dist'
        dist = normalize_path(dist_abs)
        if not dist in sys.path:
            sys.path.append(dist)
        self.dist_abs = dist_abs
        self.app_src = self.active_app / "src"
        self.manager_pyproject = self.active_app / "pyproject.toml"
        self.worker_path = self.app_src / target_worker / f"{target_worker}.py"
        self.manager_path = self.app_src / target / f"{target}.py"
        is_local_worker = self.has_agilab_anywhere_under_home(self.agilab_pck)
        worker_src = self.wenv_rel / 'src'

        if self.is_worker_env and not is_local_worker:
            app = self.agilab_pck
            self.app_src = self.agilab_pck / "src"
            self.worker_path = worker_src / target_worker / f"{target_worker}.py"

            self.manager_path = worker_src / target / f"{target}.py"

        self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
        self.uvproject = self.active_app / "uv_config.toml"
        self.dataset_archive = self.worker_path.parent / "dataset.7z"

        src_path = normalize_path(self.app_src)
        if not src_path in sys.path:
            sys.path.append(src_path)

        if not self.worker_path.exists():
            copied_packaged_worker = False
            if self._ensure_private_app_link():
                self.app_src = self.active_app / "src"
                self.worker_path = self.app_src / target_worker / f"{target_worker}.py"
                self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
                self.dataset_archive = self.worker_path.parent / "dataset.7z"
            else:
                packaged_app = self.agilab_pck / "apps" / self.app
                if not self.is_worker_env and packaged_app.exists():
                    try:
                        shutil.copytree(
                            packaged_app,
                            self.active_app,
                            dirs_exist_ok=True,
                        )
                        copied_packaged_worker = True
                        AgiEnv.logger.info(
                            "Copied packaged app %s into %s", packaged_app, self.active_app
                        )
                    except Exception as exc:
                        AgiEnv.logger.warning(
                            f"Unable to copy packaged worker app from {packaged_app} to {self.app}: {exc}"
                        )
                elif not self.is_worker_env and apps_root.exists():
                    self.copy_existing_projects(apps_root, app.parent)

                if (
                    not self.is_worker_env
                    and not self.worker_path.exists()
                    and apps_root.exists()
                    and self.app.endswith("_worker")
                ):
                    project_name = self.app.replace("_worker", "_project")
                    project_worker_dir = apps_root / project_name / "src" / self.app
                    if project_worker_dir.exists():
                        dest_worker_dir = self.active_app / "src" / self.app
                        try:
                            shutil.copytree(
                                project_worker_dir,
                                dest_worker_dir,
                                dirs_exist_ok=True,
                            )
                            AgiEnv.logger.info(
                                "Copied project worker sources %s into %s",
                                project_worker_dir,
                                dest_worker_dir,
                            )
                        except Exception as exc:
                            AgiEnv.logger.warning(
                                f"Failed to copy worker sources from {project_worker_dir}: {exc}"
                            )
                        else:
                            copied_packaged_worker = True

                if copied_packaged_worker:
                    self.app_src =self.active_app / "src"
                    self.worker_path = self.app_src / target_worker / f"{target_worker}.py"
                    self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
                    self.dataset_archive = self.worker_path.parent / "dataset.7z"
                #elif self.is_worker_env:
                #    AgiEnv.logger.info(
                #        "Worker sources not found (is_worker_env=True) at %s", self.worker_path
                #    )

        self.apps_dir = apps_dir
        distribution_tree = self.wenv_abs / "distribution_tree.json"
        if distribution_tree.exists():
            distribution_tree.unlink()
        self.distribution_tree = distribution_tree

        pythonpath_entries = self._collect_pythonpath_entries()
        self._configure_pythonpath(pythonpath_entries)

        self.python_version = envars.get("AGI_PYTHON_VERSION", "3.13")

        self.pyvers_worker = self.python_version
        self.is_free_threading_available = envars.get("AGI_PYTHON_FREE_THREADED", 0)
        # Avoid stray stdout; rely on logger when needed
        if self.worker_pyproject.exists():
            with open(self.worker_pyproject, "r") as f:
                data = tomlkit.parse(f.read())
            try:
                use_freethread = data["tool"]["freethread_info"]["is_app_freethreaded"]
                if use_freethread and self.is_free_threading_available:
                    self.uv_worker = "PYTHON_GIL=0 " + self.uv
                    self.pyvers_worker = self.pyvers_worker + "t"
                else:
                    self.uv_worker = self.uv
            except KeyError as e:
                use_freethread = False
                self.uv_worker = self.uv
        else:
            self.uv_worker = self.uv
            use_freethread = False

        if self.is_worker_env:
            return

        if self.worker_path.exists():
            self.base_worker_cls, self._base_worker_module = self.get_base_worker_cls(
                self.worker_path, worker_class
            )
        else:
            self.base_worker_cls, self._base_worker_module = (None, None)
            # In packaged end‑user environments, worker sources may be absent by design.
            # Proceed without exiting; the installer will materialize required files under wenv.
            if (not self.is_source_env) and (not self.is_worker_env):
                AgiEnv.logger.debug(
                    f"Missing {self.target_worker_class} definition; expected {self.worker_path} (packaged end-user env)"
                )
            else:
                AgiEnv.logger.info(
                    f"Missing {self.target_worker_class} definition; expected {self.worker_path}"
                )

        envars = self.envars
        raw_credentials = envars.get("CLUSTER_CREDENTIALS", getpass.getuser())
        credentials_parts = raw_credentials.split(":")
        self.user = credentials_parts[0]
        self.password = credentials_parts[1] if len(credentials_parts) > 1 else None

        self.projects = self.get_projects(self.apps_dir)
        if not self.projects:
            AgiEnv.logger.info(f"Could not find any target project app in {self.agilab_pck / 'apps'}.")

        self.setup_app = self.active_app / "build.py"
        self.setup_app_module = "agi_node.agi_dispatcher.build"

        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", "data"))
        data_rel = self.AGILAB_SHARE / self.target
        self.dataframe_path = data_rel / "dataframe"
        self.data_rel = data_rel
        self._init_projects()

        self.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
        if not self.is_valid_ip(self.scheduler_ip):
            raise ValueError(f"Invalid scheduler IP address: {self.scheduler_ip}")

        if self.is_source_env:
            self.help_path = str(self.agilab_pck / "../docs/html")
        else:
            self.help_path = "https://thalesgroup.github.io/agilab"
        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", home_abs / "data"))

        self.app_src.mkdir(parents=True, exist_ok=True)
        app_src_str = str(self.app_src)
        if app_src_str not in sys.path:
            sys.path.append(app_src_str)

        # Populate examples/apps in standard environments
        if True:
            examples_candidates = [
                self.agilab_pck / "agilab/examples",
                self.agilab_pck / "examples",
            ]
            for candidate in examples_candidates:
                if candidate.exists():
                    self.examples = candidate
                    break
            else:
                self.examples = examples_candidates[-1]
            # examples path available via singleton delegation if accessed as AgiEnv.examples
            self.init_envars_app(self.envars)
            self._init_apps()

        if os.name == "nt":
            self.export_local_bin = ""
        else:
            self.export_local_bin = 'export PATH="~/.local/bin:$PATH";'
        # export_local_bin available via singleton delegation if accessed as AgiEnv.export_local_bin


    @staticmethod
    def _resolve_package(root: Path) -> Path:
        """Return the ``src`` directory for a package when present.

        Many AGILab components follow the ``src/`` layout; when that folder is
        missing the package root itself is returned.
        """

        src_dir = root / "src" / root.name.replace("-", "_")
        return src_dir if src_dir.exists() else root

    def _get_private_apps_root(self) -> Path | None:
        """Return the private apps directory when ``AGILAB_PRIVATE`` is configured."""

        private_root = self.envars.get("AGILAB_PRIVATE")
        if not private_root:
            return None

        candidate = Path(private_root).expanduser() / "src/agilab/apps"
        if candidate.exists():
            return candidate

        AgiEnv.logger.info(
            f"AGILAB_PRIVATE is set but apps directory is missing: {candidate}"
        )
        return None

    def _collect_pythonpath_entries(self) -> list[str]:
        """Build an ordered list of paths that must live on ``PYTHONPATH``."""

        def import_root(path: Path) -> Path:
            """Return the directory that must be added to ``PYTHONPATH`` for ``path``."""

            try:
                init_file = path / "__init__.py"
            except TypeError:
                return path

            if init_file.exists():
                return path.parent
            return path

        candidates = [
            import_root(self.env_pck.parent),
            import_root(self.node_pck.parent),
            import_root(self.core_pck.parent),
            import_root(self.cluster_pck.parent),
            self.dist_abs,
            self.app_src,
            self.wenv_abs / "src",
            self.agilab_pck / "agilab",
        ]
        return self._dedupe_paths(candidates)

    def _configure_pythonpath(self, entries: list[str]) -> None:
        """Inject ``entries`` into both ``sys.path`` and the ``PYTHONPATH`` env var."""

        self._pythonpath_entries = entries
        if not entries:
            return
        for entry in entries:
            if entry not in sys.path:
                sys.path.append(entry)
        current = os.environ.get("PYTHONPATH", "")
        combined = entries.copy()
        if current:
            for part in current.split(os.pathsep):
                if part and part not in combined:
                    combined.append(part)
        os.environ["PYTHONPATH"] = os.pathsep.join(combined)

    @staticmethod
    def _dedupe_paths(paths) -> list[str]:
        """Collapse ``paths`` into a list of unique, existing filesystem entries."""

        seen: set[str] = set()
        result: list[str] = []
        for path in paths:
            if not path:
                continue
            path_str = str(path)
            if not path_str:
                continue
            if not Path(path_str).exists():
                continue
            if path_str in seen:
                continue
            seen.add(path_str)
            result.append(path_str)
        return result

    def has_agilab_anywhere_under_home(self, path: Path) -> bool:
        """Return ``True`` when ``path`` sits under the user's home ``agilab`` tree."""

        try:
            rel = path.resolve().relative_to(Path.home())
        except ValueError:
            return False  # pas sous ~
        return "agilab" in rel.parts

    def active(self, target):
        """Switch :attr:`app` to ``target`` if it differs from the current one."""

        if str(self.app) != target:
            self.change_app(target)

    def humanize_validation_errors(self, error):
        """Format pydantic-style validation ``error`` messages for human consumption."""

        formatted_errors = []
        for err in error.errors():
            field = ".".join(str(loc) for loc in err["loc"])
            message = err["msg"]
            error_type = err.get("type", "unknown_error")
            input_value = err.get("ctx", {}).get("input_value", None)
            user_message = f"❌ **{field}**: {message}"
            if input_value is not None:
                user_message += f" (Received: `{input_value}`)"
            user_message += f"*Error Type:* `{error_type}`"
            formatted_errors.append(user_message)
        return formatted_errors

    @staticmethod
    def set_env_var(key: str, value: str):
        """Persist ``key``/``value`` in :attr:`envars`, ``os.environ`` and the ``.env`` file."""
        AgiEnv._ensure_defaults()
        AgiEnv.envars[key] = value
        os.environ[key] = str(value)
        AgiEnv._update_env_file({key: value})

    @classmethod
    def _ensure_defaults(cls):
        """Ensure minimal class-level defaults exist for limited static usage."""
        if getattr(cls, "resources_path", None) is None:
            try:
                cls.resources_path = Path.home() / ".agilab"
            except Exception:
                cls.resources_path = Path(".agilab").resolve()
        if getattr(cls, "envars", None) is None or not isinstance(cls.envars, dict):
            try:
                env_path = cls.resources_path / ".env"
                cls.envars = dict(dotenv_values(dotenv_path=env_path, verbose=False))
            except Exception:
                cls.envars = {}

    @staticmethod
    def read_agilab_path(verbose=False):
        """Return the persisted AGILab installation path if previously recorded."""

        if os.name == "nt":
            where_is_agi = Path(os.getenv("LOCALAPPDATA", "")) / "agilab/.agilab-path"
        else:
            where_is_agi = Path.home() / ".local/share/agilab/.agilab-path"

        if where_is_agi.exists():
            try:
                with where_is_agi.open("r", encoding="utf-8-sig") as f:
                    install_path = f.read().strip()
                    agilab_path = Path(install_path)
                    if install_path and agilab_path.exists():
                        return agilab_path
                    else:
                        raise ValueError("Installation path file is empty or invalid.")
            except FileNotFoundError:
                logger = getattr(AgiEnv, "logger", None)
                if logger:
                    logger.error(f"File {where_is_agi} does not exist.")
            except PermissionError:
                logger = getattr(AgiEnv, "logger", None)
                if logger:
                    logger.error(f"Permission denied when accessing {where_is_agi}.")
            except Exception as e:
                logger = getattr(AgiEnv, "logger", None)
                if logger:
                    logger.error(f"An error occurred: {e}")
        else:
            return False

    @staticmethod
    def locate_agilab_installation(verbose=False):
        """Attempt to locate the installed AGILab package path on disk."""

        base_dir: Path | None = None

        for p in sys.path_importer_cache:
            if isinstance(p, str) and p.endswith("agi_env"):
                base_dir = Path(p)

        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[2] / "agi_env"

        before, sep, _ = str(base_dir).rpartition("agilab")
        candidate_repo = Path(before) / sep if sep else base_dir.parent
        if (candidate_repo / "apps").exists():
            return candidate_repo
        return base_dir.parent

    def copy_existing_projects(self, src_apps: Path, dst_apps: Path):
        """Copy ``*_project`` trees from ``src_apps`` into ``dst_apps`` if missing."""

        dst_apps.mkdir(parents=True, exist_ok=True)

        AgiEnv.logger.info(f"copy_existing_projects src={src_apps.resolve()} dst={dst_apps.resolve()}")
        candidates = [p for p in src_apps.rglob("*_project") if p.is_dir()]
        AgiEnv.logger.info(
            "Matched projects: " + ", ".join(str(p.relative_to(src_apps)) for p in candidates) or "<none>")

        # match every nested directory ending with "_project"
        for item in src_apps.rglob("*_project"):
            if not item.is_dir():
                continue

            rel = item.relative_to(src_apps)  # keep nested structure
            dst_item = dst_apps / rel
            if dst_item.is_symlink():
                try:
                    dst_item.unlink()
                except OSError as exc:
                    AgiEnv.logger.warning(
                        f"Failed to remove dangling project symlink {dst_item}: {exc}"
                    )
                    continue
            elif dst_item.exists() and not dst_item.is_dir():
                try:
                    dst_item.unlink()
                except OSError as exc:
                    AgiEnv.logger.warning(
                        f"Failed to remove conflicting project file {dst_item}: {exc}"
                    )
                    continue
            try:
                shutil.copytree(
                    item,
                    dst_item,
                    dirs_exist_ok=True,  # merge into existing tree
                    symlinks=True,  # keep symlinks as symlinks
                    ignore=shutil.ignore_patterns(  # skip bulky/ephemeral stuff
                        ".venv", "build", "dist", "__pycache__", ".pytest_cache",
                        ".idea", ".mypy_cache", ".ruff_cache", "*.egg-info"
                    ),
                )
            except Exception as e:
                AgiEnv.logger.error(f"Warning: Could not copy {item} → {dst_item}: {e}")

    # Simplified: keep single copy_missing implementation defined later using _copy_file

    def _update_env_file(updates: dict):
        AgiEnv._ensure_defaults()
        env_file = AgiEnv.resources_path / ".env"
        # Ensure parent directory exists for pre-init usage
        try:
            env_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        for k, v in updates.items():
            set_key(str(env_file), k, str(v), quote_mode="never")

    def _init_resources(self, resources_src):
        """Replicate ``resources_src`` into the managed ``.agilab`` tree."""

        src_env_path = resources_src / ".env"
        dest_env_file = self.resources_path / ".env"
        if not dest_env_file.exists():
            os.makedirs(dest_env_file.parent, exist_ok=True)
            shutil.copy(src_env_path, dest_env_file)
        for root, dirs, files in os.walk(resources_src):
            for file in files:
                src_file = Path(root) / file
                relative_path = src_file.relative_to(resources_src)
                dest_file = self.resources_path / relative_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if not dest_file.exists():
                    shutil.copy(src_file, dest_file)

        # Ensure UI assets required by Streamlit editors are present.
        extras = [
            "custom_buttons.json",
            "info_bar.json",
            "code_editor.scss",
        ]

        if not self.is_source_env:
            for extra in extras:
                src_extra = self.st_resources / extra
                dest_extra = self.resources_path / extra
                if src_extra.exists() and not dest_extra.exists():
                    dest_extra.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(src_extra, dest_extra)
        else:
            for extra in extras:
                dest_extra = self.resources_path / extra
                try:
                    if dest_extra.exists():
                        dest_extra.unlink()
                except OSError:
                    AgiEnv.logger.warning(f"Could not remove legacy resource {dest_extra}")

    def _init_projects(self):
        """Identify available projects and align state with the selected target."""

        self.projects = self.get_projects(self.apps_dir)
        for idx, project in enumerate(self.projects):
            if self.target == project[:-8].replace("-", "_"):
                self.app = self.apps_dir / project
                self.app = project
                break

    def get_projects(self, path: Path):
        """Return the names of ``*_project`` directories beneath ``path``."""

        if not path.exists():
            return []

        projects: list[str] = []
        for project_path in path.glob("*project"):
            if project_path.is_symlink() and not project_path.exists():
                try:
                    project_path.unlink()
                    AgiEnv.logger.info(
                        f"Removed dangling project symlink: {project_path}"
                    )
                except OSError as exc:
                    AgiEnv.logger.warning(
                        f"Failed to remove dangling project symlink {project_path}: {exc}"
                    )
                continue

            if project_path.is_dir():
                projects.append(project_path.name)

        return projects

    def get_base_worker_cls(self, module_path, class_name):
        """Return the base worker class name and module for ``class_name``."""

        base_info_list = self.get_base_classes(module_path, class_name)
        try:
            base_class, module_name = next((base, mod) for base, mod in base_info_list if base.endswith("Worker"))
            return base_class, module_name
        except StopIteration:
            return None, None

    def get_base_classes(self, module_path, class_name):
        """Inspect ``module_path`` AST to retrieve base classes of ``class_name``."""

        try:
            with open(module_path, "r", encoding="utf-8") as file:
                source = file.read()
        except (IOError, FileNotFoundError) as e:
            AgiEnv.logger.error(f"Error reading module file {module_path}: {e}")
            return []

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            AgiEnv.logger.error(f"Syntax error parsing {module_path}: {e}")
            raise RuntimeError(f"Syntax error parsing {module_path}: {e}")

        import_mapping = self.get_import_mapping(source)
        base_classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for base in node.bases:
                    base_info = self.extract_base_info(base, import_mapping)
                    if base_info:
                        base_classes.append(base_info)
                break
        return base_classes

    def get_import_mapping(self, source):
        """Build a mapping of names to modules from ``import`` statements in ``source``."""

        mapping = {}
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            AgiEnv.logger.error(f"Syntax error during import mapping: {e}")
            raise
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mapping[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                for alias in node.names:
                    mapping[alias.asname or alias.name] = module
        return mapping

    def _ensure_private_app_link(self) -> bool:
        """Create a symlink to a private app when the public tree is missing it."""

        link_root = self._get_private_apps_root()
        if not link_root:
            return False

        candidate = link_root / self.app
        if not candidate.exists():
            return False

        dest = self.active_app
        if dest.exists():
            if dest.is_symlink():
                dest.unlink()
            else:
                return False

        dest.symlink_to(candidate, target_is_directory=True)
        AgiEnv.logger.info("Created private app symlink: %s -> %s", dest, candidate)
        return True

    def extract_base_info(self, base, import_mapping):
        """Return the base-class name and originating module for ``base`` nodes."""

        if isinstance(base, ast.Name):
            module_name = import_mapping.get(base.id)
            return base.id, module_name
        elif isinstance(base, ast.Attribute):
            full_name = self.get_full_attribute_name(base)
            parts = full_name.split(".")
            if len(parts) > 1:
                alias = parts[0]
                module_name = import_mapping.get(alias, alias)
                return parts[-1], module_name
            return base.attr, None
        return None

    def get_full_attribute_name(self, node):
        """Reconstruct the dotted attribute path represented by ``node``."""

        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self.get_full_attribute_name(node.value) + "." + node.attr
        return ""

    def mode2str(self, mode):
        """Encode a bitmask ``mode`` into readable ``pcdr`` flag form."""

        chars = ["p", "c", "d", "r"]
        reversed_chars = reversed(list(enumerate(chars)))

        if self.hw_rapids_capable:
            mode += 8
        mode_str = "".join(
            "_" if (mode & (1 << i)) == 0 else v for i, v in reversed_chars
        )
        return mode_str

    @staticmethod
    def mode2int(mode):
        """Convert an iterable of mode flags (``p``, ``c``, ``d``) to the bitmask int."""

        mode_int = 0
        set_rm = set(mode)
        for i, v in enumerate(["p", "c", "d"]):
            if v in set_rm:
                mode_int += 2 ** (len(["p", "c", "d"]) - 1 - i)
        return mode_int

    def is_valid_ip(self, ip: str) -> bool:
        """Return ``True`` when ``ip`` is a syntactically valid IPv4 address."""

        pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        if pattern.match(ip):
            parts = ip.split(".")
            return all(0 <= int(part) <= 255 for part in parts)
        return False

    def init_envars_app(self, envars):
        """Cache frequently used environment variables and ensure directories exist."""

        self.CLUSTER_CREDENTIALS = envars.get("CLUSTER_CREDENTIALS", None)
        self.OPENAI_API_KEY = envars.get("OPENAI_API_KEY", None)
        AGILAB_LOG_ABS = Path(envars.get("AGI_LOG_DIR", self.home_abs / "log"))
        if not AGILAB_LOG_ABS.exists():
            AGILAB_LOG_ABS.mkdir(parents=True)
        self.AGILAB_LOG_ABS = AGILAB_LOG_ABS
        self.runenv = self.examples / self.target
        AGILAB_EXPORT_ABS = Path(envars.get("AGI_EXPORT_DIR", self.home_abs / "export"))
        if not AGILAB_EXPORT_ABS.exists():
            AGILAB_EXPORT_ABS.mkdir(parents=True)
        self.AGILAB_EXPORT_ABS = AGILAB_EXPORT_ABS
        self.export_apps = AGILAB_EXPORT_ABS / "apps"
        if not self.export_apps.exists():
            os.makedirs(str(self.export_apps), exist_ok=True)
        self.MLFLOW_TRACKING_DIR = Path(envars.get("MLFLOW_TRACKING_DIR", self.home_abs / ".mlflow"))
        pages_override = envars.get("AGI_PAGES_DIR")
        if pages_override:
            pages_root = Path(pages_override).expanduser()
        else:
            candidates = [self.agilab_pck / "agilab/apps-pages",
                          self.agilab_pck / "apps-pages"]
            repo_hint = self.read_agilab_path()
            if repo_hint:
                repo_hint = Path(repo_hint)
                for suffix in ("apps-pages", "agilab/apps-pages"):
                    candidates.append(repo_hint / suffix)

            pages_root = next((c.resolve() for c in candidates if c and c.exists()), candidates[0])

        self.AGILAB_PAGES_ABS = pages_root
        if not self.AGILAB_PAGES_ABS.exists():
            AgiEnv.logger.info(f"AGILAB_PAGES_ABS missing: {self.AGILAB_PAGES_ABS}")
        self.copilot_file = self.agilab_pck / "agi_codex.py"


    @staticmethod
    def _copy_file(src_item, dst_item):
        """Copy ``src_item`` to ``dst_item`` if the destination does not exist."""

        if not dst_item.exists():
            if not src_item.exists():
                logger = getattr(AgiEnv, "logger", None)
                if logger:
                    logger.info(f"[WARN] Source file missing (skipped): {src_item}")
                return
            try:
                shutil.copy2(src_item, dst_item)
            except Exception as e:
                logger = getattr(AgiEnv, "logger", None)
                if logger:
                    logger.error(f"[WARN] Could not copy {src_item} → {dst_item}: {e}")

    # def copy_missing(self, src: Path, dst: Path, max_workers=8):
    #     dst.mkdir(parents=True, exist_ok=True)
    #     to_copy = []
    #     dirs = []
    #
    #     for item in src.iterdir():
    #         src_item = item
    #         dst_item = dst / item.name
    #         if src_item.is_dir():
    #             dirs.append((src_item, dst_item))
    #         else:
    #             to_copy.append((src_item, dst_item))
    #
    #     # Parallel file copy
    #     with ThreadPoolExecutor(max_workers=max_workers) as executor:
    #         list(executor.map(lambda args: AgiEnv._copy_file(*args), to_copy))
    #
    #     # Recurse into directories
    #     for src_dir, dst_dir in dirs:
    #         self.copy_missing(src_dir, dst_dir, max_workers=max_workers)


    def _init_apps(self):
        app_settings_file = self.app_src / "app_settings.toml"
        app_settings_file.touch(exist_ok=True)
        self.app_settings_file = app_settings_file

        app_args_form = self.app_src / "app_args_form.py"
        app_args_form.touch(exist_ok=True)
        self.app_args_form = app_args_form

        self.gitignore_file = self.active_app / ".gitignore"
        dest = self.resources_path
        src = self.agilab_pck / "resources"
        if src.exists():
            for file in src.iterdir():
                if not file.is_file():
                    continue
                dest_file = dest / file.name
                if dest_file.exists():
                    continue
                shutil.copy2(file, dest_file)
        # shutil.copytree(self.agilab_pck / "resources", dest, dirs_exist_ok=True)


    @staticmethod
    def _build_env(venv=None):
        """Build environment dict for subprocesses, with activated virtualenv paths."""
        proc_env = os.environ.copy()
        venv_path = None
        if venv is not None:
            venv_path = Path(venv)
            if not (venv_path / "bin").exists() and venv_path.name != ".venv":
                venv_path = venv_path / ".venv"
            proc_env["VIRTUAL_ENV"] = str(venv_path)
            bin_path = "Scripts" if os.name == "nt" else "bin"
            venv_bin = venv_path / bin_path
            proc_env["PATH"] = str(venv_bin) + os.pathsep + proc_env.get("PATH", "")

        instance = AgiEnv._instance
        if instance is not None and getattr(instance, "_pythonpath_entries", None):
            extra_paths = list(instance._pythonpath_entries)
        else:
            extra_paths = list(AgiEnv._pythonpath_entries)
        if venv_path and Path(sys.prefix).resolve() != venv_path.resolve():
            tree_root = Path(sys.prefix).resolve()
            filtered: list[str] = []
            for entry in extra_paths:
                if not entry:
                    continue
                try:
                    resolved = Path(entry).resolve()
                except Exception:
                    filtered.append(entry)
                    continue
                if tree_root in resolved.parents or resolved == tree_root:
                    continue
                filtered.append(str(resolved))
            extra_paths = filtered
        proc_env.pop("PYTHONPATH", None)
        proc_env.pop("PYTHONHOME", None)
        if extra_paths:
            current = proc_env.get("PYTHONPATH", "")
            if current:
                for part in current.split(os.pathsep):
                    if part and part not in extra_paths:
                        extra_paths.append(part)
            proc_env["PYTHONPATH"] = os.pathsep.join(extra_paths)
        return proc_env

    @staticmethod
    def log_info(line: str) -> None:
        """Lightweight info logger retained for legacy hooks (e.g. pre_install scripts)."""

        if not isinstance(line, str):
            line = str(line)
        if AgiEnv.logger:
            AgiEnv.logger.info(line)
        else:
            print(line)

    @staticmethod
    async def run(cmd, venv, cwd=None, timeout=None, wait=True, log_callback=None):
        """
        Run a shell command inside a virtual environment.
        Streams stdout/stderr live without blocking (Windows-safe).
        Returns the full stdout string.
        """
        if (AgiEnv.verbose or 0) > 0:
            try:
                vname = Path(venv).name if venv is not None else "<venv>"
            except Exception:
                vname = str(venv)
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.info(f"@{vname}: {cmd}")

        if not cwd:
            cwd = venv
        process_env = AgiEnv._build_env(venv)

        shell_executable = None if sys.platform == "win32" else "/bin/bash"

        if wait:
            try:
                result = []
                async def read_stream(stream, callback=None):
                    enc = sys.stdout.encoding or "utf-8"
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode("utf-8", errors="replace").rstrip()
                        if not text:
                            continue
                        safe = text.encode(enc, errors="replace").decode(enc)
                        plain = AgiLogger.decolorize(safe)
                        msg = strip_time_level_prefix(plain)
                        # If callback looks like a logging function, pass extra
                        try:
                            callback(msg, extra={"subprocess": True})
                        except TypeError:
                            callback(msg)
                        result.append(msg)

                try:
                    cmd_list = shlex.split(cmd)
                    proc = await asyncio.create_subprocess_exec(
                        *cmd_list,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(cwd) if cwd else None,
                        env=process_env,
                    )
                except:
                    proc = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(cwd) if cwd else None,
                        env=process_env,
                        executable=shell_executable,
                    )

                _logger = getattr(AgiEnv, "logger", None)
                out_cb = log_callback if log_callback else (_logger.info if _logger else logging.info)
                err_cb = log_callback if log_callback else (_logger.error if _logger else logging.error)
                await asyncio.wait_for(asyncio.gather(
                    read_stream(proc.stdout, out_cb),
                    read_stream(proc.stderr, err_cb),
                ), timeout=timeout)

                returncode = await proc.wait()

                if returncode != 0:
                    # Promote to ERROR with context even if lines were logged as INFO
                    logger = getattr(AgiEnv, "logger", None)
                    if logger:
                        logger.error("Command failed with exit code %s: %s", returncode, cmd)
                    raise RuntimeError(f"Command failed with exit code {returncode}: {cmd}")

                return "\n".join(result)
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError(f"Command timed out after {timeout} seconds: {cmd}")
            except Exception as e:
                logger = getattr(AgiEnv, "logger", None)
                if logger:
                    logger.error(traceback.format_exc())
                raise RuntimeError(f"Command execution error: {e}") from e

        else:
            asyncio.create_task(asyncio.create_subprocess_shell(
                cmd,
                cwd=str(cwd),
                env=process_env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                executable=shell_executable
            ))
            return 0

    @staticmethod
    async def _run_bg(cmd, cwd=".", venv=None, timeout=None, log_callback=None,
                      env_override: dict | None = None, remove_env: set[str] | None = None):
        """
        Run the given command asynchronously, reading stdout and stderr line by line
        and passing them to the log_callback. Returns (stdout, stderr) as strings.
        """
        process_env = AgiEnv._build_env(venv)
        process_env["PYTHONUNBUFFERED"] = "1"
        if remove_env:
            for key in remove_env:
                process_env.pop(key, None)
        if env_override:
            process_env.update(env_override)

        result = []

        try:
            cmd_list = shlex.split(cmd)
            proc = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=process_env,
            )
        except:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=process_env,
            )

        async def read_stream(stream, callback=None):
            enc = sys.stdout.encoding or "utf-8"
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                safe = text.encode(enc, errors="replace").decode(enc)
                plain = AgiLogger.decolorize(safe)
                msg = strip_time_level_prefix(plain)
                try:
                    callback(msg, extra={"subprocess": True})
                except TypeError:
                    callback(msg)
                result.append(msg)

        tasks = []
        if proc.stdout:
            tasks.append(asyncio.create_task(
                read_stream(proc.stdout, log_callback if log_callback else logging.info)
            ))
        if proc.stderr:
            tasks.append(asyncio.create_task(
                read_stream(proc.stderr, log_callback if log_callback else logging.error)
            ))

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError as err:
            proc.kill()
            raise RuntimeError(f"Timeout expired for command: {cmd}") from err

        await asyncio.gather(*tasks)
        stdout, stderr = await proc.communicate()

        returncode = proc.returncode

        if returncode != 0:
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.error("Command failed with exit code %s: %s", returncode, cmd)
            raise RuntimeError(f"Command failed (exit {returncode})")

        return stdout.decode(), stderr.decode()

    async def run_agi(self, code, log_callback=None, venv: Path = None, type=None):
        """
        Asynchronous version of run_agi for use within an async context.
        """
        pattern = r"await\s+(?:Agi\.)?([^\(]+)\("
        matches = re.findall(pattern, code)
        if not matches:
            message = "Could not determine snippet name from code."
            if log_callback:
                log_callback(message)
            else:
                AgiEnv.logger.info(message)
            return "", ""
        snippet_name = matches[0]
        is_install_snippet = "install" in snippet_name.lower()

        runenv_path = Path(self.runenv)
        runenv_path.mkdir(parents=True, exist_ok=True)

        snippet_file = runenv_path / "{}_{}.py".format(
            re.sub(r"[^0-9A-Za-z_]+", "_", str(snippet_name)).strip("_") or "AGI.unknown_command",
            re.sub(r"[^0-9A-Za-z_]+", "_", str(self.target)).strip("_") or "unknown_app_name")
        with open(snippet_file, "w") as file:
            file.write(code)

        project_root = Path(venv) if venv else None
        project_venv = None
        if project_root:
            if project_root.name == ".venv" or (project_root / "pyvenv.cfg").exists():
                project_venv = project_root
            else:
                candidate = project_root / ".venv"
                if (candidate / "pyvenv.cfg").exists():
                    project_venv = candidate

        if not is_install_snippet and project_root and project_venv is None:
            message = f"No virtual environment found in {project_root}. Run INSTALL first."
            if log_callback:
                log_callback(message)
            else:
                AgiEnv.logger.warning(message)
            return "", message

        if project_venv:
            python_bin = project_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            cmd = f"{shlex.quote(str(python_bin))} {shlex.quote(str(snippet_file))}"
            result = await AgiEnv._run_bg(
                cmd,
                cwd=str(project_root),
                venv=project_venv,
                remove_env={"PYTHONPATH", "PYTHONHOME"},
                log_callback=log_callback,
            )
        else:
            python_bin = Path(sys.executable)
            cmd = f"{shlex.quote(str(python_bin))} {shlex.quote(str(snippet_file))}"
            result = await AgiEnv._run_bg(
                cmd,
                cwd=str(project_root or self.runenv),
                venv=Path(sys.prefix),
                remove_env={"PYTHONPATH", "PYTHONHOME"},
                log_callback=log_callback,
            )
        if log_callback:
            log_callback(f"Process finished")
        else:
            logging.info("Process finished")
        return result

    @staticmethod
    async def run_async(cmd, venv=None, cwd=None, timeout=None, log_callback=None):
        """
        Run a shell command asynchronously inside a virtual environment.
        Streams stdout/stderr live with sensible levels (packaging-aware).
        Returns the last non-empty line among stderr (preferred) then stdout.
        Raises on non-zero exit (logs stderr tail).
        """
        if (AgiEnv.verbose or 0) > 0:
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.info(f"Executing in {venv}: {cmd}")

        if cwd is None:
            cwd = venv

        # Build env similar to your other functions
        process_env = os.environ.copy()
        venv_path = Path(venv)
        if not (venv_path / "bin").exists() and venv_path.name != ".venv":
            venv_path = venv_path / ".venv"

        process_env["VIRTUAL_ENV"] = str(venv_path)
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        venv_bin = venv_path / bin_dir
        process_env["PATH"] = str(venv_bin) + os.pathsep + process_env.get("PATH", "")
        process_env["PYTHONUNBUFFERED"] = "1"  # ensure timely output
        shell_executable = None if os.name == "nt" else "/bin/bash"

        # Normalize cmd to string for create_subprocess_shell
        if isinstance(cmd, (list, tuple)):
            cmd = " ".join(cmd)

        result = []

        try:
            cmd_list = shlex.split(cmd)
            proc = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=process_env,
            )
        except:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=process_env,
                executable=shell_executable,
            )

        async def read_stream(stream, callback=None):
            enc = sys.stdout.encoding or "utf-8"
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                safe = text.encode(enc, errors="replace").decode(enc)
                plain = AgiLogger.decolorize(safe)
                msg = strip_time_level_prefix(plain)
                logger = getattr(AgiEnv, "logger", None)
                if callback is (logger.info if logger else None) or callback is (logger.error if logger else None):
                    callback(msg, extra={"subprocess": True})
                else:
                    callback(msg)
                result.append(msg)

        try:
            _logger = getattr(AgiEnv, "logger", None)
            out_cb = log_callback if log_callback else (_logger.info if _logger else logging.info)
            err_cb = log_callback if log_callback else (_logger.error if _logger else logging.error)
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(proc.stdout, out_cb),
                    read_stream(proc.stderr, err_cb),
                    proc.wait(),
                ),
                timeout=timeout,
            )
        except Exception as err:
            proc.kill()
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.error(f"Error during: {cmd}")
                logger.error(err)
            raise RuntimeError(f"Subprocess execution error for: {cmd}") from err

        rc = proc.returncode
        if rc != 0:
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.error("Command failed with exit code %s: %s", rc, cmd)
            raise RuntimeError(f"Command failed with exit code {rc}: {cmd}")

        # Preserve original behavior: return last non-empty line (prefer stderr, else stdout)
        def last_non_empty(lines):
            for l in reversed(lines):
                if l.strip():
                    return l
            return None

        last_line = last_non_empty(result) or ""
        return last_line


    @staticmethod
    def create_symlink(src: Path, dest: Path):
        try:
            if dest.exists() or dest.is_symlink():
                if dest.is_symlink() and dest.resolve() == src.resolve():
                    logger = getattr(AgiEnv, "logger", None)
                    if logger:
                        logger.info(f"Symlink already exists and is correct: {dest} -> {src}")
                    return
                logger = getattr(AgiEnv, "logger", None)
                if logger:
                    logger.warning(f"Warning: Destination already exists and is not a symlink: {dest}")
                dest.unlink()
            dest.symlink_to(src, target_is_directory=src.is_dir())
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.info(f"Symlink created: @{dest.name} -> {src}")
        except Exception as e:
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.error(f"Failed to create symlink @{dest} -> {src}: {e}")

    def change_app(self, app):
        # Normalize current and requested app identifiers to comparable names
        def _app_name(value):
            if value is None:
                return None
            try:
                # Accept Path-like or string; compare by final directory name
                return Path(str(value)).name
            except Exception:
                return str(value)

        current_name = _app_name(getattr(self, "app", None))
        requested_name = _app_name(app)

        if requested_name == current_name:
            return

        apps_dir = getattr(self, "apps_dir", None) or AgiEnv.apps_dir
        active_app = apps_dir / requested_name

        try:
            type(self).__init__(
                self,
                apps_dir=active_app.parent,
                app=requested_name,
                verbose=AgiEnv.verbose,
            )
        except Exception:
            if active_app.exists():
                shutil.rmtree(active_app, ignore_errors=True)
            raise

    @staticmethod
    def is_local(ip):
        """

        Args:
          ip:

        Returns:

        """
        if (
                not ip or ip in AgiEnv._ip_local_cache
        ):  # Check if IP is None, empty, or cached
            return True

        for _, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and ip == addr.address:
                    AgiEnv._ip_local_cache.add(ip)  # Cache the local IP found
                    return True

        return False

    @staticmethod
    def has_admin_rights():
        """
        Check if the current process has administrative rights on Windows.

        Returns:
            bool: True if admin, False otherwise.
        """
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    @staticmethod
    def create_junction_windows(source: Path, dest: Path):
        """
        Create a directory junction on Windows.

        Args:
            source (Path): The target directory path.
            dest (Path): The destination junction path.
        """
        try:
            # Using the mklink command to create a junction (/J) which doesn't require admin rights.
            subprocess.check_call(['cmd', '/c', 'mklink', '/J', str(dest), str(source)])
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.info(f"Created junction: {dest} -> {source}")
        except subprocess.CalledProcessError as e:
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.error(f"Failed to create junction. Error: {e}")

    @staticmethod
    def create_symlink_windows(source: Path, dest: Path):
        """
        Create a symbolic link on Windows, handling permissions and types.

        Args:
            source (Path): Source directory path.
            dest (Path): Destination symlink path.
        """
        # Define necessary Windows API functions and constants
        CreateSymbolicLink = ctypes.windll.kernel32.CreateSymbolicLinkW
        CreateSymbolicLink.restype = wintypes.BOOL
        CreateSymbolicLink.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]

        SYMBOLIC_LINK_FLAG_DIRECTORY = 0x1

        # Check if Developer Mode is enabled or if the process has admin rights
        if not AgiEnv.has_admin_rights():
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.info(
                    "Creating symbolic links on Windows requires administrative privileges or Developer Mode enabled."
                )
            return

        flags = SYMBOLIC_LINK_FLAG_DIRECTORY

        success = CreateSymbolicLink(str(dest), str(source), flags)
        if success:
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.info(f"Created symbolic link for .venv: {dest} -> {source}")
        else:
            error_code = ctypes.GetLastError()
            logger = getattr(AgiEnv, "logger", None)
            if logger:
                logger.info(
                    f"Failed to create symbolic link for .venv. Error code: {error_code}"
                )

    def create_rename_map(self, target_project: Path, dest_project: Path) -> dict:
        """
        Create a mapping of old → new names for cloning.
        Includes project names, top-level src folders, worker folders,
        in-file identifiers and class names.
        """
        def cap(s: str) -> str:
            return "".join(p.capitalize() for p in s.split("_"))

        name_tp = target_project.name      # e.g. "flight_project" or "dag_app_template"
        name_dp = dest_project.name        # e.g. "tata_project"

        def strip_suffix(name: str) -> str:
            for suffix in ("_project", "_template"):
                if name.endswith(suffix):
                    return name[: -len(suffix)]
            return name

        tp = strip_suffix(name_tp)
        dp = strip_suffix(name_dp)

        tm = tp.replace("-", "_")
        dm = dp.replace("-", "_")
        tc = cap(tm)                       # "Flight"
        dc = cap(dm)                       # "Tata"

        rename_map = {
            # project-level
            name_tp:              name_dp,

            # folder-level (longest keys first)
            f"src/{tm}_worker": f"src/{dm}_worker",
            f"src/{tm}":        f"src/{dm}",

            # sibling-level
            f"{tm}_worker":      f"{dm}_worker",
            tm:                    dm,

            # class-level
            f"{tc}Worker":       f"{dc}Worker",
            f"{tc}Args":         f"{dc}Args",
            f"{tc}ArgsTD":       f"{dc}ArgsTD",
            tc:                    dc,
        }

        # Add common suffix variants (e.g., flight_args -> toto_args)
        for suffix in ("_args", "_manager", "_worker", "_distributor", "_project"):
            rename_map.setdefault(f"{tm}{suffix}", f"{dm}{suffix}")
        rename_map.setdefault(f"{tm}_args_td", f"{dm}_args_td")
        rename_map.setdefault(f"{tm}ArgsTD", f"{dm}ArgsTD")

        return rename_map

    def clone_project(self, target_project: Path, dest_project: Path):
        """
        Clone a project by copying files and directories, applying renaming,
        then cleaning up any leftovers.

        Args:
            target_project: Path under self.apps_dir (e.g. Path("flight_project"))
            dest_project:   Path under self.apps_dir (e.g. Path("tata_project"))
        """

        # normalize names
        templates_root = self.apps_dir / "templates"
        if not target_project.name.endswith("_project"):
            candidate = target_project.with_name(target_project.name + "_project")
            if (self.apps_dir / candidate).exists() or (templates_root / candidate).exists():
                target_project = candidate
        if not dest_project.name.endswith("_project"):
            dest_project = dest_project.with_name(dest_project.name + "_project")

        rename_map  = self.create_rename_map(target_project, dest_project)
        def _strip(name: Path) -> str:
            base = name.name if isinstance(name, Path) else str(name)
            for suffix in ("_project", "_template"):
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
            return base.replace("-", "_")

        tm = _strip(target_project)
        dm = _strip(dest_project)
        source_root = self.apps_dir / target_project
        if not source_root.exists() and templates_root.exists():
            source_root = templates_root / target_project
        dest_root   = self.apps_dir / dest_project

        if not source_root.exists():
            AgiEnv.logger.info(f"Source project '{target_project}' does not exist.")
            return
        if dest_root.exists():
            AgiEnv.logger.info(f"Destination project '{dest_project}' already exists.")
            return

        # Clone all files by default. Only skip repository metadata such as .git.
        ignore_patterns = [".git", ".git/", ".git/**"]
        spec = PathSpec.from_lines(GitWildMatchPattern, ignore_patterns)

        try:
            dest_root.mkdir(parents=True, exist_ok=False)
        except Exception as e:
            AgiEnv.logger.error(f"Could not create '{dest_root}': {e}")
            return

        # 1) Recursive clone
        self.clone_directory(source_root, dest_root, rename_map, spec, source_root)

        # 2) Final cleanup
        self._cleanup_rename(dest_root, rename_map)
        self.projects.insert(0, dest_project)

        # 3) Mirror data directory if present under ~/data/<source>
        src_data_dir = self.home_abs / "data" / tm
        dest_data_dir = self.home_abs / "data" / dm
        try:
            if src_data_dir.exists() and not dest_data_dir.exists():
                shutil.copytree(src_data_dir, dest_data_dir)
        except Exception as exc:
            AgiEnv.logger.info(f"Unable to copy data directory '{src_data_dir}' to '{dest_data_dir}': {exc}")

    def clone_directory(self,
                        source_dir: Path,
                        dest_dir: Path,
                        rename_map: dict,
                        spec: PathSpec,
                        source_root: Path):
        """
        Recursively copy + rename directories, files, and contents,
        applying renaming only on exact path segments.
        """
        for item in source_dir.iterdir():
            rel = item.relative_to(source_root).as_posix()

            # Skip files/directories matched by .gitignore spec
            if spec.match_file(rel + ("/" if item.is_dir() else "")):
                continue

            # Rename only full segments of the relative path
            parts = rel.split("/")
            for i, seg in enumerate(parts):
                # Sort rename_map by key length descending to avoid partial conflicts
                for old, new in sorted(rename_map.items(), key=lambda kv: -len(kv[0])):
                    if seg == old:
                        parts[i] = new
                        break

            new_rel = "/".join(parts)
            dst = dest_dir / new_rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            if item.is_dir():
                if item.name == ".venv":
                    # Keep virtual env directory as a symlink
                    os.symlink(item, dst, target_is_directory=True)
                else:
                    self.clone_directory(item, dest_dir, rename_map, spec, source_root)

            elif item.is_file():
                suf = item.suffix.lower()
                base = item.stem

                # Rename file if its basename is in rename_map
                if base in rename_map:
                    dst = dst.with_name(rename_map[base] + item.suffix)

                if suf in (".7z", ".zip"):
                    shutil.copy2(item, dst)

                elif suf == ".py":
                    src = item.read_text(encoding="utf-8")
                    try:
                        tree = ast.parse(src)
                        renamer = ContentRenamer(rename_map)
                        new_tree = renamer.visit(tree)
                        ast.fix_missing_locations(new_tree)
                        out = astor.to_source(new_tree)
                    except SyntaxError:
                        out = src
                    # Whole word replacements in Python source text
                    for old, new in rename_map.items():
                        out = re.sub(rf"\b{re.escape(old)}\b", new, out)
                    dst.write_text(out, encoding="utf-8")

                elif suf in (".toml", ".md", ".txt", ".json", ".yaml", ".yml"):
                    txt = item.read_text(encoding="utf-8")
                    for old, new in rename_map.items():
                        txt = re.sub(rf"\b{re.escape(old)}\b", new, txt)
                    dst.write_text(txt, encoding="utf-8")

                else:
                    shutil.copy2(item, dst)

            elif item.is_symlink():
                target = os.readlink(item)
                os.symlink(target, dst, target_is_directory=item.is_dir())

    def _cleanup_rename(self, root: Path, rename_map: dict):
        """
        1) Rename any leftover file/dir basenames (including .py) that exactly match a key.
        2) Rewrite text files for any straggler content references.
        """
        # build simple name→new map (no slashes)
        simple_map = {old: new for old, new in rename_map.items() if "/" not in old}
        # sort longest first
        sorted_simple = sorted(simple_map.items(), key=lambda kv: len(kv[0]), reverse=True)

        # -- step 1: rename basenames (dirs & files) bottom‑up --
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            old = path.name
            for o, n in sorted_simple:
                # directory exactly "flight" → "truc", or "flight_worker" → "truc_worker"
                if old == o or old == f"{o}_worker" or old == f"{o}_project":
                    new_name = old.replace(o, n, 1)
                    path.rename(path.with_name(new_name))
                    break
                # file like "flight.py" → "truc.py"
                if path.is_file() and old.startswith(o + "."):
                    new_name = n + old[len(o):]
                    path.rename(path.with_name(new_name))
                    break

        # -- step 2: rewrite any lingering text references --
        exts = {".py", ".toml", ".md", ".txt", ".json", ".yaml", ".yml"}
        for file in root.rglob("*"):
            if not file.is_file() or file.suffix.lower() not in exts:
                continue
            txt = file.read_text(encoding="utf-8")
            new_txt = txt
            for old, new in rename_map.items():
                new_txt = re.sub(rf"\b{re.escape(old)}\b", new, new_txt)
            if new_txt != txt:
                file.write_text(new_txt, encoding="utf-8")

    def replace_content(self, txt: str, rename_map: dict) -> str:
        for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
            # only match whole‐word occurrences of `old`
            pattern = re.compile(rf"\b{re.escape(old)}\b")
            txt = pattern.sub(new, txt)
        return txt

    def read_gitignore(self, gitignore_path: Path) -> 'PathSpec':
        from pathspec import PathSpec
        from pathspec.patterns import GitWildMatchPattern
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        return PathSpec.from_lines(GitWildMatchPattern, lines)

    def is_valid_ip(self, ip: str) -> bool:
        pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        if pattern.match(ip):
            parts = ip.split(".")
            return all(0 <= int(part) <= 255 for part in parts)
        return False

    def unzip_data(self, archive_path: Path, extract_to: Path | str = None):
        archive_path = Path(archive_path)
        if not archive_path.exists():
            AgiEnv.logger.warning(f"Warning: Archive '{archive_path}' does not exist. Skipping extraction.")
            return  # Do not exit, just warn

        # Normalize extract_to to a Path relative to cwd or absolute
        if not extract_to:
            extract_to = "data"
        dest = self.home_abs / extract_to
        dataset = dest / "dataset"

        # Clear existing folder if not empty to avoid extraction errors on second call
        if dataset.exists() and any(dataset.iterdir()):
            if AgiEnv.verbose > 0:
                AgiEnv.logger.info(f"Destination '{dataset}' exists and is not empty. Clearing it before extraction.")
            shutil.rmtree(dataset)
        dest.mkdir(parents=True, exist_ok=True)

        try:
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=dest)
            if AgiEnv.verbose > 0:
                AgiEnv.logger.info(f"Successfully extracted '{archive_path}' to '{dest}'.")
        except Exception as e:
            AgiEnv.logger.error(f"Failed to extract '{archive_path}': {e}")
            traceback.print_exc()
            raise RuntimeError(f"Extraction failed for '{archive_path}'") from e

    @staticmethod
    def check_internet():
        AgiEnv.logger.info(f"Checking internet connectivity...")
        try:
            # HEAD request to Google
            req = urllib.request.Request("https://www.google.com", method="HEAD")
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass  # Success if no exception
        except Exception:
            AgiEnv.logger.error(f"No internet connection detected. Aborting.")
            return False
        AgiEnv.logger.info(f"Internet connection is OK.")
        return True



class ContentRenamer(ast.NodeTransformer):
    """
    A class that renames identifiers in an abstract syntax tree (AST).
    Attributes:
        rename_map (dict): A mapping of old identifiers to new identifiers.
    """
    def __init__(self, rename_map):
        """
        Initialize the ContentRenamer with the rename_map.

        Args:
            rename_map (dict): Mapping of old names to new names.
        """
        self.rename_map = rename_map

    def visit_Name(self, node):
        # Rename variable and function names
        """
        Visit and potentially rename a Name node in the abstract syntax tree.

        Args:
            self: The current object instance.
            node: The Name node in the abstract syntax tree.

        Returns:
            ast.Node: The modified Name node after potential renaming.

        Note:
            This function modifies the Name node in place.

        Raises:
            None
        """
        if node.id in self.rename_map:
            AgiEnv.logger.info(f"Renaming Name: {node.id} ➔ {self.rename_map[node.id]}")
            node.id = self.rename_map[node.id]
        self.generic_visit(node)  # Ensure child nodes are visited
        return node

    def visit_Attribute(self, node):
        # Rename attributes
        """
        Visit and potentially rename an attribute in a node.

        Args:
            node: A node representing an attribute.

        Returns:
            node: The visited node with potential attribute renamed.

        Raises:
            None.
        """
        if node.attr in self.rename_map:
            AgiEnv.logger.info(f"Renaming Attribute: {node.attr} ➔ {self.rename_map[node.attr]}")
            node.attr = self.rename_map[node.attr]
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        # Rename function names
        """
        Rename a function node based on a provided mapping.

        Args:
            node (ast.FunctionDef): The function node to be processed.

        Returns:
            ast.FunctionDef: The function node with potential name change.
        """
        if node.name in self.rename_map:
            AgiEnv.logger.info(f"Renaming Function: {node.name} ➔ {self.rename_map[node.name]}")
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        # Rename class names
        """
        Visit and potentially rename a ClassDef node.

        Args:
            node (ast.ClassDef): The ClassDef node to visit.

        Returns:
            ast.ClassDef: The potentially modified ClassDef node.
        """
        if node.name in self.rename_map:
            AgiEnv.logger.info(f"Renaming Class: {node.name} ➔ {self.rename_map[node.name]}")
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        # Rename function argument names
        """
        Visit and potentially rename an argument node.

        Args:
            self: The instance of the class.
            node: The argument node to visit and possibly rename.

        Returns:
            ast.AST: The modified argument node.

        Notes:
            Modifies the argument node in place if its name is found in the rename map.

        Raises:
            None.
        """
        if node.arg in self.rename_map:
            AgiEnv.logger.info(f"Renaming Argument: {node.arg} ➔ {self.rename_map[node.arg]}")
            node.arg = self.rename_map[node.arg]
        self.generic_visit(node)
        return node

    def visit_Global(self, node):
        # Rename global variable names
        """
        Visit and potentially rename global variables in the AST node.

        Args:
            self: The instance of the class that contains the renaming logic.
            node: The AST node to visit and potentially rename global variables.

        Returns:
            AST node: The modified AST node with global variable names potentially renamed.
        """
        new_names = []
        for name in node.names:
            if name in self.rename_map:
                AgiEnv.logger.info(f"Renaming Global Variable: {name} ➔ {self.rename_map[name]}")
                new_names.append(self.rename_map[name])
            else:
                new_names.append(name)
        node.names = new_names
        self.generic_visit(node)
        return node

    def visit_nonlocal(self, node):
        # Rename nonlocal variable names
        """
        Visit and potentially rename nonlocal variables in the AST node.

        Args:
            self: An instance of the class containing the visit_nonlocal method.
            node: The AST node to visit and potentially modify.

        Returns:
            ast.AST: The modified AST node after visiting and potentially renaming nonlocal variables.
        """
        new_names = []
        for name in node.names:
            if name in self.rename_map:
                AgiEnv.logger.info(
                    f"Renaming Nonlocal Variable: {name} ➔ {self.rename_map[name]}"
                )
                new_names.append(self.rename_map[name])
            else:
                new_names.append(name)
        node.names = new_names
        self.generic_visit(node)
        return node

    def visit_Assign(self, node):
        # Rename assigned variable names
        """
        Visit and process an assignment node.

        Args:
            self: The instance of the visitor class.
            node: The assignment node to be visited.

        Returns:
            ast.Node: The visited assignment node.
        """
        self.generic_visit(node)
        return node

    def visit_AnnAssign(self, node):
        # Rename annotated assignments
        """
        Visit and process an AnnAssign node in an abstract syntax tree.

        Args:
            self: The AST visitor object.
            node: The AnnAssign node to be visited.

        Returns:
            AnnAssign: The visited AnnAssign node.
        """
        self.generic_visit(node)
        return node

    def visit_For(self, node):
        # Rename loop variable names
        """
        Visit and potentially rename the target variable in a For loop node.

        Args:
            node (ast.For): The For loop node to visit.

        Returns:
            ast.For: The modified For loop node.

        Note:
            This function may modify the target variable in the For loop node if it exists in the rename map.
        """
        if isinstance(node.target, ast.Name) and node.target.id in self.rename_map:
            AgiEnv.logger.info(
                f"Renaming For Loop Variable: {node.target.id} ➔ {self.rename_map[node.target.id]}"
            )
            node.target.id = self.rename_map[node.target.id]
        self.generic_visit(node)
        return node

    def visit_Import(self, node):
        """
        Rename imported modules in 'import module' statements.

        Args:
            node (ast.Import): The import node.
        """
        for alias in node.names:
            original_name = alias.name
            if original_name in self.rename_map:
                AgiEnv.logger.info(
                    f"Renaming Import Module: {original_name} ➔ {self.rename_map[original_name]}"
                )
                alias.name = self.rename_map[original_name]
            else:
                # Handle compound module names if necessary
                for old, new in self.rename_map.items():
                    if original_name.startswith(old):
                        AgiEnv.logger.info(
                            f"Renaming Import Module: {original_name} ➔ {original_name.replace(old, new, 1)}"
                        )
                        alias.name = original_name.replace(old, new, 1)
                        break
        self.generic_visit(node)
        return node

    def visit_ImportFrom(self, node):
        """
        Rename modules and imported names in 'from module import name' statements.

        Args:
            node (ast.ImportFrom): The import from node.
        """
        # Rename the module being imported from
        if node.module in self.rename_map:
            AgiEnv.logger.info(
                f"Renaming ImportFrom Module: {node.module} ➔ {self.rename_map[node.module]}"
            )
            node.module = self.rename_map[node.module]
        else:
            for old, new in self.rename_map.items():
                if node.module and node.module.startswith(old):
                    new_module = node.module.replace(old, new, 1)
                    AgiEnv.logger.info(
                        f"Renaming ImportFrom Module: {node.module} ➔ {new_module}"
                    )
                    node.module = new_module
                    break

        # Rename the imported names
        for alias in node.names:
            if alias.name in self.rename_map:
                AgiEnv.logger.info(
                    f"Renaming Imported Name: {alias.name} ➔ {self.rename_map[alias.name]}"
                )
                alias.name = self.rename_map[alias.name]
            else:
                for old, new in self.rename_map.items():
                    if alias.name.startswith(old):
                        AgiEnv.logger.info(
                            f"Renaming Imported Name: {alias.name} ➔ {alias.name.replace(old, new, 1)}"
                        )
                        alias.name = alias.name.replace(old, new, 1)
                        break
        self.generic_visit(node)
        return node

        import getpass, os, sys, subprocess, signal

        me = getpass.getuser()
        my_pid = os.getpid()
def _is_relative_to(path: Path, other: Path) -> bool:
    """Return ``True`` if ``path`` lies under ``other`` (without requiring Python 3.9)."""

    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False
