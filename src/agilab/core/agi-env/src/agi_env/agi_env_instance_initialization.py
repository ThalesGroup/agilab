"""Constructor orchestration for :class:`agi_env.agi_env.AgiEnv`."""

from __future__ import annotations

from dataclasses import dataclass
import getpass
import importlib.util
import os
import sys
from pathlib import Path
from typing import Callable

from agi_env.agi_logger import AgiLogger
from agi_env.app_provider_registry import installed_app_project_paths, resolve_app_runtime_target
from agi_env.bootstrap_support import (
    can_link_repo_apps,
    resolve_active_app_selection,
    resolve_builtin_apps_path,
    resolve_default_apps_path,
    resolve_install_type,
    resolve_package_dir,
    resolve_requested_apps_path,
)
from agi_env.env_config_support import clean_envar_value
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
from agi_env.share_mount_support import (
    cluster_enabled_from_settings as resolve_cluster_enabled_from_settings,
    resolve_share_path as resolve_runtime_share_path,
)


@dataclass(slots=True)
class _LoadedEnvironment:
    home_abs: Path
    env_path: Path
    envars: dict
    repo_agilab_dir: Path


@dataclass(slots=True)
class _PackageBootstrap:
    agilab_pkg_dir: Path
    agilab_pck: Path
    is_agilab_installed: bool


@dataclass(slots=True)
class _AppBootstrap:
    apps_path: Path | None
    active_app: Path
    target: str
    apps_root: Path


def initialize_agi_env_instance(
    env,
    *,
    apps_path: Path | None,
    app: str | None,
    active_app_override,
    verbose: int,
    debug: bool,
    python_variante: str,
    init_signature: tuple,
    load_dotenv_values_fn: Callable,
    optional_agi_pages_bundles_root_fn: Callable[[], Path | None],
    ensure_dir_fn: Callable[[str | Path], Path],
    module_logger,
) -> None:
    """Populate an ``AgiEnv`` singleton after the public constructor guard passes."""

    env_cls = type(env)
    _reset_bootstrap_flags(env)
    loaded = _load_environment(
        env,
        verbose=verbose,
        load_dotenv_values_fn=load_dotenv_values_fn,
        module_logger=module_logger,
    )
    envars = loaded.envars

    _propagate_streamlit_message_size(envars)
    package = _resolve_package_bootstrap(loaded.repo_agilab_dir)

    apps_path, override_builtin_apps_path = _resolve_requested_apps_path_from_env(
        envars=envars,
        apps_path=apps_path,
        active_app_override=active_app_override,
    )
    _configure_environment_kind(
        env,
        envars=envars,
        apps_path=apps_path,
        active_app_override=active_app_override,
        is_agilab_installed=package.is_agilab_installed,
    )
    app_bootstrap = _resolve_active_app_bootstrap(
        env,
        app=app,
        apps_path=apps_path,
        active_app_override=active_app_override,
        override_builtin_apps_path=override_builtin_apps_path,
        home_abs=loaded.home_abs,
        envars=envars,
        agilab_pck=package.agilab_pck,
    )

    _configure_runtime_identity(
        env,
        verbose=verbose,
        debug=debug,
        python_variante=python_variante,
    )
    _configure_package_layout(
        env,
        repo_agilab_dir=loaded.repo_agilab_dir,
        agilab_pkg_dir=package.agilab_pkg_dir,
    )
    _sync_repository_app_links(
        env,
        env_cls=env_cls,
        app_bootstrap=app_bootstrap,
        ensure_dir_fn=ensure_dir_fn,
    )
    _configure_common_runtime(env, app_bootstrap=app_bootstrap, loaded=loaded, envars=envars)

    if env.is_worker_env:
        env.user = "agi"
        return

    _configure_non_worker_runtime(
        env,
        env_cls=env_cls,
        envars=envars,
        optional_agi_pages_bundles_root_fn=optional_agi_pages_bundles_root_fn,
        ensure_dir_fn=ensure_dir_fn,
    )

    env._agilab_init_signature = init_signature
    env._agilab_initialized = True


def _reset_bootstrap_flags(env) -> None:
    env.skip_repo_links = False
    env.AGILAB_SHARE_HINT = None
    env.AGILAB_SHARE_REL = None


