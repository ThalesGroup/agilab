"""Startup and environment bootstrap helpers for the AGILab About page."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional

from agi_env.credential_store_support import CLUSTER_CREDENTIALS_KEY, KEYRING_SENTINEL


@dataclass
class BootstrapResult:
    """Result of a first-run Streamlit environment bootstrap."""

    env: Any | None
    should_rerun: bool = False
    handled_recovery: bool = False


@dataclass(frozen=True)
class BootstrapPorts:
    """External services used by the About-page bootstrap flow."""

    agi_env_cls: Any
    activate_mlflow: Callable[[Any], Any]
    background_services_enabled: Callable[[], bool]
    load_last_active_app: Callable[[], Any]
    store_last_active_app: Callable[[Path], Any]
    environ: MutableMapping[str, str]


def default_bootstrap_ports() -> BootstrapPorts:
    """Load production adapters for the About-page bootstrap flow."""
    from agi_env import AgiEnv
    from agi_gui.pagelib import activate_mlflow, background_services_enabled
    from agi_gui.ui_support import load_last_active_app, store_last_active_app

    return BootstrapPorts(
        agi_env_cls=AgiEnv,
        activate_mlflow=activate_mlflow,
        background_services_enabled=background_services_enabled,
        load_last_active_app=load_last_active_app,
        store_last_active_app=store_last_active_app,
        environ=os.environ,
    )


def parse_startup_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse supported Streamlit entrypoint arguments."""
    parser = argparse.ArgumentParser(description="Run the AGI Streamlit App with optional parameters.")
    parser.add_argument(
        "--apps-path",
        type=str,
        help="Where you store your apps (default is ./)",
        default=None,
    )
    parser.add_argument(
        "--active-app",
        type=str,
        help="App name or path to select on startup (mirrors ?active_app= query parameter).",
        default=None,
    )
    args, _ = parser.parse_known_args(argv)
    return args


def default_agilab_path_file(
    *,
    os_name: str = os.name,
    environ: Mapping[str, str] | None = None,
    home_path: Path | None = None,
) -> Path:
    """Return the platform-specific AGILAB install marker path."""
    environ = environ or os.environ
    home_path = home_path or Path.home()
    if os_name == "nt":
        return Path(environ.get("LOCALAPPDATA", "")) / "agilab/.agilab-path"
    return home_path / ".local/share/agilab/.agilab-path"


def apps_path_from_agilab_path_file(agi_path_file: Path) -> Path:
    """Resolve the apps directory from a packaged-install ``.agilab-path`` file."""
    agilab_path = agi_path_file.read_text(encoding="utf-8").strip()
    if not agilab_path:
        raise FileNotFoundError(f"Empty .agilab-path at {agi_path_file}")
    before, sep, _after = agilab_path.rpartition(".venv")
    if not sep:
        raise ValueError(f"Malformed .agilab-path (missing .venv marker): {agilab_path!r}")
    try:
        return (Path(before).resolve(strict=False) / "apps").resolve(strict=False)
    except OSError as path_err:
        raise ValueError(f"Cannot resolve apps path from .agilab-path: {path_err}") from path_err


def resolve_apps_path(
    args: argparse.Namespace,
    *,
    env_file_path: Path,
    load_env_file_map: Callable[[Path], Mapping[str, str]],
    os_name: str = os.name,
    environ: Mapping[str, str] | None = None,
    home_path: Path | None = None,
) -> Path | None:
    """Resolve the apps path from CLI, user .env, or packaged install marker."""
    apps_arg = args.apps_path
    if apps_arg is None:
        env_apps = load_env_file_map(env_file_path).get("APPS_PATH")
        if env_apps and env_apps.strip() and not env_apps.startswith("/path/to"):
            apps_arg = env_apps.strip()

    if apps_arg is None:
        agi_path_file = default_agilab_path_file(
            os_name=os_name,
            environ=environ,
            home_path=home_path,
        )
        apps_arg = apps_path_from_agilab_path_file(agi_path_file)

    return Path(apps_arg).expanduser() if apps_arg else None


