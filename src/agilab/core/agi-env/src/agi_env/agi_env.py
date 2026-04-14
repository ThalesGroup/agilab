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
except Exception:  # Optional dependency; fallback if absent
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
from typing import Tuple, Optional
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
)
from agi_env.rename_gitignore_support import (
    is_relative_to as is_path_relative_to,
    load_gitignore_spec,
    replace_text_content,
)
from agi_env.content_renamer_support import ContentRenamer as BaseContentRenamer
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

        # Backward/forward compat: accept 'active_app' alias for 'app'
        if app is None and 'active_app' in kwargs:
            val = kwargs.pop('active_app')
            try:
                active_app_override = Path(val)
            except Exception:
                active_app_override = None
            try:
                app = Path(val).name
            except Exception:
                app = str(val) if val is not None else None
        else:
            active_app_override = None

        self.skip_repo_links = False
        self.AGILAB_SHARE_HINT = None
        self.AGILAB_SHARE_REL = None

        def _resolve_install_type(apps_path: str | None,
                                  agilab_pck: Path,
                                  envars: dict | None,
                                  active_app_override: Path | None = None) -> int:
            """Infer install type without requiring an explicit argument.

            Precedence:
            1. honour explicit overrides from environment variables (``AGILAB_INSTALL_TYPE``
               or ``INSTALL_TYPE``) when they are valid integers;
            2. when no ``apps_path`` is provided, assume a worker-only environment (type 2);
            3. otherwise rely on the directory layout to distinguish source checkouts (type 1)
               from packaged installs (type 0), falling back to the legacy heuristic based on
               ``agilab_pck`` when needed.
            """
            try:
                # Heuristic: if apps_path is not provided (BaseWorker.new) or it resides inside a worker env folder (wenv/*_worker),
                # treat this as a worker-only environment regardless of source/layout markers.
                if active_app_override is not None and apps_path is None:
                    return 1

                if apps_path is None or "wenv" in set(apps_path.resolve().parts):
                    self.is_worker_env = True
                    return 2

                elif apps_path.parents[1].name == "src":
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

        # User's .env APPS_PATH takes priority over the constructor argument
        # so that values saved via the env editor UI are always honoured.
        _env_apps_path = envars.get("APPS_PATH", "").strip()
        if _env_apps_path:
            apps_path = Path(_env_apps_path).expanduser()
            try:
                apps_path = apps_path.resolve()
            except Exception:
                pass
        elif apps_path is not None:
            apps_path = Path(apps_path).expanduser()
            try:
                apps_path = apps_path.resolve()
            except FileNotFoundError:
                pass
        elif active_app_override is not None:
            # Use the provided active_app path as the anchor when no apps_path is supplied.
            try:
                candidate_parent = active_app_override.parent.resolve()
            except Exception:
                candidate_parent = active_app_override.parent

            # If the active_app sits under apps/builtin/<app>, keep apps_path at apps/
            if candidate_parent.name == "builtin" and candidate_parent.parent.name == "apps":
                apps_path = candidate_parent.parent
                self.builtin_apps_path = candidate_parent
            else:
                apps_path = candidate_parent

        # Honour env flags when present
        env_is_source = envars.get("IS_SOURCE_ENV")
        env_is_worker = envars.get("IS_WORKER_ENV")
        if env_is_source is not None:
            try:
                is_agilab_installed = not bool(int(env_is_source))
            except Exception:
                is_agilab_installed = str(env_is_source).lower() in {"false", "0", "no", ""}  # default False-ish
            self.is_source_env = not is_agilab_installed
        if env_is_worker is not None:
            try:
                self.is_worker_env = bool(int(env_is_worker))
            except Exception:
                self.is_worker_env = str(env_is_worker).lower() not in {"false", "0", "no", ""}

        install_type = _resolve_install_type(apps_path, agilab_pck, self.envars, active_app_override)
        if env_is_source is None and install_type == 1:
            self.is_source_env = True
        if env_is_worker is None and install_type == 2:
            self.is_worker_env = True
        if self.is_worker_env:
            self.skip_repo_links = True

        repo_root = agilab_pck.parents[1] if len(agilab_pck.parents) > 1 else agilab_pck
        builtin_candidates = [
            apps_path if apps_path and apps_path.name == "builtin" else None,
            apps_path / "builtin" if apps_path else None,
            repo_root / "apps" / "builtin",
            agilab_pck / "apps" / "builtin",
        ]
        self.builtin_apps_path = next((c for c in builtin_candidates if c and c.exists()), None)

        # Default apps_path for non-worker envs when not provided
        if not self.is_worker_env and apps_path is None:
            repo_apps = self._get_apps_repository_root()
            default_apps_root = agilab_pck / "apps"

            # Prefer an explicit APPS_REPOSITORY if present
            if repo_apps is not None:
                apps_path = default_apps_root if default_apps_root.exists() else repo_apps
                self.apps_repository_root = repo_apps
            else:
                apps_path = default_apps_root

        if self.is_worker_env:
            if not app:
                raise ValueError("app is required when self.is_worker_env")
            active_app = home_abs / "wenv" / app
        else:
            if app is None:
                app_default = str(envars.get("APP_DEFAULT", "flight_project") or "").strip()
                app = app_default or "flight_project"

            # If caller provided an explicit path and it exists, honour it directly.
            if active_app_override is not None and Path(active_app_override).exists():
                active_app = Path(active_app_override)
            else:
                base_dir = apps_path if apps_path is not None else Path()
                try:
                    base_dir = base_dir.resolve()
                except Exception:
                    pass
                active_app = base_dir / app

                # Prefer builtin app directories over legacy duplicated roots.
                if self.builtin_apps_path:
                    candidate_builtin = self.builtin_apps_path / app
                    try:
                        if candidate_builtin.exists():
                            active_app = candidate_builtin
                    except Exception:
                        pass

        if not app.endswith('_project') and not app.endswith('_worker'):
            raise ValueError(f"{app} must end with '_project' or '_worker'")

        # If apps_path contains a builtin subdir, prefer that as the builtin root.
        if apps_path and (apps_path / "builtin").exists():
            self.builtin_apps_path = apps_path / "builtin"

        self.app = app
        try:
            self.active_app = active_app.resolve()
        except Exception:
            self.active_app = active_app
        self.apps_path = apps_path
        self.apps_repository_root: Path | None = None

        target = app.replace("_project", "").replace("_worker","").replace("-", "_")
        self.share_target_name = target

        self.verbose = verbose
        self.python_variante = python_variante
        self.logger = AgiLogger.configure(verbose=verbose, base_name="agi_env")
        self.debug = debug

        # Keep resolved flags from env/config/layout detection above.
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
        is_builtin_app = False
        try:
            if self.builtin_apps_path and self.active_app.resolve().is_relative_to(self.builtin_apps_path.resolve()):
                is_builtin_app = True
        except Exception:
            is_builtin_app = False

        can_link_repo = (
            apps_path is not None
            and not self.is_worker_env
            and not self.skip_repo_links
            and not is_builtin_app
        )
        if can_link_repo:
            try:
                apps_root_candidate = apps_path.resolve(strict=False)
            except Exception:
                apps_root_candidate = apps_path
            try:
                active_parent = self.active_app.parent.resolve(strict=False)
            except Exception:
                active_parent = self.active_app.parent
            if apps_root_candidate != active_parent:
                can_link_repo = False
            else:
                normalized_name = apps_root_candidate.name.lower()
                if normalized_name.endswith("_project") or normalized_name.endswith("_worker"):
                    can_link_repo = False

        if can_link_repo:
            _ensure_dir(apps_path)

            link_source = self.apps_repository_root or self._get_apps_repository_root()

            if link_source is not None and link_source.exists():
                same_tree = False
                if apps_path is not None:
                    try:
                        same_tree = apps_path.resolve(strict=False) == link_source.resolve()
                    except Exception:
                        same_tree = False

                if not same_tree:
                    for src_app in link_source.glob("*_project"):
                        dest_app = apps_path / src_app.relative_to(link_source)
                        # Avoid self-referential or pre-existing entries; only fill gaps.
                        try:
                            if dest_app.exists() or dest_app.resolve(strict=False) == src_app.resolve():
                                continue
                        except OSError:
                            continue

                        if os.name == "nt":
                            AgiEnv.create_symlink_windows(Path(src_app), dest_app)
                        else:
                            os.symlink(src_app, dest_app, target_is_directory=True)
                        AgiEnv.logger.info("Created symbolic link for app: %s -> %s", src_app, dest_app)
            elif apps_root.exists() and not self.is_source_env:
                try:
                    if apps_root.resolve() != active_app.parent.resolve():
                        self.copy_existing_projects(apps_root, active_app.parent)
                except Exception:
                    pass


        # Resource seed files (.agilab/.env, balancer assets) always live under
        # the agi_env package tree, regardless of install mode.
        resources_root = self.env_pck
        if not self.is_worker_env:
            self._init_resources(resources_root / self._agi_resources)
        try:
            self.TABLE_MAX_ROWS = int(str(envars.get("TABLE_MAX_ROWS", 1000000) or "").strip() or 1000000)
        except Exception:
            self.TABLE_MAX_ROWS = 1000000
        try:
            self.GUI_SAMPLING = int(str(envars.get("GUI_SAMPLING", 20) or "").strip() or 20)
        except Exception:
            self.GUI_SAMPLING = 20

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
        _ensure_dir(self.wenv_abs)

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
        worker_src_abs = self.wenv_abs / 'src'

        if self.is_worker_env and not is_local_worker:
            self.app_src = self.agilab_pck / "src"
            self.worker_path = worker_src_abs / target_worker / f"{target_worker}.py"

            self.manager_path = worker_src_abs / target / f"{target}.py"

        self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
        self.uvproject = self.active_app / "uv_config.toml"
        self.dataset_archive = self.worker_path.parent / "dataset.7z"

        src_path = normalize_path(self.app_src)
        if not src_path in sys.path:
            sys.path.append(src_path)

        if not self.worker_path.exists():
            if not self.is_worker_env:
                builtin_roots = []
                if self.builtin_apps_path is not None:
                    builtin_roots.append(self.builtin_apps_path)
                if apps_path is not None:
                    builtin_roots.append(apps_path / "builtin")
                builtin_roots.append(apps_root / "builtin")
                builtin_roots.append(self.agilab_pck / "apps" / "builtin")

                for builtin_root in builtin_roots:
                    try:
                        candidate_app = builtin_root / self.app
                    except TypeError:
                        continue
                    candidate_worker = candidate_app / "src" / target_worker / f"{target_worker}.py"
                    if not candidate_worker.exists():
                        continue
                    try:
                        self.active_app = candidate_app.resolve(strict=False)
                    except Exception:
                        self.active_app = candidate_app
                    self.app_src = self.active_app / "src"
                    self.manager_pyproject = self.active_app / "pyproject.toml"
                    self.uvproject = self.active_app / "uv_config.toml"
                    self.worker_path = candidate_worker
                    self.manager_path = self.app_src / target / f"{target}.py"
                    self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
                    self.dataset_archive = self.worker_path.parent / "dataset.7z"
                    self.builtin_apps_path = builtin_root
                    AgiEnv.logger.info(
                        "Resolved builtin app %s from %s after missing worker path in %s",
                        self.app,
                        candidate_app,
                        active_app,
                    )
                    break

        if not self.worker_path.exists():
            copied_packaged_worker = False
            # Prefer an installed worker tree inside wenv to avoid mutating the source checkout.
            wenv_worker_src = self.wenv_abs / "src" / target_worker / f"{target_worker}.py"
            if wenv_worker_src.exists():
                self.app_src = self.wenv_abs / "src"
                self.worker_path = wenv_worker_src
                self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
                self.dataset_archive = self.worker_path.parent / "dataset.7z"
                copied_packaged_worker = True
            if not copied_packaged_worker:
                if self._ensure_repository_app_link():
                    self.app_src = self.active_app / "src"
                    self.worker_path = self.app_src / target_worker / f"{target_worker}.py"
                    self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
                    self.dataset_archive = self.worker_path.parent / "dataset.7z"
                else:
                    packaged_app = self.agilab_pck / "apps" / self.app
                    if not self.is_worker_env and packaged_app.exists():
                        try:
                            same_app = packaged_app.resolve(
                                strict=False
                            ) == self.active_app.resolve(strict=False)
                        except Exception:  # pragma: no cover - defensive guard
                            same_app = False

                        if not same_app:
                            try:
                                shutil.copytree(
                                    packaged_app,
                                    self.active_app,
                                    dirs_exist_ok=True,
                                )
                                copied_packaged_worker = True
                                AgiEnv.logger.info(
                                    "Copied packaged app %s into %s",
                                    packaged_app,
                                    self.active_app,
                                )
                            except Exception as exc:
                                AgiEnv.logger.warning(
                                    "Unable to copy packaged worker app from %s to %s: %s",
                                    packaged_app,
                                    self.active_app,
                                    exc,
                                )
                    elif not self.is_worker_env and apps_root.exists():
                        self.copy_existing_projects(apps_root, apps_path)

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

        self.apps_path = apps_path
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

        self.AGI_LOCAL_SHARE = envars.get("AGI_LOCAL_SHARE") or os.environ.get("AGI_LOCAL_SHARE")
        if not self.AGI_LOCAL_SHARE:
            self.AGI_LOCAL_SHARE = "localshare"

        self.AGI_CLUSTER_SHARE = envars.get("AGI_CLUSTER_SHARE") or os.environ.get("AGI_CLUSTER_SHARE")
        if not self.AGI_CLUSTER_SHARE:
            self.AGI_CLUSTER_SHARE = "clustershare"

        # `AGI_SHARE_DIR` is the user-facing knob (installer + Streamlit UI). Treat it
        # as an override for the cluster share root so updating it is immediately
        # reflected without having to also edit `AGI_CLUSTER_SHARE` manually.
        share_dir_override = _clean_envar_value(envars, "AGI_SHARE_DIR", fallback_to_process=True)
        if share_dir_override is not None:
            self.AGI_CLUSTER_SHARE = share_dir_override
            try:
                envars["AGI_CLUSTER_SHARE"] = share_dir_override
            except Exception:
                pass

        def _cluster_enabled_from_settings() -> bool:
            """Best-effort read of the Streamlit 'Enable Cluster' toggle.

            The toggle is persisted under `[cluster].cluster_enabled` in the
            per-user app settings file seeded from each app's source
            `app_settings.toml`. When the per-app setting is missing, fall back to
            the versioned source file, then to the global `.env` value
            `AGI_CLUSTER_ENABLED` if present.
            """

            if self.is_worker_env:
                return True

            def _parse_bool(value: object) -> bool | None:
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, float)):
                    return bool(value)
                if isinstance(value, str):
                    normalized = value.strip().lower()
                    if normalized in {"1", "true", "yes", "y", "on"}:
                        return True
                    if normalized in {"0", "false", "no", "n", "off", ""}:
                        return False
                return None

            def _read_cluster_setting(path: Path) -> bool | None:
                """Read [cluster].cluster_enabled from a settings file."""
                try:
                    if not path.is_file() or path.stat().st_size <= 0:
                        return None
                    import tomllib

                    with path.open("rb") as handle:
                        doc = tomllib.load(handle)
                    cluster_section = doc.get("cluster")
                    if isinstance(cluster_section, dict) and "cluster_enabled" in cluster_section:
                        return _parse_bool(cluster_section.get("cluster_enabled"))
                    return None
                except Exception:
                    return None

            parsed: bool | None = None

            try:
                settings_candidates = [
                    self.resolve_user_app_settings_file(ensure_exists=False),
                    self.find_source_app_settings_file(),
                ]
                for settings_path in settings_candidates:
                    if settings_path is None:
                        continue
                    parsed = _read_cluster_setting(settings_path)
                    if parsed is not None:
                        break
            except Exception:
                parsed = None

            if parsed is not None:
                return parsed

            parsed = _parse_bool(envars.get("AGI_CLUSTER_ENABLED"))
            if parsed is None:
                parsed = _parse_bool(os.environ.get("AGI_CLUSTER_ENABLED"))
            return bool(parsed) if parsed is not None else False

        cluster_enabled = _cluster_enabled_from_settings()

        def _abs_path(path_str: str) -> str:
            """Absolute path; relative paths are relative to $HOME."""
            p = Path(path_str).expanduser()
            if not p.is_absolute():
                p = Path.home() / p
            return os.path.normpath(os.path.abspath(str(p)))

        def _is_usable_dir(p: str) -> bool:
            """Directory exists and is readable/writable."""
            if not os.path.isdir(p):
                return False
            try:
                os.listdir(p)
                testfile = os.path.join(p, ".agi_mount_test")
                with open(testfile, "w") as f:
                    f.write("ok")
                os.remove(testfile)
                return True
            except Exception:
                return False

        def _same_storage(a: str, b: str) -> bool:
            """True if a and b are the same inode/device (bind or symlink)."""
            try:
                sa = os.stat(os.path.realpath(a))
                sb = os.stat(os.path.realpath(b))
                return (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)
            except FileNotFoundError:
                return False

        def _fstab_bind_source_for_target(target: str) -> Optional[str]:
            """
            If /etc/fstab contains a bind mount for 'target',
            return the bind source path; else None.
            """
            try:
                with open("/etc/fstab", "r") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split()
                        if len(parts) < 4:
                            continue
                        src, tgt, fstype, opts = parts[:4]
                        if os.path.normpath(tgt) == target and "bind" in opts.split(","):
                            return os.path.normpath(src)
            except FileNotFoundError:
                pass
            return None

        def is_mounted(p: str) -> bool:
            """
            "Mounted enough to use" for AGI_CLUSTER_SHARE.

            Returns True if:
              1) path is a usable directory, AND
              2) either:
                 a) it is an actual mount target in this namespace, OR
                 b) /etc/fstab defines a bind mount for it and it points to the same storage
                    as the bind source (even if the bind isn't visible here), OR
                 c) no bind rule found; we accept usability alone.

            This matches your real intent: prefer clustershare when it works.
            """

            # Must be usable first (your real requirement)
            if not _is_usable_dir(p):
                return False

            # If it shows up as a mount target here, great.
            try:
                with open("/proc/self/mountinfo", "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) > 4 and os.path.normpath(parts[4]) == p:
                            return True
            except FileNotFoundError:
                # Non-Linux / no proc: fall back to usability only
                return True

            # Not a visible mountpoint here.
            # If fstab says it's a bind mount, verify it really points to the bind source.
            bind_src = _fstab_bind_source_for_target(p)
            if bind_src:
                # bind_src may be relative in fstab (rare), normalize it similarly
                bind_src_abs = _abs_path(bind_src) if not os.path.isabs(bind_src) else bind_src
                return _same_storage(p, bind_src_abs)

            # No bind rule found; directory is usable, so accept it.
            return True
        candidate = _abs_path(self.AGI_CLUSTER_SHARE)
        local_candidate = _abs_path(self.AGI_LOCAL_SHARE)

        wants_cluster_share = bool(cluster_enabled)
        if wants_cluster_share and os.path.normpath(candidate) == os.path.normpath(local_candidate):
            raise RuntimeError(
                "Cluster mode requires AGI_CLUSTER_SHARE to be distinct from AGI_LOCAL_SHARE. "
                f"Both resolve to {candidate!r}; env={env_path}"
            )
        mounted = is_mounted(candidate)
        if mounted and wants_cluster_share:
            self.agi_share_path = self.AGI_CLUSTER_SHARE
            #AgiEnv.logger.info(
            #    f"self.agi_share_path = AGI_CLUSTER_SHARE = {candidate}"
            #)
        else:
            if wants_cluster_share and not mounted:
                raise RuntimeError(
                    "Cluster mode requires AGI_CLUSTER_SHARE to be mounted and writable. "
                    f"Configured AGI_CLUSTER_SHARE={candidate!r} is not usable; env={env_path}"
                )
            self.agi_share_path = self.AGI_LOCAL_SHARE
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
                except Exception as exc:  # pragma: no cover - defensive guard
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
            except Exception:
                cls.resources_path = Path(".agilab").resolve()
        if getattr(cls, "envars", None) is None or not isinstance(cls.envars, dict):
            try:
                env_path = cls.resources_path / ".env"
                cls.envars = _load_dotenv_values(env_path, verbose=False)
            except Exception:
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
            except Exception:
                continue
            if not base.exists():
                continue

            for project_path in base.glob("*_project"):
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

        self.CLUSTER_CREDENTIALS = envars.get("CLUSTER_CREDENTIALS", None)
        self.OPENAI_API_KEY = envars.get("OPENAI_API_KEY", None)
        self.OPENAI_MODEL = envars.get("OPENAI_MODEL") or get_default_openai_model()
        AGILAB_LOG_OVERRIDE = _clean_envar_value(envars, "AGI_LOG_DIR", fallback_to_process=True)
        AGILAB_LOG_ABS = Path(AGILAB_LOG_OVERRIDE or (self.home_abs / "log")).expanduser()
        if not AGILAB_LOG_ABS.is_absolute():
            AGILAB_LOG_ABS = (self.home_abs / AGILAB_LOG_ABS).resolve()
        self.AGILAB_LOG_ABS = _ensure_dir(AGILAB_LOG_ABS)
        runenv_base = self.AGILAB_LOG_ABS / "execute"
        _ensure_dir(runenv_base)
        self.runenv = runenv_base / self.target
        _ensure_dir(self.runenv)
        AGILAB_EXPORT_OVERRIDE = _clean_envar_value(envars, "AGI_EXPORT_DIR", fallback_to_process=True)
        AGILAB_EXPORT_ABS = Path(AGILAB_EXPORT_OVERRIDE or (self.home_abs / "export")).expanduser()
        if not AGILAB_EXPORT_ABS.is_absolute():
            AGILAB_EXPORT_ABS = (self.home_abs / AGILAB_EXPORT_ABS).resolve()
        self.AGILAB_EXPORT_ABS = _ensure_dir(AGILAB_EXPORT_ABS)
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
                logger = AgiEnv.logger
                if logger:
                    logger.info(f"[WARN] Source file missing (skipped): {src_item}")
                return
            try:
                shutil.copy2(src_item, dst_item)
            except Exception as e:
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
        except Exception as e:
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
            except Exception:
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
        except Exception:
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
        except Exception:
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
