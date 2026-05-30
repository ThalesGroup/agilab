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
import os
import getpass
import shutil
import psutil
import socket
import subprocess
import sys
from pathlib import Path
import logging
from pathspec import PathSpec
import py7zr
import urllib.request
import inspect
import ctypes
from ctypes import wintypes
import importlib.util
from threading import RLock
from agi_env.app_settings_support import (
    app_settings_aliases,
    app_settings_source_roots,
    candidate_app_settings_path,
    find_source_app_settings_file,
    resolve_user_app_settings_file,
)
from agi_env.env_config_support import (
    load_dotenv_values as _load_dotenv_values,
    write_env_updates,
)
from agi_env.agi_env_app_switch_support import change_app as _agi_env_change_app
from agi_env.agi_env_execution_methods import (
    run as _agi_env_run,
    run_agi as _agi_env_run_agi,
    run_async as _agi_env_run_async,
    run_bg as _agi_env_run_bg,
)
from agi_env.agi_env_instance_initialization import initialize_agi_env_instance
from agi_env.agi_env_meta_support import AgiEnvMeta as _AgiEnvMeta
from agi_env.env_runtime_initialization_support import initialize_app_runtime
from agi_env.hook_support import resolve_worker_hook, select_hook
from agi_env.host_runtime_support import (
    check_internet_connectivity,
    create_symlink as _create_symlink,
    is_local_ip,
)
from agi_env.installation_support import (
    installation_marker_path,
    locate_agilab_installation_path,
    read_agilab_installation_marker,
)
from agi_env.runtime_bootstrap_support import parse_int_env_value
from agi_env.worker_runtime_support import configure_worker_runtime
from agi_env.windows_link_support import (
    create_junction_windows as _create_junction_windows,
    create_symlink_windows as _create_symlink_windows,
    has_admin_rights as _has_admin_rights,
)
from agi_env.process_support import (
    build_subprocess_env,
    fix_windows_drive as _fix_windows_drive,
    normalize_path,
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
from agi_env.rename_gitignore_support import (
    is_relative_to as is_path_relative_to,
    load_gitignore_spec,
    replace_text_content,
)
from agi_env.content_renamer_support import ContentRenamer as BaseContentRenamer
from agi_env.bootstrap_support import coerce_active_app_request
from agi_env.source_analysis_support import (
    extract_base_info as extract_ast_base_info,
    get_full_attribute_name as build_full_attribute_name,
    get_import_mapping as build_import_mapping,
)
from agi_env.project_initialization_support import (
    copy_file_if_missing,
    discover_projects,
    initialize_app_files,
    initialize_resources,
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
_LOGGING_MODULE = logging


def _optional_agi_pages_bundles_root() -> Path | None:
    """Return the optional agi-pages bundle root without making it a hard dependency."""

    if importlib.util.find_spec("agi_pages") is None:
        return None
    try:
        import agi_pages
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


_resolve_worker_hook.cache_clear = resolve_worker_hook.cache_clear  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]


def _select_hook(local_candidate: Path, fallback_filename: str, hook_label: str) -> tuple[Path, bool]:
    """Return the hook to execute and whether it comes from the shared baseline."""
    return select_hook(
        local_candidate,
        fallback_filename,
        hook_label,
        resolve_hook=_resolve_worker_hook,
    )

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
    def for_app(
        cls,
        *,
        apps_path: Path,
        app: str,
        verbose: int | None = None,
        **kwargs,
    ) -> "AgiEnv":
        """Return an environment for an app, reinitialising the singleton only when needed."""

        app_name = Path(str(app)).name
        if not app_name:
            raise ValueError("app name must be non-empty")
        requested_apps_path = Path(apps_path).expanduser().resolve(strict=False)

        if cls._instance is None:
            return cls(apps_path=requested_apps_path, app=app_name, verbose=verbose, **kwargs)

        env = cls.current()
        current_apps_path = Path(getattr(env, "apps_path", "") or "").expanduser().resolve(strict=False)
        current_app = Path(str(getattr(env, "app", "") or "")).name
        current_active_app = Path(getattr(env, "active_app", "") or "").expanduser().resolve(strict=False)
        requested_active_app = (requested_apps_path / app_name).resolve(strict=False)
        requested_builtin_app = (requested_apps_path / "builtin" / app_name).resolve(strict=False)

        if (
            current_apps_path == requested_apps_path
            and current_app == app_name
            and current_active_app in {requested_active_app, requested_builtin_app}
        ):
            return env

        type(env).__init__(
            env,
            apps_path=requested_apps_path,
            app=app_name,
            verbose=verbose,
            _agilab_reinitialize=True,
            **kwargs,
        )
        return env

    @classmethod
    def reset(cls) -> None:
        """Drop the cached singleton so a fresh environment can be bootstrapped."""

        with cls._lock:
            cls._instance = None
    install_type: int | None = None  # deprecated: derived from flags for backward compatibility
    apps_path: Path | None = None
    app: str | None = None
    target: str | None = None
    TABLE_MAX_ROWS: int | None = None
    GUI_SAMPLING: int | float | None = None
    init_done: bool = False
    hw_rapids_capable: bool | None = None
    is_worker_env: bool = False
    _is_managed_pc: bool | None = None
    skip_repo_links: bool = False
    debug: bool = False
    uv: str | None = None
    benchmark: object = None
    verbose: int | None = None
    pyvers_worker: str | None = None
    logger: logging.Logger | None = None
    out_log: object = None
    err_log: object = None
    # Minimal class-level fallbacks to support limited static usage pre-init
    resources_path: Path = Path.home() / ".agilab"
    envars: dict[str, str] = {}
    home_abs: Path
    active_app: Path
    app_src: Path
    builtin_apps_path: Path | None
    apps_repository_root: Path | None
    installed_app_project_paths: tuple[Path, ...]
    projects: list[str]
    user: str
    env_pck: Path
    node_pck: Path
    core_pck: Path
    cluster_pck: Path
    agilab_pck: Path
    st_resources: Path
    agi_share_path: str | Path | None
    agi_share_path_abs: Path
    app_data_rel: Path
    share_target_name: str
    AGI_LOCAL_SHARE: str | Path | None
    dist_abs: Path
    wenv_abs: Path
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

        allow_reinitialize = bool(kwargs.pop("_agilab_reinitialize", False))
        verbose = 0 if verbose is None else verbose
        app, active_app_override = coerce_active_app_request(app, kwargs, path_cls=Path)
        init_signature = self._init_signature(
            apps_path=apps_path,
            app=app,
            active_app_override=active_app_override,
            verbose=verbose,
            debug=debug,
            python_variante=python_variante,
            kwargs=kwargs,
        )

        if getattr(self, "_agilab_initialized", False) and not allow_reinitialize:
            current_signature = getattr(self, "_agilab_init_signature", None)
            if current_signature == init_signature:
                return
            raise RuntimeError(
                "AgiEnv is already initialised with a different configuration; "
                "use AgiEnv.reset() for a fresh environment or change_app() to switch apps."
            )

        initialize_agi_env_instance(
            self,
            apps_path=apps_path,
            app=app,
            active_app_override=active_app_override,
            verbose=verbose,
            debug=debug,
            python_variante=python_variante,
            init_signature=init_signature,
            load_dotenv_values_fn=_load_dotenv_values,
            optional_agi_pages_bundles_root_fn=_optional_agi_pages_bundles_root,
            ensure_dir_fn=_ensure_dir,
            module_logger=logger,
        )

    @staticmethod
    def _init_signature(
        *,
        apps_path: Path | None,
        app: str | None,
        active_app_override,
        verbose: int,
        debug: bool,
        python_variante: str,
        kwargs: dict,
    ) -> tuple:
        return (
            AgiEnv._signature_value(apps_path),
            AgiEnv._signature_value(app),
            AgiEnv._signature_value(active_app_override),
            str(python_variante),
            tuple(sorted((str(key), AgiEnv._signature_value(value)) for key, value in kwargs.items())),
        )

    @staticmethod
    def _signature_value(value):
        if isinstance(value, Path):
            try:
                return ("path", str(value.expanduser().resolve(strict=False)))
            except (OSError, RuntimeError):
                return ("path", str(value))
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        return repr(value)

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
        initialize_resources(
            resources_src,
            resources_path=self.resources_path,
            st_resources=self.st_resources,
            is_source_env=self.is_source_env,
            ensure_dir_fn=_ensure_dir,
            logger=AgiEnv.logger,
        )

    def _init_projects(self):
        """Identify available projects and align state with the selected target."""

        if self.apps_repository_root is None:
            self.apps_repository_root = self._get_apps_repository_root()

        self.projects = self.get_projects(self.apps_path, self.builtin_apps_path, self.apps_repository_root)  # ty: ignore[invalid-argument-type]
        for idx, project in enumerate(self.projects):
            if self.target == project[:-8].replace("-", "_"):
                self.app = project
                break

    def get_projects(self, *paths: Path):
        """Return the names of ``*_project`` directories beneath the provided paths."""
        return discover_projects(
            paths,
            installed_app_project_paths=getattr(self, "installed_app_project_paths", ()),
            logger=AgiEnv.logger,
        )

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

        candidate = link_root / self.app  # ty: ignore[unsupported-operator]
        if not candidate.exists():
            return False

        dest = self.active_app
        if dest.exists():
            if dest.is_symlink():
                dest.unlink()
            else:
                return False

        if not AgiEnv.create_symlink(candidate, dest):
            return False
        AgiEnv.logger.info("Created apps repository symlink: %s -> %s", dest, candidate)  # ty: ignore[unresolved-attribute]
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
        return find_source_app_settings_file(
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
        return resolve_user_app_settings_file(
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
        return mode_to_str(mode, hw_rapids_capable=self.hw_rapids_capable)  # ty: ignore[invalid-argument-type]

    @staticmethod
    def mode2int(mode):
        """Convert an iterable of mode flags (``p``, ``c``, ``d``) to the bitmask int."""
        return mode_to_int(mode)

    def is_valid_ip(self, ip: str) -> bool:
        """Return ``True`` when ``ip`` is a syntactically valid IPv4 address."""
        return is_valid_ipv4_address(ip)

    def init_envars_app(self, envars):
        """Cache frequently used environment variables and ensure directories exist."""
        initialize_app_runtime(
            self,
            envars,
            environ=os.environ,
            default_account=getpass.getuser(),
            read_agilab_path_fn=self.read_agilab_path,
            optional_agi_pages_bundles_root_fn=_optional_agi_pages_bundles_root,
            ensure_dir_fn=_ensure_dir,
            logger=AgiEnv.logger,
        )


    @staticmethod
    def _copy_file(src_item, dst_item):
        """Copy ``src_item`` to ``dst_item`` if the destination does not exist."""
        copy_file_if_missing(src_item, dst_item, logger=AgiEnv.logger)

    def _init_apps(self):
        app_files = initialize_app_files(
            app_src=self.app_src,
            active_app=self.active_app,
            resources_path=self.resources_path,
            agilab_pck=self.agilab_pck,
            find_source_app_settings_file_fn=self.find_source_app_settings_file,
            resolve_user_app_settings_file_fn=self.resolve_user_app_settings_file,
        )
        self.app_settings_source_file = app_files.app_settings_source_file
        self.app_settings_file = app_files.app_settings_file
        self.app_args_form = app_files.app_args_form
        self.gitignore_file = app_files.gitignore_file


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

    run = staticmethod(_agi_env_run)
    _run_bg = staticmethod(_agi_env_run_bg)
    run_agi = _agi_env_run_agi
    run_async = staticmethod(_agi_env_run_async)

    @staticmethod
    def create_symlink(src: Path, dest: Path) -> bool:
        return _create_symlink(
            src,
            dest,
            logger=AgiEnv.logger,
            os_name=os.name,
            create_junction_windows_fn=AgiEnv.create_junction_windows,
        )

    change_app = _agi_env_change_app

    @staticmethod
    def is_local(ip):
        """

        Args:
          ip:

        Returns:

        """
        return is_local_ip(
            ip,
            cache=AgiEnv._ip_local_cache,
            net_if_addrs_fn=psutil.net_if_addrs,
            inet_family=socket.AF_INET,
        )

    @staticmethod
    def has_admin_rights():
        """
        Check if the current process has administrative rights on Windows.

        Returns:
            bool: True if admin, False otherwise.
        """
        return _has_admin_rights(ctypes_module=ctypes)

    @staticmethod
    def create_junction_windows(source: Path, dest: Path) -> bool:
        """
        Create a directory junction on Windows.

        Args:
            source (Path): The target directory path.
            dest (Path): The destination junction path.
        """
        return _create_junction_windows(
            source,
            dest,
            logger=AgiEnv.logger,
            check_call=subprocess.check_call,
        )

    @staticmethod
    def create_symlink_windows(source: Path, dest: Path):
        """
        Create a symbolic link on Windows, handling permissions and types.

        Args:
            source (Path): Source directory path.
            dest (Path): Destination symlink path.
        """
        return _create_symlink_windows(
            source,
            dest,
            has_admin_rights_fn=AgiEnv.has_admin_rights,
            logger=AgiEnv.logger,
            ctypes_module=ctypes,
            wintypes_module=wintypes,
        )

    def create_rename_map(self, target_project: Path, dest_project: Path) -> dict:
        """Create a mapping of old → new names for cloning."""
        return build_clone_rename_map(target_project, dest_project)

    def clone_project(self, target_project: Path, dest_project: Path):
        """Clone a project by copying files, applying renames, and final cleanup."""
        clone_app_project(
            target_project,
            dest_project,
            apps_path=self.apps_path,  # ty: ignore[invalid-argument-type]
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
        extract_to: Path | str = None,  # ty: ignore[invalid-parameter-default]
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
            environ=os.environ,  # ty: ignore[invalid-argument-type]
        )


    @staticmethod
    def check_internet():
        return check_internet_connectivity(
            logger=AgiEnv.logger,
            request_factory=urllib.request.Request,
            urlopen_fn=urllib.request.urlopen,
        )



class ContentRenamer(BaseContentRenamer):
    """Compatibility wrapper that binds the pure renamer to ``AgiEnv.logger``."""

    def __init__(self, rename_map):
        super().__init__(rename_map, logger=AgiEnv.logger)
def _is_relative_to(path: Path, other: Path) -> bool:
    """Return ``True`` if ``path`` lies under ``other`` (without requiring Python 3.9)."""
    return is_path_relative_to(path, other)