def normalize_active_app_input(env: Any, raw_value: Optional[str]) -> Path | None:
    """Return a Path to the requested active app if the input is valid."""
    if not raw_value:
        return None

    candidates: list[Path] = []
    try:
        provided = Path(raw_value).expanduser()
    except (TypeError, RuntimeError, ValueError):
        return None

    if provided.is_absolute():
        candidates.append(provided)
    else:
        candidates.append((Path.cwd() / provided).resolve())
        candidates.append((env.apps_path / provided).resolve())
        candidates.append((env.apps_path / provided.name).resolve())

    if raw_value in env.projects:
        candidates.insert(0, (env.apps_path / raw_value).resolve())
    elif provided.name in env.projects:
        candidates.insert(0, (env.apps_path / provided.name).resolve())

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate.exists():
            return candidate
    return None


def apply_active_app_request(env: Any, request_value: Optional[str], *, streamlit: Any) -> bool:
    """Switch AgiEnv to the requested app name/path; returns True if a change occurred."""
    target_path = normalize_active_app_input(env, request_value)
    if not target_path:
        return False

    target_name = target_path.name
    if target_name == env.app:
        return False
    try:
        env.change_app(target_path)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        streamlit.warning(f"Unable to switch to project '{target_name}': {exc}")
        return False
    return True


def sync_active_app_from_query(
    env: Any,
    *,
    streamlit: Any,
    store_last_active_app: Callable[[Path], Any],
    apply_request: Callable[[Any, Optional[str]], bool],
) -> None:
    """Honor ?active_app=... query parameter so all pages stay in sync."""
    try:
        requested = streamlit.query_params.get("active_app")
    except (AttributeError, RuntimeError, TypeError):
        requested = None

    if isinstance(requested, (list, tuple)):
        requested_value = requested[0] if requested else None
    else:
        requested_value = requested

    changed = False
    if requested_value:
        changed = apply_request(env, str(requested_value))

    if not requested_value or changed or requested_value != env.app:
        try:
            streamlit.query_params["active_app"] = env.app
        except (AttributeError, RuntimeError, TypeError):
            pass

    try:
        if changed:
            store_last_active_app(Path(env.apps_path) / env.app)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def persist_bootstrap_env(
    env: Any,
    *,
    apps_path: Path,
    explicit_apps_path: bool,
    saved_env: Mapping[str, str],
    agi_env_cls: Any,
    clean_openai_key: Callable[[str | None], str | None],
    store_cluster_credentials: Callable[..., bool],
    environ: MutableMapping[str, str] | None = None,
    logger: Any = None,
) -> bool:
    """Persist and mirror startup environment defaults. Returns True if OpenAI is missing."""
    environ = environ if environ is not None else os.environ
    openai_api_key = clean_openai_key(getattr(env, "OPENAI_API_KEY", None))
    cluster_credentials = getattr(env, "CLUSTER_CREDENTIALS", None) or ""

    def init_env_var(key: str, value: str, *, force: bool = False) -> None:
        environ[key] = value
        if hasattr(env, "envars") and isinstance(env.envars, dict):
            env.envars[key] = value
        if force or key not in saved_env:
            agi_env_cls.set_env_var(key, value)

    if openai_api_key:
        init_env_var("OPENAI_API_KEY", openai_api_key)
    if cluster_credentials:
        environ[CLUSTER_CREDENTIALS_KEY] = cluster_credentials
        if hasattr(env, "envars") and isinstance(env.envars, dict):
            env.envars[CLUSTER_CREDENTIALS_KEY] = cluster_credentials
        if CLUSTER_CREDENTIALS_KEY not in saved_env:
            if store_cluster_credentials(cluster_credentials, environ=environ, logger=logger):
                agi_env_cls.set_env_var(CLUSTER_CREDENTIALS_KEY, KEYRING_SENTINEL)
            else:
                agi_env_cls.set_env_var(CLUSTER_CREDENTIALS_KEY, cluster_credentials)
    else:
        init_env_var(CLUSTER_CREDENTIALS_KEY, "")

    init_env_var("IS_SOURCE_ENV", str(int(bool(env.is_source_env))))
    init_env_var("IS_WORKER_ENV", str(int(bool(env.is_worker_env))))
    init_env_var("APPS_PATH", str(apps_path), force=explicit_apps_path)
    return not bool(openai_api_key)