def _load_environment(
    env,
    *,
    verbose: int,
    load_dotenv_values_fn: Callable,
    module_logger,
) -> _LoadedEnvironment:
    env.is_managed_pc = getpass.getuser().startswith("T0")
    env._is_managed_pc = env.is_managed_pc
    env._agi_resources = Path("resources/.agilab")
    home_abs = Path.home() / "MyApp" if env.is_managed_pc else Path.home()
    env.home_abs = home_abs
    env._share_root_cache = None

    env.uv = "uv"
    if verbose < 3:
        env.uv = "uv --quiet"
    elif verbose >= 3:
        env.uv = "uv --verbose"

    env.resources_path = home_abs / env._agi_resources.name
    env_path = env.resources_path / ".env"
    env.benchmark = env.resources_path / "benchmark.json"
    env.envars = load_dotenv_values_fn(env_path, verbose=verbose)
    module_logger.debug(f"env path: {env_path}")
    repo_agilab_dir = Path(__file__).resolve().parents[4]

    return _LoadedEnvironment(
        home_abs=home_abs,
        env_path=env_path,
        envars=env.envars,
        repo_agilab_dir=repo_agilab_dir,
    )


def _resolve_package_bootstrap(repo_agilab_dir: Path) -> _PackageBootstrap:
    package_context = resolve_agilab_package_context(
        repo_agilab_dir=repo_agilab_dir,
        find_spec_fn=importlib.util.find_spec,
        path_cls=Path,
    )
    return _PackageBootstrap(
        agilab_pkg_dir=package_context.package_dir,
        agilab_pck=package_context.apps_root_hint,
        is_agilab_installed=package_context.is_installed,
    )


def _resolve_requested_apps_path_from_env(
    *,
    envars,
    apps_path: Path | None,
    active_app_override,
) -> tuple[Path | None, Path | None]:
    env_apps_path = str(envars.get("APPS_PATH", "") or "").strip()
    return resolve_requested_apps_path(
        env_apps_path=env_apps_path,
        explicit_apps_path=apps_path,
        active_app_override=active_app_override,
        path_cls=Path,
    )


def _configure_environment_kind(
    env,
    *,
    envars,
    apps_path: Path | None,
    active_app_override,
    is_agilab_installed: bool,
) -> None:
    _apply_environment_layout_flags(
        env,
        envars=envars,
        is_agilab_installed=is_agilab_installed,
    )

    install_type, inferred_worker_env = resolve_install_type(
        apps_path,
        active_app_override=active_app_override,
    )
    if envars.get("IS_SOURCE_ENV") is None and install_type == 1:
        env.is_source_env = True
    if envars.get("IS_WORKER_ENV") is None and install_type == 2:
        env.is_worker_env = True
    if inferred_worker_env:
        env.is_worker_env = True
    if env.is_worker_env:
        env.skip_repo_links = True


def _resolve_active_app_bootstrap(
    env,
    *,
    app: str | None,
    apps_path: Path | None,
    active_app_override,
    override_builtin_apps_path: Path | None,
    home_abs: Path,
    envars,
    agilab_pck: Path,
) -> _AppBootstrap:
    apps_path = _configure_app_roots(
        env,
        apps_path=apps_path,
        override_builtin_apps_path=override_builtin_apps_path,
        agilab_pck=agilab_pck,
    )
    app, active_app = _select_active_app(
        env,
        app=app,
        active_app_override=active_app_override,
        apps_path=apps_path,
        home_abs=home_abs,
        envars=envars,
    )
    _bind_active_app(env, app=app, active_app=active_app, apps_path=apps_path)

    target = resolve_app_runtime_target(active_app, app)
    env.share_target_name = target

    return _AppBootstrap(
        apps_path=apps_path,
        active_app=active_app,
        target=target,
        apps_root=agilab_pck / "apps",
    )


