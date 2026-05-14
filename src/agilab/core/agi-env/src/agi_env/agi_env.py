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
----------------------------------------
- ``AgiEnv`` behaves as a true singleton. Instance attributes are the source of
  truth; class attribute reads proxy to the singleton instance when initialised.
  Methods and descriptors are never shadowed by the delegation.
- A small subset of helpers is pre‑init safe and can be used before constructing
  an instance: :func:`AgiEnv.set_env_var`, :func:`AgiEnv.read_agilab_path`,
  ``AgiEnv._build_env``, and :func:`AgiEnv.log_info`. These functions avoid
  hard failures when the shared logger/environment has not been configured yet.
  Logging in that mode is best‑effort and may fall back to ``print``.
"""
try:
    from IPython.core.ultratb import FormattedTB
except (ImportError, AttributeError):  # Optional dependency; fallback if absent
    FormattedTB = None  # type: ignore
import ast
import errno
import getpass
import os
import re
import shutil
import psutil
import socket
import subprocess
import sys
from pathlib import Path
import tomlkit
from typing import Tuple
import logging
import astor
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
import py7zr
import urllib.request
import uuid
import inspect
import ctypes
from ctypes import wintypes
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from agi_env.defaults import get_default_openai_model
from agi_env.app_settings_support import (
    app_settings_aliases,
    app_settings_source_roots,
    candidate_app_settings_path,
    find_source_app_settings_file as find_versioned_app_settings_file,
    resolve_user_app_settings_file as resolve_workspace_app_settings_file,
)
from agi_env.connector_registry import resolve_connector_root
from agi_env.app_provider_registry import resolve_app_runtime_target
from agi_env.env_config_support import (
    clean_envar_value as _clean_envar_value,
    load_dotenv_values as _load_dotenv_values,
    write_env_updates,
)
from agi_env.hook_support import resolve_worker_hook, select_hook
from agi_env.installation_support import (
    installation_marker_path,
    locate_agilab_installation_path,
    read_agilab_installation_marker,
)
from agi_env.package_layout_support import (
    resolve_agilab_package_context,
    resolve_package_layout,
    resolve_resource_root,
)
from agi_env.runtime_bootstrap_support import (
    parse_int_env_value,
    resolve_share_runtime_config,
    sync_repository_apps,
)
from agi_env.worker_runtime_support import configure_worker_runtime
from agi_env.process_support import (
    build_subprocess_env,
    fix_windows_drive as _fix_windows_drive,
    is_packaging_cmd,
    normalize_path,
    parse_level,
)
from agi_env.repository_support import (
    collect_pythonpath_entries as build_pythonpath_entries,
    configure_pythonpath as apply_pythonpath_entries,
    dedupe_existing_paths,
    get_apps_repository_root as resolve_apps_repository_root,
    resolve_package_root,
)
from agi_env.share_runtime_support import (
    is_valid_ip as is_valid_ipv4_address,
    mode_to_int,
    mode_to_str,
    resolve_share_path as resolve_relative_share_path,
    share_target_name,
    python_supports_free_threading,
)
from agi_env.share_mount_support import (
    cluster_enabled_from_settings as resolve_cluster_enabled_from_settings,
    resolve_share_path as resolve_runtime_share_path,
)
from agi_env.rename_gitignore_support import (
    is_relative_to as is_path_relative_to,
    load_gitignore_spec,
    replace_text_content,
)
from agi_env.content_renamer_support import ContentRenamer as BaseContentRenamer
from agi_env.bootstrap_support import (
    can_link_repo_apps,
    coerce_active_app_request,
    resolve_active_app_selection,
    resolve_builtin_apps_path,
    resolve_default_apps_path,
    resolve_install_type,
    resolve_package_dir,
    resolve_requested_apps_path,
)
from agi_env.app_provider_registry import installed_app_project_paths
from agi_env.credential_store_support import read_cluster_credentials
from agi_env.source_analysis_support import (
    extract_base_info as extract_ast_base_info,
    get_full_attribute_name as build_full_attribute_name,
    get_import_mapping as build_import_mapping,
)
from agi_env.worker_source_support import (
    get_base_classes as discover_base_classes,
    get_base_worker_cls as discover_base_worker_cls,
)
from agi_env.project_clone_support import (
    cleanup_rename as cleanup_project_rename,
    clone_directory as clone_project_directory,
    clone_project as clone_app_project,
    copy_existing_projects as copy_missing_projects,
    create_rename_map as build_clone_rename_map,
)
from agi_env.data_archive_support import unzip_data as extract_dataset_archive
from agi_env.execution_support import (
    run as run_command_in_env,
    run_agi as run_agi_snippet,
    run_async as run_command_async,
    run_bg as run_command_in_background,
)
import inspect as _inspect
try:
    import pwd
except ImportError:  # Windows
    pwd = None  # type: ignore
if FormattedTB is not None:
    # Get constructor parameters of FormattedTB
    _sig = inspect.signature(FormattedTB.__init__).parameters

    _call_pdb = bool(getattr(sys.stdin, "isatty", lambda: False)())
    if "AGILAB_CALL_PDB" in os.environ:
        _call_pdb = os.environ["AGILAB_CALL_PDB"].strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    _tb_kwargs = dict(mode='Verbose', call_pdb=_call_pdb)
    if 'color_scheme' in _sig:
        _tb_kwargs['color_scheme'] = 'NoColor'
    else:
        _tb_kwargs['theme_name'] = 'NoColor'

    sys.excepthook = FormattedTB(**_tb_kwargs)

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)


def _optional_agi_pages_bundles_root() -> Path | None:
    """Return the optional agi-pages bundle root without making it a hard dependency."""

    if importlib.util.find_spec("agi_pages") is None:
        return None
    try:
        import agi_pages  # type: ignore
    except (ImportError, AttributeError, TypeError, OSError):
        return None
    bundles_root = getattr(agi_pages, "bundles_root", None)
    if not callable(bundles_root):
        return None
    try:
        return Path(bundles_root()).expanduser()
    except (TypeError, OSError, RuntimeError):
        return None


def _ensure_dir(path: str | Path) -> Path:
    """Create a directory if missing and log only when it is first created."""
    target = Path(path)
    if not target.exists():
        logger.info(f"mkdir {target}")
        target.mkdir(parents=True, exist_ok=True)
    return target


def _resolve_worker_hook(filename: str) -> Path | None:
    """Return the path to the shared worker hook."""
    return resolve_worker_hook(filename, module_file=__file__)


_resolve_worker_hook.cache_clear = resolve_worker_hook.cache_clear  # type: ignore[attr-defined]


def _select_hook(local_candidate: Path, fallback_filename: str, hook_label: str) -> tuple[Path, bool]:
    """Return the hook to execute and whether it comes from the shared baseline."""
    return select_hook(
        local_candidate,
        fallback_filename,
        hook_label,
        resolve_hook=_resolve_worker_hook,
    )

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
    apps_path = None
    app = None
    target = None
    TABLE_MAX_ROWS = None
    GUI_SAMPLING = None
    init_done = False
    hw_rapids_capable = None
    is_worker_env = False
    _is_managed_pc = None
    skip_repo_links = False
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
    _share_mount_warning_keys: set[tuple[str, str]] = set()
    INDEX_URL="https://test.pypi.org/simple"
    EXTRA_INDEX_URL="https://pypi.org/simple"
    snippet_tail = "asyncio.get_event_loop().run_until_complete(main())"
    _pythonpath_entries: list[str] = []

    def __init__(self,
                 apps_path: Path | None = None,
                 app: str | None = None,
                 verbose: int | None = None,
                 debug: bool = False,
                 python_variante: str = '',
                 **kwargs):

        app, active_app_override = coerce_active_app_request(app, kwargs, path_cls=Path)

        self.skip_repo_links = False
        self.AGILAB_SHARE_HINT = None
        self.AGILAB_SHARE_REL = None

        self.is_managed_pc = getpass.getuser().startswith("T0")
        self._is_managed_pc = self.is_managed_pc
        self._agi_resources = Path("resources/.agilab")
        home_abs = Path.home() / "MyApp" if self.is_managed_pc else Path.home()
        self.home_abs = home_abs
        self._share_root_cache: Path | None = None

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
        self.envars = _load_dotenv_values(env_path, verbose=verbose)
        logger.debug(f"env path: {env_path}")
        envars = self.envars
        repo_agilab_dir = Path(__file__).resolve().parents[4]

        # Propagate Streamlit message size from AgiEnv env vars to runtime env to avoid local config writes.
        streamlit_size = envars.get("STREAMLIT_SERVER_MAX_MESSAGE_SIZE") or envars.get(
            "STREAMLIT_MAX_MESSAGE_SIZE"
        )
        if streamlit_size:
            os.environ.setdefault("STREAMLIT_SERVER_MAX_MESSAGE_SIZE", str(streamlit_size))
            os.environ.setdefault("STREAMLIT_MAX_MESSAGE_SIZE", str(streamlit_size))

        package_context = resolve_agilab_package_context(
            repo_agilab_dir=repo_agilab_dir,
            find_spec_fn=importlib.util.find_spec,
            path_cls=Path,
        )
        agilab_pkg_dir = package_context.package_dir
        agilab_pck = package_context.apps_root_hint
        is_agilab_installed = package_context.is_installed

        env_apps_path = str(envars.get("APPS_PATH", "") or "").strip()
        apps_path, override_builtin_apps_path = resolve_requested_apps_path(
            env_apps_path=env_apps_path,
            explicit_apps_path=apps_path,
            active_app_override=active_app_override,
            path_cls=Path,
        )

        # Honour env flags when present
        env_is_source = envars.get("IS_SOURCE_ENV")
        env_is_worker = envars.get("IS_WORKER_ENV")
        if env_is_source is not None:
            try:
                is_agilab_installed = not bool(int(env_is_source))
            except (TypeError, ValueError):
                is_agilab_installed = str(env_is_source).lower() in {"false", "0", "no", ""}  # default False-ish
            self.is_source_env = not is_agilab_installed
        if env_is_worker is not None:
            try:
                self.is_worker_env = bool(int(env_is_worker))
            except (TypeError, ValueError):
                self.is_worker_env = str(env_is_worker).lower() not in {"false", "0", "no", ""}

        install_type, inferred_worker_env = resolve_install_type(
            apps_path,
            active_app_override=active_app_override,
        )
        if env_is_source is None and install_type == 1:
            self.is_source_env = True
        if env_is_worker is None and install_type == 2:
            self.is_worker_env = True
        if inferred_worker_env:
            self.is_worker_env = True
        if self.is_worker_env:
            self.skip_repo_links = True

        repo_root = agilab_pck.parents[1] if len(agilab_pck.parents) > 1 else agilab_pck
        self.builtin_apps_path = override_builtin_apps_path or resolve_builtin_apps_path(
            apps_path=apps_path,
            repo_root=repo_root,
            agilab_pck=agilab_pck,
        )

        # Default apps_path for non-worker envs when not provided
        repo_apps = self._get_apps_repository_root()
        default_apps_root = agilab_pck / "apps"
        apps_path, apps_repository_root = resolve_default_apps_path(
            apps_path=apps_path,
            is_worker_env=self.is_worker_env,
            default_apps_root=default_apps_root,
            apps_repository_root=repo_apps,
        )
        self.apps_repository_root = apps_repository_root or repo_apps
        self.installed_app_project_paths = installed_app_project_paths()

        active_app_selection = resolve_active_app_selection(
            app=app,
            active_app_override=active_app_override,
            apps_path=apps_path,
            builtin_apps_path=self.builtin_apps_path,
            installed_app_projects=self.installed_app_project_paths,
            home_abs=home_abs,
            is_worker_env=self.is_worker_env,
            default_app=str(envars.get("APP_DEFAULT", "flight_telemetry_project") or "").strip(),
            path_cls=Path,
        )
        app = active_app_selection.app
        active_app = active_app_selection.active_app

        if not app.endswith('_project') and not app.endswith('_worker'):
            raise ValueError(f"{app} must end with '_project' or '_worker'")

        # If apps_path contains a builtin subdir, prefer that as the builtin root.
        if apps_path and (apps_path / "builtin").exists():
            self.builtin_apps_path = apps_path / "builtin"

        self.app = app
        try:
            self.active_app = active_app.resolve()
        except OSError:
            self.active_app = active_app
        self.apps_path = apps_path

        target = resolve_app_runtime_target(active_app, app)
        self.share_target_name = target

        self.verbose = verbose
        self.python_variante = python_variante
        self.logger = AgiLogger.configure(verbose=verbose, base_name="agi_env")
        self.debug = debug

        # Keep resolved flags from env/config/layout detection above.
        self.is_local_worker = False
        # Backward-compat: map booleans to legacy install_type
        self.install_type = 1 if self.is_source_env else (2 if self.is_worker_env else 0)

        package_layout = resolve_package_layout(
            is_source_env=self.is_source_env,
            repo_agilab_dir=repo_agilab_dir,
            installed_package_dir=agilab_pkg_dir,
            resolve_package_dir_fn=resolve_package_dir,
            find_spec_fn=importlib.util.find_spec,
            path_cls=Path,
        )
        self.agilab_pck = package_layout.agilab_pck
        self.env_pck = package_layout.env_pck
        self.node_pck = package_layout.node_pck
        self.core_pck = package_layout.core_pck
        self.cluster_pck = package_layout.cluster_pck
        self.cli = package_layout.cli

        resolve = self._resolve_package
        self.env_pck = resolve(self.env_pck)
        self.node_pck = resolve(self.node_pck)
        self.core_pck = resolve(self.core_pck)
        self.cluster_pck = resolve(self.cluster_pck)
        self.agi_env = self.env_pck.parents[1]
        self.agi_node = self.node_pck.parents[1]
        self.agi_core = self.core_pck.parents[1]
        self.agi_cluster = self.cluster_pck.parents[1]

        self.st_resources = resolve_resource_root(self.agilab_pck, path_cls=Path)

        apps_root = self.agilab_pck / "apps"
        can_link_repo = can_link_repo_apps(
            apps_path=apps_path,
            active_app=self.active_app,
            builtin_apps_path=self.builtin_apps_path,
            is_worker_env=self.is_worker_env,
            skip_repo_links=self.skip_repo_links,
        )
        sync_repository_apps(
            can_link_repo=can_link_repo,
            apps_path=apps_path,
            apps_root=apps_root,
            active_app=active_app,
            is_source_env=self.is_source_env,
            apps_repository_root=self.apps_repository_root,
            get_apps_repository_root_fn=self._get_apps_repository_root,
            ensure_dir_fn=_ensure_dir,
            copy_existing_projects_fn=self.copy_existing_projects,
            create_symlink_windows_fn=AgiEnv.create_symlink_windows,
            symlink_fn=os.symlink,
            logger=AgiEnv.logger,
            os_name=os.name,
            path_cls=Path,
        )


        # Resource seed files (.agilab/.env, balancer assets) always live under
        # the agi_env package tree, regardless of install mode.
        resources_root = self.env_pck
        if not self.is_worker_env:
            self._init_resources(resources_root / self._agi_resources)
        self.TABLE_MAX_ROWS = parse_int_env_value(envars, "TABLE_MAX_ROWS", 1000000)
        self.GUI_SAMPLING = parse_int_env_value(envars, "GUI_SAMPLING", 20)

        self._configure_worker_runtime(
            target=target,
            home_abs=home_abs,
            apps_path=apps_path,
            apps_root=apps_root,
            envars=envars,
            requested_active_app=active_app,
        )

        share_runtime_config = resolve_share_runtime_config(
            envars=envars,
            environ=os.environ,
            is_worker_env=self.is_worker_env,
            resolve_workspace_settings_fn=lambda: self.resolve_user_app_settings_file(ensure_exists=False),
            find_source_settings_fn=self.find_source_app_settings_file,
            clean_envar_value_fn=_clean_envar_value,
            resolve_cluster_enabled_fn=resolve_cluster_enabled_from_settings,
            resolve_runtime_share_path_fn=resolve_runtime_share_path,
            env_path=env_path,
            home_path=Path.home(),
        )
        self.AGI_LOCAL_SHARE = share_runtime_config.local_share
        self.AGI_CLUSTER_SHARE = share_runtime_config.cluster_share
        self.agi_share_path = share_runtime_config.agi_share_path
        self._share_root_cache = None

        share_root_abs = self.share_root_path()
        share_target_name = self._share_target_name()
        self.share_target_name = share_target_name
        self.agi_share_path_abs = share_root_abs
        self.app_data_rel = share_root_abs / share_target_name
        self.dataframe_path = self.app_data_rel / "dataframe"

        if self.is_worker_env:
            self.user = "agi"
            return

        if self.worker_path.exists():
            self.base_worker_cls, self._base_worker_module = self.get_base_worker_cls(
                self.worker_path, self.target_worker_class
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
        ssh_key_env = envars.get("AGI_SSH_KEY_PATH", "")
        ssh_key_env = ssh_key_env.strip() if isinstance(ssh_key_env, str) else ""
        self.ssh_key_path = str(Path(ssh_key_env).expanduser()) if ssh_key_env else None

        self.projects = self.get_projects(self.apps_path, self.builtin_apps_path)
        if not self.projects:
            AgiEnv.logger.info(f"Could not find any target project app in {self.agilab_pck / 'apps'}.")

        self.setup_app = self.active_app / "build.py"
        self.setup_app_module = "agi_node.agi_dispatcher.build"

        self._init_projects()

        self.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
        if not self.is_valid_ip(self.scheduler_ip):
            raise ValueError(f"Invalid scheduler IP address: {self.scheduler_ip}")

        if self.is_source_env:
            self.help_path = str(self.agilab_pck.parents[1] / "docs/html")
        else:
            self.help_path = "https://thalesgroup.github.io/agilab"
        # Ensure packaged datasets are available when running locally (e.g. app_test).
        dataset_archive = getattr(self, "dataset_archive", None)
        if not self.is_worker_env and dataset_archive and Path(dataset_archive).exists():
            dataset_root = (Path(self.app_data_rel) / "dataset").expanduser()
            archive_mtime = Path(dataset_archive).stat().st_mtime
            stamp_path = dataset_root / ".agilab_dataset_stamp"

            existing_files = (
                [p for p in dataset_root.rglob("*") if p.is_file() and p != stamp_path]
                if dataset_root.exists()
                else []
            )

            if not existing_files:
                needs_extract = True
            elif stamp_path.exists():
                try:
                    needs_extract = stamp_path.stat().st_mtime < archive_mtime
                except OSError:
                    needs_extract = False
            else:
                # No stamp file means the dataset was created by an older AGILAB version
                # or manually by the user. Avoid clobbering existing content; use
                # AGILAB_FORCE_DATA_REFRESH=1 if a rebuild is required.
                needs_extract = False
            if needs_extract:
                try:
                    self.unzip_data(Path(dataset_archive), self.app_data_rel, force_extract=True)
                except (OSError, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover - defensive guard
                    AgiEnv.logger.warning(
                        "Failed to extract packaged dataset %s: %s",
                        dataset_archive,
                        exc,
                    )

        _ensure_dir(self.app_src)
        app_src_str = str(self.app_src)
        if app_src_str not in sys.path:
            sys.path.append(app_src_str)

        # Populate examples/apps in standard environments
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
        return resolve_package_root(root)

    def _get_apps_repository_root(self) -> Path | None:
        return resolve_apps_repository_root(
            envars=self.envars,
            environ=os.environ,
            logger=AgiEnv.logger,
            fix_windows_drive_fn=_fix_windows_drive,
        )

    def _collect_pythonpath_entries(self) -> list[str]:
        return build_pythonpath_entries(
            env_pck=self.env_pck,
            node_pck=self.node_pck,
            core_pck=self.core_pck,
            cluster_pck=self.cluster_pck,
            dist_abs=self.dist_abs,
            app_src=self.app_src,
            wenv_abs=self.wenv_abs,
            agilab_pck=self.agilab_pck,
            dedupe_paths_fn=self._dedupe_paths,
        )

    def _configure_pythonpath(self, entries: list[str]) -> None:
        self._pythonpath_entries = entries
        apply_pythonpath_entries(entries, sys_path=sys.path, environ=os.environ)

    def _configure_worker_runtime(
        self,
        *,
        target: str,
        home_abs: Path,
        apps_path: Path | None,
        apps_root: Path,
        envars: dict,
        requested_active_app: Path,
    ) -> None:
        configure_worker_runtime(
            self,
            target=target,
            home_abs=home_abs,
            apps_path=apps_path,
            apps_root=apps_root,
            envars=envars,
            requested_active_app=requested_active_app,
            ensure_dir_fn=_ensure_dir,
            normalize_path_fn=normalize_path,
            parse_int_env_value_fn=parse_int_env_value,
            python_supports_free_threading_fn=python_supports_free_threading,
            logger=AgiEnv.logger,
            sys_path=sys.path,
        )

    @staticmethod
    def _dedupe_paths(paths) -> list[str]:
        return dedupe_existing_paths(paths)

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
            field = ".".join(str(loc) for loc in err["loc"]) or "(model)"
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

    # ------------------------------------------------------------------
    # Shared storage helpers
    # ------------------------------------------------------------------
    def share_root_path(self) -> Path:
        """Return the absolute path corresponding to ``agi_share_path``."""

        if self._share_root_cache is not None:
            return self._share_root_cache

        share = self.agi_share_path
        if not share:
            raise RuntimeError("agi_share_path is not configured; cannot resolve shared storage path.")

        share_path = Path(share).expanduser()
        if not share_path.is_absolute():
            base = Path.home()
            env_home = self.home_abs
            # Worker environments inherit persisted metadata from the manager.
            # Prefer the runtime home directory so relative shares resolve on the worker.
            if env_home and not self.is_worker_env:
                base = Path(env_home)
            share_path = Path(base).expanduser() / share_path

        share_path = share_path.resolve(strict=False)
        self._share_root_cache = share_path
        return share_path

    def _share_target_name(self) -> str:
        """Return the logical app name for share paths (strip *_project/_worker)."""
        return share_target_name(self.target, self.app)

    def resolve_share_path(self, path: str | Path | None) -> Path:
        """
        Resolve ``path`` relative to the shared storage root.

        ``None`` or ``"."`` returns the root itself; absolute inputs pass through unchanged.
        """
        return resolve_relative_share_path(path, self.share_root_path())

    @classmethod
    def _ensure_defaults(cls):
        """Ensure minimal class-level defaults exist for limited static usage."""
        if getattr(cls, "resources_path", None) is None:
            try:
                cls.resources_path = Path.home() / ".agilab"
            except (OSError, RuntimeError):
                cls.resources_path = Path(".agilab").resolve()
        if getattr(cls, "envars", None) is None or not isinstance(cls.envars, dict):
            try:
                env_path = cls.resources_path / ".env"
                cls.envars = _load_dotenv_values(env_path, verbose=False)
            except (OSError, RuntimeError, TypeError, ValueError):
                cls.envars = {}

    @staticmethod
    def read_agilab_path(verbose=False):
        """Return the persisted AGILab installation path if previously recorded."""
        marker = installation_marker_path(
            os_name=os.name,
            home=Path.home(),
            localappdata=os.getenv("LOCALAPPDATA", ""),
        )
        return read_agilab_installation_marker(marker, logger=AgiEnv.logger)

    @staticmethod
    def locate_agilab_installation(verbose=False):
        """Attempt to locate the installed AGILab package path on disk."""
        return locate_agilab_installation_path(
            module_file=__file__,
            find_spec=importlib.util.find_spec,
        )

    # Backwards-compatible alias kept for older tests and scripts
    @staticmethod
    def locate_agi_installation(verbose=False):
        """Deprecated alias for locate_agilab_installation()."""
        return AgiEnv.locate_agilab_installation(verbose=verbose)

    def copy_existing_projects(self, src_apps: Path, dst_apps: Path):
        """Copy ``*_project`` trees from ``src_apps`` into ``dst_apps`` if missing."""
        copy_missing_projects(
            src_apps,
            dst_apps,
            ensure_dir_fn=_ensure_dir,
            logger=AgiEnv.logger,
        )

    # Simplified: keep single copy_missing implementation defined later using _copy_file

    def _update_env_file(updates: dict):
        AgiEnv._ensure_defaults()
        env_file = AgiEnv.resources_path / ".env"
        write_env_updates(env_file, updates)

    def _init_resources(self, resources_src):
        """Replicate ``resources_src`` into the managed ``.agilab`` tree."""

        src_env_path = resources_src / ".env"
        dest_env_file = self.resources_path / ".env"
        if not dest_env_file.exists():
            _ensure_dir(dest_env_file.parent)
            shutil.copy(src_env_path, dest_env_file)
        for root, dirs, files in os.walk(resources_src):
            for file in files:
                src_file = Path(root) / file
                relative_path = src_file.relative_to(resources_src)
                dest_file = self.resources_path / relative_path
                _ensure_dir(dest_file.parent)
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
                    _ensure_dir(dest_extra.parent)
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

        if self.apps_repository_root is None:
            self.apps_repository_root = self._get_apps_repository_root()

        self.projects = self.get_projects(self.apps_path, self.builtin_apps_path, self.apps_repository_root)
        for idx, project in enumerate(self.projects):
            if self.target == project[:-8].replace("-", "_"):
                self.app = self.apps_path / project
                self.app = project
                break

    def get_projects(self, *paths: Path):
        """Return the names of ``*_project`` directories beneath the provided paths."""

        projects: list[str] = []
        seen: set[str] = set()

        for path in paths:
            if path is None:
                continue
            try:
                base = Path(path)
            except (TypeError, ValueError):
                continue
            if not base.exists():
                continue

            for project_path in sorted(base.glob("*_project"), key=lambda candidate: candidate.name):
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
                    name = project_path.name
                    if name not in seen:
                        projects.append(name)
                        seen.add(name)

        for project_path in sorted(getattr(self, "installed_app_project_paths", ()), key=lambda candidate: candidate.name):
            try:
                name = Path(project_path).name
            except (TypeError, ValueError):
                continue
            if name.endswith("_project") and name not in seen:
                projects.append(name)
                seen.add(name)

        return projects

    def get_base_worker_cls(self, module_path, class_name):
        """Return the base worker class name and module for ``class_name``."""
        return discover_base_worker_cls(
            module_path,
            class_name,
            logger=AgiEnv.logger,
            get_base_classes_fn=self.get_base_classes,
        )

    def get_base_classes(self, module_path, class_name):
        """Inspect ``module_path`` AST to retrieve base classes of ``class_name``."""
        return discover_base_classes(
            module_path,
            class_name,
            logger=AgiEnv.logger,
            import_mapping_fn=self.get_import_mapping,
            extract_base_info_fn=self.extract_base_info,
        )

    def get_import_mapping(self, source):
        """Build a mapping of names to modules from ``import`` statements in ``source``."""
        return build_import_mapping(source, logger=AgiEnv.logger)

    def _ensure_repository_app_link(self) -> bool:
        """Create a symlink to a repository app when the public tree is missing it."""

        link_root = self._get_apps_repository_root()
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
        AgiEnv.logger.info("Created apps repository symlink: %s -> %s", dest, candidate)
        return True

    @staticmethod
    def _app_settings_aliases(app_name: str | None) -> set[str]:
        """Return common project/worker aliases for ``app_name``."""
        return app_settings_aliases(app_name)

    @staticmethod
    def _candidate_app_settings_path(base: object) -> Path | None:
        """Return a safe candidate path for ``app_settings.toml`` or ``None``."""
        return candidate_app_settings_path(base)

    def _app_settings_source_roots(self, app_name: str | None = None) -> list[Path]:
        """Collect source roots that may contain ``app_settings.toml`` for an app."""
        return app_settings_source_roots(
            target_app=app_name or self.app,
            current_app=self.app,
            app_src=self.app_src,
            active_app=self.active_app,
            apps_path=self.apps_path,
            builtin_apps_path=self.builtin_apps_path,
            apps_repository_root=self.apps_repository_root or self._get_apps_repository_root(),
            home_abs=self.home_abs,
            envars=self.envars,
        )

    def find_source_app_settings_file(self, app_name: str | None = None) -> Path | None:
        """Return the versioned/source ``app_settings.toml`` for an app when available."""
        return find_versioned_app_settings_file(
            target_app=app_name or self.app,
            current_app=self.app,
            app_src=self.app_src,
            active_app=self.active_app,
            apps_path=self.apps_path,
            builtin_apps_path=self.builtin_apps_path,
            apps_repository_root=self.apps_repository_root or self._get_apps_repository_root(),
            home_abs=self.home_abs,
            envars=self.envars,
        )

    def resolve_user_app_settings_file(
        self,
        app_name: str | None = None,
        *,
        ensure_exists: bool = True,
    ) -> Path:
        """Return the per-user mutable ``app_settings.toml`` path for an app.

        The workspace copy lives under ``~/.agilab/apps/<app>/app_settings.toml`` and
        is seeded from the versioned source file on first use.
        """
        return resolve_workspace_app_settings_file(
            target_app=app_name or self.app or self.target,
            resources_path=self.resources_path,
            ensure_exists=ensure_exists,
            find_source_file=self.find_source_app_settings_file,
        )

    def extract_base_info(self, base, import_mapping):
        """Return the base-class name and originating module for ``base`` nodes."""
        return extract_ast_base_info(base, import_mapping)

    def get_full_attribute_name(self, node):
        """Reconstruct the dotted attribute path represented by ``node``."""
        return build_full_attribute_name(node)

    def mode2str(self, mode):
        """Encode a bitmask ``mode`` into readable ``pcdr`` flag form."""
        return mode_to_str(mode, hw_rapids_capable=self.hw_rapids_capable)

    @staticmethod
    def mode2int(mode):
        """Convert an iterable of mode flags (``p``, ``c``, ``d``) to the bitmask int."""
        return mode_to_int(mode)

    def is_valid_ip(self, ip: str) -> bool:
        """Return ``True`` when ``ip`` is a syntactically valid IPv4 address."""
        return is_valid_ipv4_address(ip)

    def init_envars_app(self, envars):
        """Cache frequently used environment variables and ensure directories exist."""

        self.CLUSTER_CREDENTIALS = read_cluster_credentials(
            envars.get("CLUSTER_CREDENTIALS", None),
            environ=os.environ,
            default_account=getpass.getuser(),
            logger=AgiEnv.logger,
        )
        if self.CLUSTER_CREDENTIALS:
            envars["CLUSTER_CREDENTIALS"] = self.CLUSTER_CREDENTIALS
        self.OPENAI_API_KEY = envars.get("OPENAI_API_KEY", None)
        self.OPENAI_MODEL = envars.get("OPENAI_MODEL") or get_default_openai_model()
        log_connector = resolve_connector_root(
            self,
            connector_id="log_root",
            label="Log root",
            attr_name="AGILAB_LOG_ABS",
            env_key="AGI_LOG_DIR",
            default_child="log",
            ensure=True,
            prefer_attr=False,
            description="Root for execution logs and run manifests.",
        )
        self.AGILAB_LOG_ABS = log_connector.path
        runenv_base = self.AGILAB_LOG_ABS / "execute"
        _ensure_dir(runenv_base)
        self.runenv = runenv_base / self.target
        _ensure_dir(self.runenv)
        export_connector = resolve_connector_root(
            self,
            connector_id="export_root",
            label="Export root",
            attr_name="AGILAB_EXPORT_ABS",
            env_key="AGI_EXPORT_DIR",
            default_child="export",
            ensure=True,
            prefer_attr=False,
            description="Root for app and page output artifacts.",
        )
        self.AGILAB_EXPORT_ABS = export_connector.path
        self.export_apps = self.AGILAB_EXPORT_ABS / "apps-zip"
        _ensure_dir(self.export_apps)
        mlflow_tracking_override = _clean_envar_value(envars, "MLFLOW_TRACKING_DIR")
        if mlflow_tracking_override:
            mlflow_tracking_dir = Path(mlflow_tracking_override).expanduser()
            if not mlflow_tracking_dir.is_absolute():
                mlflow_tracking_dir = self.home_abs / mlflow_tracking_dir
            self.MLFLOW_TRACKING_DIR = mlflow_tracking_dir
        else:
            self.MLFLOW_TRACKING_DIR = self.home_abs / ".mlflow"
        pages_override = _clean_envar_value(envars, "AGI_PAGES_DIR")
        if pages_override:
            pages_root = Path(pages_override).expanduser()
        else:
            candidates = [
                self.agilab_pck / "apps-pages",
                self.agilab_pck / "agilab/apps-pages",
            ]
            repo_hint = self.read_agilab_path()
            if repo_hint:
                repo_hint = Path(repo_hint)
                for suffix in ("apps-pages", "agilab/apps-pages"):
                    candidates.append(repo_hint / suffix)
            agi_pages_root = _optional_agi_pages_bundles_root()
            if agi_pages_root is not None:
                candidates.append(agi_pages_root)

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
                logger = AgiEnv.logger
                if logger:
                    logger.info(f"[WARN] Source file missing (skipped): {src_item}")
                return
            try:
                shutil.copy2(src_item, dst_item)
            except (OSError, shutil.Error) as e:
                logger = AgiEnv.logger
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
        app_settings_source_file = self.find_source_app_settings_file() or (self.app_src / "app_settings.toml")
        self.app_settings_source_file = app_settings_source_file
        self.app_settings_file = self.resolve_user_app_settings_file()

        app_args_form = self.app_src / "app_args_form.py"
        app_args_form.touch(exist_ok=True)
        self.app_args_form = app_args_form

        self.gitignore_file = self.active_app / ".gitignore"
        dest = self.resources_path
        src = self.agilab_pck / "resources"
        if src.exists():
            dest.mkdir(parents=True, exist_ok=True)
            for file in src.iterdir():
                if not file.is_file():
                    continue
                dest_file = dest / file.name
                if dest_file.exists():
                    continue
                shutil.copy(file, dest_file)
        # shutil.copytree(self.agilab_pck / "resources", dest, dirs_exist_ok=True)


    @staticmethod
    def _build_env(venv=None):
        """Build environment dict for subprocesses, with activated virtualenv paths."""
        instance = AgiEnv._instance
        if instance is not None and getattr(instance, "_pythonpath_entries", None):
            extra_paths = list(instance._pythonpath_entries)
        else:
            extra_paths = list(AgiEnv._pythonpath_entries)
        return build_subprocess_env(
            base_env=os.environ.copy(),
            venv=venv,
            pythonpath_entries=extra_paths,
            sys_prefix=sys.prefix,
        )

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
        """Run a shell command inside a virtual environment."""
        return await run_command_in_env(
            cmd,
            venv,
            cwd=cwd,
            timeout=timeout,
            wait=wait,
            log_callback=log_callback,
            verbose=AgiEnv.verbose or 0,
            logger=AgiEnv.logger,
            build_env_fn=AgiEnv._build_env,
        )

    @staticmethod
    async def _run_bg(cmd, cwd=".", venv=None, timeout=None, log_callback=None,
                      env_override: dict | None = None, remove_env: set[str] | None = None):
        """Run a command asynchronously and return ``(stdout, stderr)``."""
        return await run_command_in_background(
            cmd,
            cwd=cwd,
            venv=venv,
            timeout=timeout,
            log_callback=log_callback,
            env_override=env_override,
            remove_env=remove_env,
            logger=AgiEnv.logger,
            build_env_fn=AgiEnv._build_env,
        )

    async def run_agi(self, code, log_callback=None, venv: Path = None, type=None):
        """Asynchronous version of run_agi for use within an async context."""
        return await run_agi_snippet(
            code=code,
            runenv=Path(self.runenv),
            target=str(self.target),
            log_callback=log_callback,
            venv=Path(venv) if venv else None,
            run_bg_fn=AgiEnv._run_bg,
            ensure_dir_fn=_ensure_dir,
            logger=AgiEnv.logger,
            python_executable=sys.executable,
            log_info_fn=logging.info,
            snippet_type=type,
        )

    @staticmethod
    async def run_async(cmd, venv=None, cwd=None, timeout=None, log_callback=None):
        """Run a shell command asynchronously and return the last non-empty line."""
        return await run_command_async(
            cmd,
            venv=venv,
            cwd=cwd,
            timeout=timeout,
            log_callback=log_callback,
            verbose=AgiEnv.verbose or 0,
            logger=AgiEnv.logger,
            build_env_fn=AgiEnv._build_env,
        )


    @staticmethod
    def create_symlink(src: Path, dest: Path):
        try:
            if dest.exists() or dest.is_symlink():
                if dest.is_symlink() and dest.resolve() == src.resolve():
                    logger = AgiEnv.logger
                    if logger:
                        logger.info(f"Symlink already exists and is correct: {dest} -> {src}")
                    return
                logger = AgiEnv.logger
                if logger:
                    logger.warning(f"Warning: Destination already exists and is not a symlink: {dest}")
                dest.unlink()
            dest.symlink_to(src, target_is_directory=src.is_dir())
            logger = AgiEnv.logger
            if logger:
                logger.info(f"Symlink created: @{dest.name} -> {src}")
        except OSError as e:
            logger = AgiEnv.logger
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
            except (TypeError, ValueError):
                return str(value)

        # Normalize *both* current and requested app identifiers
        current_name = _app_name(getattr(self, "app", None))
        requested_name = _app_name(app)

        if not requested_name:
            raise ValueError("app name must be non-empty")

        # No-op when the requested app is already active
        if requested_name == current_name:
            return

        apps_path = None
        current_app = getattr(self, "app", None)
        try:
            current_app_path = Path(str(current_app))
            if current_app_path.name:
                apps_path = current_app_path.parent
        except (TypeError, ValueError):
            apps_path = None

        if apps_path is None:
            apps_path = getattr(self, "apps_path", None) or AgiEnv.apps_path
        if apps_path is None:
            raise RuntimeError("apps_path is not configured on AgiEnv")

        active_app = apps_path / requested_name

        try:
            type(self).__init__(
                self,
                apps_path=active_app.parent,
                app=requested_name,
                verbose=AgiEnv.verbose,
            )
        finally:
            if sys.exc_info()[0] is not None and active_app.exists():
                shutil.rmtree(active_app, ignore_errors=True)

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
        except (AttributeError, OSError, RuntimeError):
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
            logger = AgiEnv.logger
            if logger:
                logger.info(f"Created junction: {dest} -> {source}")
        except subprocess.CalledProcessError as e:
            logger = AgiEnv.logger
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
            logger = AgiEnv.logger
            if logger:
                logger.info(
                    "Creating symbolic links on Windows requires administrative privileges or Developer Mode enabled."
                )
            return

        flags = SYMBOLIC_LINK_FLAG_DIRECTORY

        success = CreateSymbolicLink(str(dest), str(source), flags)
        if success:
            logger = AgiEnv.logger
            if logger:
                logger.info(f"Created symbolic link for .venv: {dest} -> {source}")
        else:
            error_code = ctypes.GetLastError()
            logger = AgiEnv.logger
            if logger:
                logger.info(
                    f"Failed to create symbolic link for .venv. Error code: {error_code}"
                )

    def create_rename_map(self, target_project: Path, dest_project: Path) -> dict:
        """Create a mapping of old → new names for cloning."""
        return build_clone_rename_map(target_project, dest_project)

    def clone_project(self, target_project: Path, dest_project: Path):
        """Clone a project by copying files, applying renames, and final cleanup."""
        clone_app_project(
            target_project,
            dest_project,
            apps_path=self.apps_path,
            home_abs=self.home_abs,
            projects=self.projects,
            logger=AgiEnv.logger,
            create_rename_map_fn=self.create_rename_map,
            clone_directory_fn=self.clone_directory,
            cleanup_rename_fn=self._cleanup_rename,
            copytree_fn=shutil.copytree,
        )

    def clone_directory(self,
                        source_dir: Path,
                        dest_dir: Path,
                        rename_map: dict,
                        spec: PathSpec,
                        source_root: Path):
        """Recursively copy + rename directories, files, and contents."""
        clone_project_directory(
            source_dir,
            dest_dir,
            rename_map,
            spec,
            source_root,
            ensure_dir_fn=_ensure_dir,
            content_renamer_cls=ContentRenamer,
            replace_content_fn=self.replace_content,
        )

    def _cleanup_rename(self, root: Path, rename_map: dict):
        cleanup_project_rename(
            root,
            rename_map,
            replace_content_fn=self.replace_content,
        )

    def replace_content(self, txt: str, rename_map: dict) -> str:
        return replace_text_content(txt, rename_map)

    def read_gitignore(self, gitignore_path: Path) -> 'PathSpec':
        return load_gitignore_spec(gitignore_path)

    def unzip_data(
        self,
        archive_path: Path,
        extract_to: Path | str = None,
        *,
        force_extract: bool = False,
    ):
        extract_dataset_archive(
            archive_path,
            extract_to=extract_to,
            app_data_rel=self.app_data_rel,
            agi_share_path_abs=Path(self.agi_share_path_abs),
            user=self.user,
            home_abs=Path(self.home_abs),
            verbose=AgiEnv.verbose or 0,
            logger=AgiEnv.logger,
            force_extract=force_extract,
            ensure_dir_fn=_ensure_dir,
            sevenzip_file_cls=py7zr.SevenZipFile,
            rmtree_fn=shutil.rmtree,
            environ=os.environ,
        )


    @staticmethod
    def check_internet():
        AgiEnv.logger.info(f"Checking internet connectivity...")
        try:
            # HEAD request to Google
            req = urllib.request.Request("https://www.google.com", method="HEAD")
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass  # Success if no exception
        except OSError:
            AgiEnv.logger.error(f"No internet connection detected. Aborting.")
            return False
        AgiEnv.logger.info(f"Internet connection is OK.")
        return True



class ContentRenamer(BaseContentRenamer):
    """Compatibility wrapper that binds the pure renamer to ``AgiEnv.logger``."""

    def __init__(self, rename_map):
        super().__init__(rename_map, logger=AgiEnv.logger)
def _is_relative_to(path: Path, other: Path) -> bool:
    """Return ``True`` if ``path`` lies under ``other`` (without requiring Python 3.9)."""
    return is_path_relative_to(path, other)