def remember_active_app(env: Any, store_last_active_app: Callable[[Path], Any]) -> None:
    """Persist the latest active app path when possible."""
    try:
        store_last_active_app(Path(env.apps_path) / env.app)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def stop_startup_with_error(streamlit: Any, message: str) -> None:
    """Render a startup error and stop when the Streamlit API is available."""
    streamlit.error(message)
    stop = getattr(streamlit, "stop", None)
    if callable(stop):
        stop()


def bootstrap_page_environment(
    *,
    streamlit: Any,
    env_file_path: Path,
    load_env_file_map: Callable[[Path], Mapping[str, str]],
    logger: Any,
    apply_active_app_request: Callable[[Any, Optional[str]], bool],
    handle_data_root_failure: Callable[..., bool],
    refresh_env_from_file: Callable[[Any], None],
    clean_openai_key: Callable[[str | None], str | None],
    store_cluster_credentials: Callable[..., bool],
    argv: list[str] | None = None,
    ports: BootstrapPorts | None = None,
) -> BootstrapResult:
    """Create and persist the AGILAB environment for a cold Streamlit session."""
    ports = ports or default_bootstrap_ports()
    args = parse_startup_args(argv)
    try:
        apps_path = resolve_apps_path(
            args,
            env_file_path=env_file_path,
            load_env_file_map=load_env_file_map,
        )
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        stop_startup_with_error(streamlit, f"Unable to resolve AGILAB apps path: {exc}")
        return BootstrapResult(env=None, handled_recovery=True)

    if apps_path is None:
        stop_startup_with_error(streamlit, "Error: Missing mandatory parameter: --apps-path")
        return BootstrapResult(env=None, handled_recovery=True)

    streamlit.session_state["apps_path"] = str(apps_path)

    try:
        env = ports.agi_env_cls(apps_path=apps_path, verbose=1)
    except RuntimeError as exc:
        if handle_data_root_failure(exc, agi_env_cls=ports.agi_env_cls):
            return BootstrapResult(env=None, handled_recovery=True)
        raise

    requested_app = args.active_app
    if not requested_app:
        last_app = ports.load_last_active_app()
        if last_app:
            requested_app = str(last_app)
    apply_active_app_request(env, requested_app)

    env.init_done = True
    streamlit.session_state["env"] = env
    streamlit.session_state["IS_SOURCE_ENV"] = env.is_source_env
    streamlit.session_state["IS_WORKER_ENV"] = env.is_worker_env

    services_enabled = ports.background_services_enabled()
    if services_enabled and not streamlit.session_state.get("server_started"):
        ports.activate_mlflow(env)

    remember_active_app(env, ports.store_last_active_app)

    try:
        refresh_env_from_file(env)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass

    saved_env = load_env_file_map(env_file_path)
    openai_missing = persist_bootstrap_env(
        env,
        apps_path=apps_path,
        explicit_apps_path=bool(args.apps_path),
        saved_env=saved_env,
        agi_env_cls=ports.agi_env_cls,
        clean_openai_key=clean_openai_key,
        store_cluster_credentials=store_cluster_credentials,
        environ=ports.environ,
        logger=logger,
    )
    if openai_missing:
        streamlit.warning("OPENAI_API_KEY not set. OpenAI-powered features will be disabled.")

    streamlit.session_state["first_run"] = False
    try:
        streamlit.query_params["active_app"] = env.app
    except (AttributeError, RuntimeError, TypeError):
        pass
    return BootstrapResult(env=env, should_rerun=services_enabled)