def _configure_app_roots(
    env,
    *,
    apps_path: Path | None,
    override_builtin_apps_path: Path | None,
    agilab_pck: Path,
) -> Path | None:
    repo_root = agilab_pck.parents[1] if len(agilab_pck.parents) > 1 else agilab_pck
    env.builtin_apps_path = override_builtin_apps_path or resolve_builtin_apps_path(
        apps_path=apps_path,
        repo_root=repo_root,
        agilab_pck=agilab_pck,
    )

    repo_apps = env._get_apps_repository_root()
    default_apps_root = agilab_pck / "apps"
    apps_path, apps_repository_root = resolve_default_apps_path(
        apps_path=apps_path,
        is_worker_env=env.is_worker_env,
        default_apps_root=default_apps_root,
        apps_repository_root=repo_apps,
    )
    env.apps_repository_root = apps_repository_root or repo_apps
    env.installed_app_project_paths = installed_app_project_paths()
    return apps_path


def _select_active_app(
    env,
    *,
    app: str | None,
    active_app_override,
    apps_path: Path | None,
    home_abs: Path,
    envars,
) -> tuple[str, Path]:
    active_app_selection = resolve_active_app_selection(
        app=app,
        active_app_override=active_app_override,
        apps_path=apps_path,
        builtin_apps_path=env.builtin_apps_path,
        installed_app_projects=env.installed_app_project_paths,
        home_abs=home_abs,
        is_worker_env=env.is_worker_env,
        default_app=str(envars.get("APP_DEFAULT", "flight_telemetry_project") or "").strip(),
        path_cls=Path,
    )
    app = active_app_selection.app
    active_app = active_app_selection.active_app

    if not app.endswith("_project") and not app.endswith("_worker"):
        raise ValueError(f"{app} must end with '_project' or '_worker'")

    return app, active_app


def _bind_active_app(
    env,
    *,
    app: str,
    active_app: Path,
    apps_path: Path | None,
) -> None:
    if apps_path and (apps_path / "builtin").exists():
        env.builtin_apps_path = apps_path / "builtin"
    env.app = app
    try:
        env.active_app = active_app.resolve()
    except OSError:
        env.active_app = active_app
    env.apps_path = apps_path


def _configure_runtime_identity(
    env,
    *,
    verbose: int,
    debug: bool,
    python_variante: str,
) -> None:
    env.verbose = verbose
    env.python_variante = python_variante
    env.logger = AgiLogger.configure(verbose=verbose, base_name="agi_env")
    env.debug = debug
    env.is_local_worker = False
    env.install_type = 1 if env.is_source_env else (2 if env.is_worker_env else 0)


def _sync_repository_app_links(
    env,
    *,
    env_cls,
    app_bootstrap: _AppBootstrap,
    ensure_dir_fn: Callable[[str | Path], Path],
) -> None:
    can_link_repo = can_link_repo_apps(
        apps_path=app_bootstrap.apps_path,
        active_app=env.active_app,
        builtin_apps_path=env.builtin_apps_path,
        is_worker_env=env.is_worker_env,
        skip_repo_links=env.skip_repo_links,
    )
    sync_repository_apps(
        can_link_repo=can_link_repo,
        apps_path=app_bootstrap.apps_path,
        apps_root=app_bootstrap.apps_root,
        active_app=app_bootstrap.active_app,
        is_source_env=env.is_source_env,
        apps_repository_root=env.apps_repository_root,
        get_apps_repository_root_fn=env._get_apps_repository_root,
        ensure_dir_fn=ensure_dir_fn,
        copy_existing_projects_fn=env.copy_existing_projects,
        create_symlink_windows_fn=env_cls.create_symlink_windows,
        symlink_fn=os.symlink,
        logger=env_cls.logger,
        os_name=os.name,
        path_cls=Path,
    )


def _configure_common_runtime(
    env,
    *,
    app_bootstrap: _AppBootstrap,
    loaded: _LoadedEnvironment,
    envars,
) -> None:
    resources_root = env.env_pck
    if not env.is_worker_env:
        env._init_resources(resources_root / env._agi_resources)
    env.TABLE_MAX_ROWS = parse_int_env_value(envars, "TABLE_MAX_ROWS", 1000000)
    env.GUI_SAMPLING = parse_int_env_value(envars, "GUI_SAMPLING", 20)

    env._configure_worker_runtime(
        target=app_bootstrap.target,
        home_abs=loaded.home_abs,
        apps_path=app_bootstrap.apps_path,
        apps_root=app_bootstrap.apps_root,
        envars=envars,
        requested_active_app=app_bootstrap.active_app,
    )

    _configure_share_runtime(env, envars=envars, env_path=loaded.env_path)


