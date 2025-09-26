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
by installers as well as runtime workers.  Supporting free functions provide small
parsing and path utilities leveraged during setup.
"""
import shlex
from IPython.core.ultratb import FormattedTB
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
from pathlib import Path, PureWindowsPath, PurePosixPath
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
from concurrent.futures import ThreadPoolExecutor
from agi_env.agi_logger import AgiLogger
# Get constructor parameters of FormattedTB
_sig = inspect.signature(FormattedTB.__init__).parameters

_tb_kwargs = dict(mode='Verbose', call_pdb=True)
if 'color_scheme' in _sig:
    _tb_kwargs['color_scheme'] = 'NoColor'
else:
    _tb_kwargs['theme_name'] = 'NoColor'

sys.excepthook = FormattedTB(**_tb_kwargs)

# logger = AgiLogger.get_logger(__name__)

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

class AgiEnv:
    """Encapsulates filesystem and configuration state for AGILab deployments."""
    install_type = None
    apps_dir = None
    app = None
    target = None
    TABLE_MAX_ROWS = None
    TABLE_SAMPLING = None
    init_done = False
    hw_rapids_capable = None
    is_worker_env = False
    _is_managed_pc = None
    debug = False
    uv = None
    benchmark = None
    verbose = None
    verbose = None
    pyvers_worker = None
    logger = None
    out_log = None
    err_log = None
    _ip_local_cache: set = set({"127.0.0.1", "::1"})
    INDEX_URL="https://test.pypi.org/simple"
    EXTRA_INDEX_URL="https://pypi.org/simple"
    snippet_tail = "asyncio.get_event_loop().run_until_complete(main())"
    _pythonpath_entries: list[str] = []

    def __init__(self,
                 active_app: Path | str = None,
                 install_type: int = None,
                 verbose: int = None,
                 debug=False,
                 python_variante: str = ''):

        AgiEnv.is_managed_pc = getpass.getuser().startswith("T0")
        AgiEnv._is_managed_pc = AgiEnv.is_managed_pc
        self._agi_resources = Path("resources/.agilab")
        home_abs = Path.home() / "MyApp" if AgiEnv.is_managed_pc else Path.home()
        self.home_abs = home_abs

        if verbose is None:
            verbose = 0
        self.uv = "uv"
        if verbose < 3:
            self.uv = "uv --quiet"
        elif verbose >= 3:
            self.uv = "uv --verbose"

        if os.name == "nt":
            pip_prefix = (
                f'set "PIP_INDEX_URL={AgiEnv.INDEX_URL}" && '
                f'set "PIP_EXTRA_INDEX_URL={AgiEnv.EXTRA_INDEX_URL}" && '
            )
        else:
            pip_prefix = (
                f"PIP_INDEX_URL={AgiEnv.INDEX_URL} "
                f"PIP_EXTRA_INDEX_URL={AgiEnv.EXTRA_INDEX_URL} "
            )

        self.pip_prefix = pip_prefix
        AgiEnv.pip_prefix = pip_prefix
        self.uv = f"{pip_prefix}{self.uv}"

        AgiEnv.resources_path = home_abs / self._agi_resources.name
        env_path = AgiEnv.resources_path / ".env"
        self.benchmark = AgiEnv.resources_path / "benchmark.json"
        AgiEnv.envars = dotenv_values(dotenv_path=env_path, verbose=verbose)
        envars = AgiEnv.envars

        module_path = Path(__file__).resolve()
        package_root = module_path.parent
        site_packages_root = package_root.parent

        agilab_src = None
        for parent in module_path.parents:
            if parent.name == "agilab":
                agilab_src = parent.parent
                break
        if agilab_src is None:
            agilab_src = site_packages_root

        agilab_spec = importlib.util.find_spec("agilab")
        if agilab_spec is not None and agilab_spec.origin:
            agilab_installed = Path(agilab_spec.origin).parents[1]
        elif (site_packages_root / "agi_env").exists():
            agilab_installed = site_packages_root
        else:
            agilab_installed = package_root

        if isinstance(active_app, str):
            # case only worker_env
            self.is_worker_env = True
            active_app = home_abs / "wenv" / active_app
        else:
            if not active_app:
                venv_home = Path(sys.prefix).parent
                if venv_home.name == "agilab":
                    active_app = agilab_src / "agilab/apps" / envars.get("APP_DEFAULT", 'flight_project')
                else:
                    active_app = venv_home / "apps" / envars.get("APP_DEFAULT", 'flight_project')
            else:
                active_app = active_app.expanduser()

            if not active_app.name.endswith('_project') and not active_app.name.endswith('_worker'):
                raise ValueError(f"{active_app} must end with '_project'")

        self.active_app = active_app
        target = active_app.name.replace("_project", "").replace("_worker","").replace("-", "_")

        AgiEnv.verbose = verbose
        self.verbose = verbose
        self._is_managed_pc = AgiEnv.is_managed_pc
        AgiEnv.python_variante = python_variante
        AgiEnv.logger =  AgiLogger.get_logger("agi_env")
        AgiEnv.logger =  AgiLogger.configure(verbose=verbose, base_name="agi_env")
        AgiEnv.debug = debug

        if install_type is None:
            if agilab_src.name == "src":
                install_type = 1
            else:
                install_type = 0
        elif isinstance(install_type, str):
            install_type = int(install_type)

        AgiEnv.install_type = install_type
        self.node_root = agilab_installed / "agi_node"
        self.env_root = agilab_installed / "agi_env"
        self.core_root = agilab_installed / "agi_core"
        self.cluster_root = agilab_installed / "agi_cluster"

        if install_type == 1:
            self.node_root = agilab_src / "agilab/core/agi-node"
            self.env_root = agilab_src / "agilab/core/agi-env"
            self.core_root = agilab_src / "agilab/core/agi-core"
            self.cluster_root = agilab_src / "agilab/core/agi-cluster"
            src_cluster = self.cluster_root / "src"
            self.cli = src_cluster / "agi_cluster/agi_distributor/cli.py"
            self.agilab_src = agilab_src
        else:
            self.agilab_src = agilab_installed
            self.cli = self.cluster_root / "agi_distributor/cli.py"

        self.env_src = self._resolve_package_root(self.env_root)
        self.node_src = self._resolve_package_root(self.node_root)
        self.core_src = self._resolve_package_root(self.core_root)
        self.cluster_src = self._resolve_package_root(self.cluster_root)

        self.st_resources = self.agilab_src / "agilab/resources"

        if install_type == 0:
            apps_root = self.agilab_src / "agilab/apps"
            os.makedirs(active_app.parent, exist_ok=True)
            if apps_root.exists():
                agilab_path = self.read_agilab_path()
                if agilab_path:
                    apps_root = agilab_path / "apps"
                    for src_app in apps_root.glob("*_project"):
                        # If it's a directory and already exists at destination -> remove it first
                        dest_app = active_app.parent / src_app.name
                        try:
                            if dest_app.is_symlink():
                                dest_app.unlink()  # remove the link itself
                            elif dest_app.exists():
                                shutil.rmtree(dest_app)  # remove a real directory tree
                        except FileNotFoundError:
                            pass
                        if os.name == "nt":
                            AgiEnv.create_symlink_windows(Path(src_app), dest_app)
                        else:
                            # For Unix-like systems
                            os.symlink(src_app, dest_app, target_is_directory=True)
                        AgiEnv.logger.info(f"Created symbolic link for app: {src_app} -> {dest_app}")
                else:
                    self.copy_existing_projects(apps_root, active_app.name)
            else:
                AgiEnv.logger.info(f"Warning: {apps_root} does not exist, nothing to copy!")


        resources_root = self.env_root
        src_layout = self.env_root / "src/agi_env"
        if install_type == 1 and src_layout.exists():
            resources_root = src_layout
        elif not (resources_root / self._agi_resources).exists():
            package_root = Path(__file__).resolve().parent
            if (package_root / self._agi_resources).exists():
                resources_root = package_root

        if install_type != 2:
            self._init_resources(resources_root / self._agi_resources)
        self.TABLE_MAX_ROWS = int(envars.get("TABLE_MAX_ROWS", 1000))
        self.TABLE_SAMPLING = int(envars.get("TABLE_SAMPLING", 20))

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

        dist_abs = wenv_abs / 'dist'
        dist = normalize_path(dist_abs)
        if not dist in sys.path:
            sys.path.append(dist)
        self.dist_abs = dist_abs
        self.app_src = active_app / "src"
        self.manager_pyproject = active_app / "pyproject.toml"
        self.worker_path = self.app_src / target_worker / f"{target_worker}.py"
        self.manager_path = self.app_src / target / f"{target}.py"
        is_local_worker = self.has_agilab_anywhere_under_home(self.agilab_src)
        self.setup_core = self.agilab_src / "agilab/core/agi-node/src"
        self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
        worker_src = self.wenv_rel / 'src'

        if install_type == 0:
            self.setup_core = self.node_root.parent
        elif install_type == 2 and not is_local_worker:
            active_app = self.agilab_src
            self.app_src = self.agilab_src / "src"
            self.setup_core = worker_src
            self.worker_path = worker_src / target_worker / f"{target_worker}.py"
            self.manager_path = worker_src / target / f"{target}.py"

        self.setup_core = self.setup_core / "agi_node/agi_dispatcher/build.py"
        self.uvproject = active_app / "uv_config.toml"
        self.post_install = self.worker_path.parent / "post_install.py"
        self.pre_install = self.worker_path.parent / "pre_install.py"
        self.post_install_rel = worker_src / target_worker / "post_install.py"

        src_path = normalize_path(self.app_src)
        if not src_path in sys.path:
            sys.path.append(src_path)

        AgiEnv.apps_dir = active_app.parent
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
        self.uv_worker = self.uv
        use_freethread = False

        if self.worker_pyproject.exists():
            try:
                with open(self.worker_pyproject, "r") as f:
                    data = tomlkit.parse(f.read())
                use_freethread = data["tool"]["freethread_info"]["is_app_freethreaded"]
            except (KeyError, TypeError, AttributeError, tomlkit.exceptions.TOMLKitError) as err:
                AgiEnv.logger.debug(
                    "worker pyproject missing freethread metadata or invalid; assuming non-freethreaded (%s)",
                    err,
                )
            except OSError as err:
                AgiEnv.logger.warning(
                    "Unable to read worker pyproject %s: %s",
                    self.worker_pyproject,
                    err,
                )
        else:
            AgiEnv.logger.debug(
                "No worker pyproject found at %s; assuming non-freethreaded app", self.worker_pyproject
            )

        if use_freethread and self.is_free_threading_available:
            self.uv_worker = "PYTHON_GIL=0 " + self.uv
            self.pyvers_worker = self.pyvers_worker + "t"

        if install_type == 2:
            return

        self.base_worker_cls, self._base_worker_module = self.get_base_worker_cls(
            self.worker_path, worker_class
        )
        if not self.worker_path.exists():
            AgiEnv.logger.info(f"Missing {self.target_worker_class} definition; should be in {self.worker_path} but it does not exist")
            sys.exit(1)

        envars = AgiEnv.envars
        raw_credentials = envars.get("CLUSTER_CREDENTIALS", getpass.getuser())
        credentials_parts = raw_credentials.split(":")
        self.user = credentials_parts[0]
        self.password = credentials_parts[1] if len(credentials_parts) > 1 else None

        self.projects = self.get_projects(AgiEnv.apps_dir)
        if not self.projects:
            AgiEnv.logger.info(f"Could not find any target project app in {self.agilab_src / 'apps'}.")

        self.setup_app = active_app / "build.py"

        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", "data"))
        data_rel = self.AGILAB_SHARE / self.target
        self.dataframe_path = data_rel / "dataframe"
        self.data_rel = data_rel
        self._init_projects()

        self.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
        if not self.is_valid_ip(self.scheduler_ip):
            raise ValueError(f"Invalid scheduler IP address: {self.scheduler_ip}")

        if AgiEnv.install_type:
            self.help_path = str(self.agilab_src / "../docs/html")
        else:
            self.help_path = "https://thalesgroup.github.io/agilab"
        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", home_abs / "data"))

        self.app_src.mkdir(parents=True, exist_ok=True)
        app_src_str = str(self.app_src)
        if app_src_str not in sys.path:
            sys.path.append(app_src_str)

        # type 3: only core install
        if AgiEnv.install_type != 3:
            AgiEnv.examples = self.agilab_src / "agilab/examples"
            self.init_envars_app(AgiEnv.envars)
            self._init_apps()

        if os.name == "nt":
            AgiEnv.export_local_bin = ""
        else:
            AgiEnv.export_local_bin = 'export PATH="~/.local/bin:$PATH";'

    @staticmethod
    def _resolve_package_root(root: Path) -> Path:
        """Return the ``src`` directory for a package when present.

        Many AGILab components follow the ``src/`` layout; when that folder is
        missing the package root itself is returned.
        """

        src_dir = root / "src"
        return src_dir if src_dir.exists() else root

    def _collect_pythonpath_entries(self) -> list[str]:
        """Build an ordered list of paths that must live on ``PYTHONPATH``."""

        candidates = [
            self.env_src,
            self.node_src,
            self.core_src,
            self.cluster_src,
            self.dist_abs,
            self.app_src,
            self.wenv_abs / "src",
            self.agilab_src / "agilab",
        ]
        return self._dedupe_paths(candidates)

    def _configure_pythonpath(self, entries: list[str]) -> None:
        """Inject ``entries`` into both ``sys.path`` and the ``PYTHONPATH`` env var."""

        AgiEnv._pythonpath_entries = entries
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

    def active(self, target, install_type):
        """Switch :attr:`active_app` to ``target`` if it differs from the current one."""

        if str(self.active_app) != target:
            self.change_active_app(target, install_type)

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

        AgiEnv.envars[key] = value
        os.environ[key] = str(value)
        AgiEnv._update_env_file({key: value})

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
                AgiEnv.logger.error(f"File {where_is_agi} does not exist.")
            except PermissionError:
                AgiEnv.logger.error(f"Permission denied when accessing {where_is_agi}.")
            except Exception as e:
                AgiEnv.logger.error(f"An error occurred: {e}")
        else:
            return False

    @staticmethod
    def locate_agilab_installation(verbose=False):
        """Attempt to locate the installed AGILab package path on disk."""

        for p in sys.path_importer_cache:
            if p.endswith("agi_env"):
                base_dir = p
        before, sep, after = base_dir.rpartition("agilab")
        if AgiEnv.install_type == 0:
            return base_dir.parent
        else:
            return Path(before) / sep

    def copy_existing_projects(self, src_apps: Path, dst_apps: Path):
        """Copy ``*_project`` trees from ``src_apps`` into ``dst_apps`` if missing."""

        dst_apps.mkdir(parents=True, exist_ok=True)

        # match every nested directory ending with "_project"
        for item in src_apps.rglob("*_project"):
            if not item.is_dir():
                continue

            rel = item.relative_to(src_apps)  # keep nested structure
            dst_item = dst_apps / rel
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
        env_file = AgiEnv.resources_path / ".env"
        for k, v in updates.items():
            set_key(str(env_file), k, str(v), quote_mode="never")

    def _init_resources(self, resources_src):
        """Replicate ``resources_src`` into the managed ``.agilab`` tree."""

        src_env_path = resources_src / ".env"
        dest_env_file = AgiEnv.resources_path / ".env"
        if not src_env_path.exists():
            msg = f"Installation issue: {src_env_path} is missing!"
            AgiEnv.logger.info(msg)
            raise RuntimeError(msg)
        if not dest_env_file.exists():
            os.makedirs(dest_env_file.parent, exist_ok=True)
            shutil.copy(src_env_path, dest_env_file)
        for root, dirs, files in os.walk(resources_src):
            for file in files:
                src_file = Path(root) / file
                relative_path = src_file.relative_to(resources_src)
                dest_file = AgiEnv.resources_path / relative_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if not dest_file.exists():
                    shutil.copy(src_file, dest_file)

    def _init_projects(self):
        """Identify available projects and align state with the selected target."""

        self.projects = self.get_projects(self.apps_dir)
        for idx, project in enumerate(self.projects):
            if self.target == project[:-8].replace("-", "_"):
                self.active_app = AgiEnv.apps_dir / project
                self.app = project
                break

    def get_projects(self, path: Path):
        """Return the names of ``*_project`` directories beneath ``path``."""

        return [p.name for p in path.glob("*project")]

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
        self.runenv = AgiEnv.examples
        AGILAB_EXPORT_ABS = Path(envars.get("AGI_EXPORT_DIR", self.home_abs / "export"))
        if not AGILAB_EXPORT_ABS.exists():
            AGILAB_EXPORT_ABS.mkdir(parents=True)
        self.AGILAB_EXPORT_ABS = AGILAB_EXPORT_ABS
        self.export_apps = AGILAB_EXPORT_ABS / "apps"
        if not self.export_apps.exists():
            os.makedirs(str(self.export_apps), exist_ok=True)
        self.MLFLOW_TRACKING_DIR = Path(envars.get("MLFLOW_TRACKING_DIR", self.home_abs / ".mlflow"))
        self.AGILAB_PAGES_ABS = Path(envars.get("AGI_PAGES_DIR", self.agilab_src / "agilab/apps-pages"))
        if AgiEnv.install_type == 0:
            self.copilot_file = self.agilab_src / "agi_codex.py" # WTF ?
        else:
            self.copilot_file = self.agilab_src / "agi_codex.py"


    @staticmethod
    def _copy_file(src_item, dst_item):
        """Copy ``src_item`` to ``dst_item`` if the destination does not exist."""

        if not dst_item.exists():
            if not src_item.exists():
                AgiEnv.logger.info(f"[WARN] Source file missing (skipped): {src_item}")
                return
            try:
                shutil.copy2(src_item, dst_item)
            except Exception as e:
                AgiEnv.logger.error(f"[WARN] Could not copy {src_item} → {dst_item}: {e}")

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
        dest = AgiEnv.resources_path
        src = self.agilab_src / "resources"
        if src.exists():
            for file in src.iterdir():
                if not file.is_file():
                    continue
                dest_file = dest / file.name
                if dest_file.exists():
                    continue
                shutil.copy2(file, dest_file)
        # shutil.copytree(self.agilab_src / "resources", dest, dirs_exist_ok=True)


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

        extra_paths = list(AgiEnv._pythonpath_entries)
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
        if AgiEnv.verbose > 0:
            AgiEnv.logger.info(f"@{venv.name}: {cmd}")

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
                        callback(msg, extra={"subprocess": True})
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

                await asyncio.wait_for(asyncio.gather(
                    read_stream(proc.stdout, log_callback if log_callback else AgiEnv.logger.info),
                    read_stream(proc.stderr, log_callback if log_callback else AgiEnv.logger.error),
                ), timeout=timeout)

                returncode = await proc.wait()

                if returncode != 0:
                    # Promote to ERROR with context even if lines were logged as INFO
                    AgiEnv.logger.error("Command failed with exit code %s: %s", returncode, cmd)
                    sys.exit(returncode)

                return "\n".join(result)
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError(f"Command timed out after {timeout} seconds: {cmd}")
            except Exception as e:
                AgiEnv.logger.error(traceback.format_exc())
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
    async def _run_bg(cmd, cwd=".", venv=None, timeout=None, log_callback=None):
        """
        Run the given command asynchronously, reading stdout and stderr line by line
        and passing them to the log_callback. Returns (stdout, stderr) as strings.
        """
        process_env = AgiEnv._build_env(venv)
        process_env["PYTHONUNBUFFERED"] = "1"

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
                if callback is AgiEnv.logger.info or callback is AgiEnv.logger.error:
                    callback(msg, extra={"subprocess": True})
                else:
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
            AgiEnv.logger.error("Command failed with exit code %s: %s", returncode, cmd)
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
        snippet_file = os.path.join(self.runenv, f"{matches[0]}_{self.target}.py")
        with open(snippet_file, "w") as file:
            file.write(code)
        pip_prefix = getattr(self, "pip_prefix", getattr(AgiEnv, "pip_prefix", ""))
        cmd = f"{AgiEnv.export_local_bin}{pip_prefix}uv run --no-sync --project {str(venv)} python {snippet_file}"
        result = await AgiEnv._run_bg(cmd, cwd=venv, log_callback=log_callback)
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
        if AgiEnv.verbose > 0:
            AgiEnv.logger.info(f"Executing in {venv}: {cmd}")

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
                if callback is AgiEnv.logger.info or callback is AgiEnv.logger.error:
                    callback(msg, extra={"subprocess": True})
                else:
                    callback(msg)
                result.append(msg)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(proc.stdout, log_callback if log_callback else AgiEnv.logger.info),
                    read_stream(proc.stderr, log_callback if log_callback else AgiEnv.logger.info),
                    proc.wait(),
                ),
                timeout=timeout,
            )
        except Exception as err:
            proc.kill()
            AgiEnv.logger.error(f"Error during: {cmd}")
            AgiEnv.logger.error(err)
            sys.exit(1)

        rc = proc.returncode
        if rc != 0:
            AgiEnv.logger.error("Command failed with exit code %s: %s", rc, cmd)
            sys.exit(rc)

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
                    AgiEnv.logger.info(f"Symlink already exists and is correct: {dest} -> {src}")
                    return
                AgiEnv.logger.warning(f"Warning: Destination already exists and is not a symlink: {dest}")
                dest.unlink()
            dest.symlink_to(src, target_is_directory=src.is_dir())
            AgiEnv.logger.info(f"Symlink created: @{dest.name} -> {src}")
        except Exception as e:
            AgiEnv.logger.error(f"Failed to create symlink @{dest} -> {src}: {e}")

    def change_active_app(self, app, install_type=1):
        if not isinstance(app, Path):
            app = Path(app)
        app = app.expanduser()

        current_name = None
        if getattr(self, "active_app", None):
            current_name = Path(self.active_app).name

        if app.name == current_name:
            return

        apps_dir = getattr(self, "apps_dir", None) or AgiEnv.apps_dir
        app_path = app if app.is_absolute() else apps_dir / app

        try:
            self.__init__(active_app=app_path, install_type=install_type, verbose=AgiEnv.verbose)
        except Exception:
            if app_path.exists():
                shutil.rmtree(app_path, ignore_errors=True)
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
            AgiEnv.logger.info(f"Created junction: {dest} -> {source}")
        except subprocess.CalledProcessError as e:
            AgiEnv.logger.error(f"Failed to create junction. Error: {e}")

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
            AgiEnv.logger.info(
                "Creating symbolic links on Windows requires administrative privileges or Developer Mode enabled."
            )
            return

        flags = SYMBOLIC_LINK_FLAG_DIRECTORY

        success = CreateSymbolicLink(str(dest), str(source), flags)
        if success:
            AgiEnv.logger.info(f"Created symbolic link for .venv: {dest} -> {source}")
        else:
            error_code = ctypes.GetLastError()
            AgiEnv.logger.info(
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
        templates_root = AgiEnv.apps_dir / "templates"
        if not target_project.name.endswith("_project"):
            candidate = target_project.with_name(target_project.name + "_project")
            if (AgiEnv.apps_dir / candidate).exists() or (templates_root / candidate).exists():
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
        source_root = AgiEnv.apps_dir / target_project
        if not source_root.exists() and templates_root.exists():
            source_root = templates_root / target_project
        dest_root   = AgiEnv.apps_dir / dest_project

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
                AgiEnv.logger.info("Destination '{dataset}' exists and is not empty. Clearing it before extraction.")
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
            sys.exit(1)

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