def _configure_non_worker_runtime(
    env,
    *,
    env_cls,
    envars,
    optional_agi_pages_bundles_root_fn: Callable[[], Path | None],
    ensure_dir_fn: Callable[[str | Path], Path],
) -> None:
    _resolve_worker_base_class(env, env_cls=env_cls)
    _configure_credentials_and_project_state(env, env_cls=env_cls, envars=envars)
    _extract_packaged_dataset_if_needed(env, env_cls=env_cls)
    _finalize_non_worker_runtime(
        env,
        env_cls=env_cls,
        optional_agi_pages_bundles_root_fn=optional_agi_pages_bundles_root_fn,
        ensure_dir_fn=ensure_dir_fn,
    )


def _propagate_streamlit_message_size(envars) -> None:
    streamlit_size = envars.get("STREAMLIT_SERVER_MAX_MESSAGE_SIZE") or envars.get(
        "STREAMLIT_MAX_MESSAGE_SIZE"
    )
    if streamlit_size:
        os.environ.setdefault("STREAMLIT_SERVER_MAX_MESSAGE_SIZE", str(streamlit_size))
        os.environ.setdefault("STREAMLIT_MAX_MESSAGE_SIZE", str(streamlit_size))


def _apply_environment_layout_flags(env, *, envars, is_agilab_installed: bool) -> bool:
    env_is_source = envars.get("IS_SOURCE_ENV")
    env_is_worker = envars.get("IS_WORKER_ENV")
    if env_is_source is not None:
        try:
            is_agilab_installed = not bool(int(env_is_source))
        except (TypeError, ValueError):
            is_agilab_installed = str(env_is_source).lower() in {"false", "0", "no", ""}
        env.is_source_env = not is_agilab_installed
    if env_is_worker is not None:
        try:
            env.is_worker_env = bool(int(env_is_worker))
        except (TypeError, ValueError):
            env.is_worker_env = str(env_is_worker).lower() not in {"false", "0", "no", ""}
    return is_agilab_installed


def _configure_package_layout(env, *, repo_agilab_dir: Path, agilab_pkg_dir: Path) -> None:
    package_layout = resolve_package_layout(
        is_source_env=env.is_source_env,
        repo_agilab_dir=repo_agilab_dir,
        installed_package_dir=agilab_pkg_dir,
        resolve_package_dir_fn=resolve_package_dir,
        find_spec_fn=importlib.util.find_spec,
        path_cls=Path,
    )
    env.agilab_pck = package_layout.agilab_pck
    env.env_pck = package_layout.env_pck
    env.node_pck = package_layout.node_pck
    env.core_pck = package_layout.core_pck
    env.cluster_pck = package_layout.cluster_pck
    env.cli = package_layout.cli

    resolve = env._resolve_package
    env.env_pck = resolve(env.env_pck)
    env.node_pck = resolve(env.node_pck)
    env.core_pck = resolve(env.core_pck)
    env.cluster_pck = resolve(env.cluster_pck)
    env.agi_env = env.env_pck.parents[1]
    env.agi_node = env.node_pck.parents[1]
    env.agi_core = env.core_pck.parents[1]
    env.agi_cluster = env.cluster_pck.parents[1]
    env.st_resources = resolve_resource_root(env.agilab_pck, path_cls=Path)


def _configure_share_runtime(env, *, envars, env_path: Path) -> None:
    share_runtime_config = resolve_share_runtime_config(
        envars=envars,
        environ=os.environ,
        is_worker_env=env.is_worker_env,
        resolve_workspace_settings_fn=lambda: env.resolve_user_app_settings_file(ensure_exists=False),
        find_source_settings_fn=env.find_source_app_settings_file,
        clean_envar_value_fn=clean_envar_value,
        resolve_cluster_enabled_fn=resolve_cluster_enabled_from_settings,
        resolve_runtime_share_path_fn=resolve_runtime_share_path,
        env_path=env_path,
        home_path=Path.home(),
    )
    env.AGI_LOCAL_SHARE = share_runtime_config.local_share
    env.AGI_CLUSTER_SHARE = share_runtime_config.cluster_share
    env.agi_share_path = share_runtime_config.agi_share_path
    env._share_root_cache = None

    share_root_abs = env.share_root_path()
    share_target_name = env._share_target_name()
    env.share_target_name = share_target_name
    env.agi_share_path_abs = share_root_abs
    env.app_data_rel = share_root_abs / share_target_name
    env.dataframe_path = env.app_data_rel / "dataframe"


def _resolve_worker_base_class(env, *, env_cls) -> None:
    if env.worker_path.exists():
        env.base_worker_cls, env._base_worker_module = env.get_base_worker_cls(
            env.worker_path, env.target_worker_class
        )
        return

    env.base_worker_cls, env._base_worker_module = (None, None)
    if (not env.is_source_env) and (not env.is_worker_env):
        env_cls.logger.debug(
            f"Missing {env.target_worker_class} definition; expected {env.worker_path} (packaged end-user env)"
        )
    else:
        env_cls.logger.info(f"Missing {env.target_worker_class} definition; expected {env.worker_path}")


def _configure_credentials_and_project_state(env, *, env_cls, envars) -> None:
    raw_credentials = envars.get("CLUSTER_CREDENTIALS", getpass.getuser())
    credentials_parts = raw_credentials.split(":")
    env.user = credentials_parts[0]
    env.password = credentials_parts[1] if len(credentials_parts) > 1 else None
    ssh_key_env = envars.get("AGI_SSH_KEY_PATH", "")
    ssh_key_env = ssh_key_env.strip() if isinstance(ssh_key_env, str) else ""
    env.ssh_key_path = str(Path(ssh_key_env).expanduser()) if ssh_key_env else None

    env.projects = env.get_projects(env.apps_path, env.builtin_apps_path)
    if not env.projects:
        env_cls.logger.info(f"Could not find any target project app in {env.agilab_pck / 'apps'}.")

    env.setup_app = env.active_app / "build.py"
    env.setup_app_module = "agi_node.agi_dispatcher.build"
    env._init_projects()

    env.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
    if not env.is_valid_ip(env.scheduler_ip):
        raise ValueError(f"Invalid scheduler IP address: {env.scheduler_ip}")

    if env.is_source_env:
        env.help_path = str(env.agilab_pck.parents[1] / "docs/html")
    else:
        env.help_path = "https://thalesgroup.github.io/agilab"


def _extract_packaged_dataset_if_needed(env, *, env_cls) -> None:
    dataset_archive = getattr(env, "dataset_archive", None)
    if env.is_worker_env or not dataset_archive or not Path(dataset_archive).exists():
        return

    dataset_root = (Path(env.app_data_rel) / "dataset").expanduser()
    archive_mtime = Path(dataset_archive).stat().st_mtime
    stamp_path = dataset_root / ".agilab_dataset_stamp"
    existing_files = (
        [p for p in dataset_root.rglob("*") if p != stamp_path and p.is_file()]
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
        needs_extract = False

    if not needs_extract:
        return
    try:
        env.unzip_data(Path(dataset_archive), env.app_data_rel, force_extract=True)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover - defensive guard
        env_cls.logger.warning("Failed to extract packaged dataset %s: %s", dataset_archive, exc)


def _finalize_non_worker_runtime(
    env,
    *,
    env_cls,
    optional_agi_pages_bundles_root_fn: Callable[[], Path | None],
    ensure_dir_fn: Callable[[str | Path], Path],
) -> None:
    ensure_dir_fn(env.app_src)
    app_src_str = str(env.app_src)
    if app_src_str not in sys.path:
        sys.path.append(app_src_str)

    examples_candidates = [
        env.agilab_pck / "agilab/examples",
        env.agilab_pck / "examples",
    ]
    for candidate in examples_candidates:
        if candidate.exists():
            env.examples = candidate
            break
    else:
        env.examples = examples_candidates[-1]

    env.init_envars_app(env.envars)
    env._init_apps()
    env.export_local_bin = "" if os.name == "nt" else 'export PATH="~/.local/bin:$PATH";'
