"""Startup and environment bootstrap helpers for the AGILAB main page."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, MutableMapping, Optional

from agi_env.app_settings_support import (
    find_source_app_settings_file,
    read_app_settings,
    update_app_settings,
)
from agi_env.credential_store_support import CLUSTER_CREDENTIALS_KEY, KEYRING_SENTINEL
from agi_env.project.app_provider_registry import (
    discover_installed_app_projects,
    resolve_installed_app_project,
)
from agi_env.runtime.process_support import fix_windows_drive
from agi_env.runtime.repository_support import get_apps_repository_root
from agi_env.ui.sidecar_registry import hosted_inline_render_guard

try:  # pragma: no cover - optional import fallback is exercised through behavior tests
    import tomli_w as _tomli_writer
except ModuleNotFoundError:  # pragma: no cover - dependency is present in AGILAB envs
    _tomli_writer = None


DEFAULT_STARTUP_APP_NAME = "flight_telemetry_project"


@dataclass
class BootstrapResult:
    """Result of a first-run Streamlit environment bootstrap."""

    env: Any | None
    should_rerun: bool = False
    handled_recovery: bool = False


@dataclass(frozen=True)
class BootstrapPorts:
    """External services used by the main-page bootstrap flow."""

    agi_env_cls: Any
    activate_mlflow: Callable[[Any], Any]
    background_services_enabled: Callable[[], bool]
    load_last_active_app: Callable[[], Any]
    store_last_active_app: Callable[[Path], Any]
    environ: MutableMapping[str, str]


@dataclass(frozen=True)
class StartupAppRequest:
    """Project selection resolved before an ``AgiEnv`` instance exists."""

    name: str
    target_path: Path
    source: str
    authorized_container_roots: tuple[Path, ...] = field(
        default_factory=tuple,
        compare=False,
        repr=False,
    )


def default_bootstrap_ports() -> BootstrapPorts:
    """Load production adapters for the main-page bootstrap flow."""
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
    with hosted_inline_render_guard():
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
    """Resolve the apps directory from a source or packaged-install ``.agilab-path`` file."""
    agilab_path = agi_path_file.read_text(encoding="utf-8").strip()
    if not agilab_path:
        raise FileNotFoundError(f"Empty .agilab-path at {agi_path_file}")
    before, sep, _after = agilab_path.rpartition(".venv")
    if not sep:
        source_root = Path(agilab_path).expanduser()
        if source_root.name == "agilab" and source_root.parent.name == "src":
            try:
                return (source_root / "apps").resolve(strict=False)
            except OSError as path_err:
                raise ValueError(f"Cannot resolve apps path from .agilab-path: {path_err}") from path_err
        raise ValueError(f"Malformed .agilab-path (missing .venv marker): {agilab_path!r}")
    try:
        return (Path(before).resolve(strict=False) / "apps").resolve(strict=False)
    except OSError as path_err:
        raise ValueError(f"Cannot resolve apps path from .agilab-path: {path_err}") from path_err


def _looks_like_source_apps_path(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        resolved = Path(path).resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        resolved = Path(path)
    if resolved.name == "builtin":
        resolved = resolved.parent
    return (
        resolved.name == "apps"
        and resolved.parent.name == "agilab"
        and resolved.parent.parent.name == "src"
    )


def source_launch_env_updates(apps_path: Path | None) -> dict[str, str]:
    """Return pre-init env overrides required for source-checkout launches."""
    if not _looks_like_source_apps_path(apps_path):
        return {}
    try:
        apps_path = Path(apps_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        apps_path = Path(apps_path)
    if apps_path.name == "builtin":
        apps_path = apps_path.parent
    return {
        "APPS_PATH": str(apps_path),
        "IS_SOURCE_ENV": "1",
        "IS_WORKER_ENV": "0",
    }


def _is_already_initialised_env_error(exc: BaseException) -> bool:
    return "AgiEnv is already initialised with a different configuration" in str(exc)


def _project_switch_failure_message(target_name: str, exc: BaseException) -> str:
    if _is_already_initialised_env_error(exc):
        return (
            f"Unable to switch to project '{target_name}'. Refresh the page or "
            "restart AGILAB, then select the project again."
        )
    return f"Unable to switch to project '{target_name}': {exc}"


def _normalize_path(value: Any) -> Path | None:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _canonical_apps_path(value: Any) -> Path | None:
    path = _normalize_path(value)
    if path is not None and path.name == "builtin":
        return path.parent
    return path


def _existing_env_matches_apps_path(env: Any, apps_path: Path) -> bool:
    expected = _canonical_apps_path(apps_path)
    if expected is None:
        return False

    env_apps_path = _canonical_apps_path(getattr(env, "apps_path", None))
    if env_apps_path is not None:
        return env_apps_path == expected

    active_app_path = _normalize_path(getattr(env, "active_app", None))
    if active_app_path is not None and _canonical_apps_path(active_app_path.parent) == expected:
        return True

    app_value = getattr(env, "app", None)
    try:
        explicit_app_path = Path(app_value).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        explicit_app_path = None
    if (
        explicit_app_path is not None
        and (explicit_app_path.is_absolute() or explicit_app_path.parent != Path("."))
    ):
        app_path = _normalize_path(app_value)
        if app_path is not None and _canonical_apps_path(app_path.parent) == expected:
            return True

    return False


def _streamlit_session_factory(agi_env_cls: Any) -> Callable[..., Any]:
    """Return the required UI factory or fail with an upgrade path."""
    session_factory = getattr(agi_env_cls, "session", None)
    if not callable(session_factory):
        raise RuntimeError(
            "This AGILAB UI requires AgiEnv.session() so each Streamlit session "
            "owns an isolated environment. Upgrade agi-env, restart AGILAB, and "
            "open a new browser session."
        )
    return session_factory


def _startup_runtime_authorized_roots(
    startup_app: StartupAppRequest,
    env: Any,
) -> tuple[Path, ...]:
    """Extend startup trust with the runtime-owned built-in app container."""
    roots = list(startup_app.authorized_container_roots)
    builtin_apps_path = _normalize_path(getattr(env, "builtin_apps_path", None))
    if builtin_apps_path is not None and builtin_apps_path not in roots:
        roots.append(builtin_apps_path)
    return tuple(roots)


def _streamlit_env_matches_startup_request(
    env: Any,
    startup_app: StartupAppRequest,
) -> bool:
    """Accept the exact target or a same-name fallback under runtime built-ins."""
    if getattr(env, "app", None) != startup_app.name:
        return False
    if _active_app_path_matches(env, startup_app.target_path):
        return True
    active_app = _normalize_path(getattr(env, "active_app", None))
    builtin_apps_path = _normalize_path(getattr(env, "builtin_apps_path", None))
    if active_app is None or builtin_apps_path is None:
        return False
    return active_app == (builtin_apps_path / startup_app.name).resolve(strict=False)


def _create_streamlit_session_env(
    agi_env_cls: Any,
    *,
    apps_path: Path,
    startup_app: StartupAppRequest,
    verbose: int,
) -> Any:
    """Create a UI-owned environment without borrowing the CLI singleton."""

    session_factory = _streamlit_session_factory(agi_env_cls)
    env = session_factory(
        apps_path=apps_path,
        active_app=startup_app.target_path,
        verbose=verbose,
    )
    if not getattr(env, "_agilab_session_scoped", False):
        raise RuntimeError(
            "AgiEnv.session() returned a legacy shared environment. Upgrade agi-env, "
            "restart AGILAB, and open a new browser session."
        )
    if not _streamlit_env_matches_startup_request(env, startup_app):
        raise RuntimeError(
            "AgiEnv.session() initialized a different project than the validated "
            f"startup target `{startup_app.target_path}`. Restart AGILAB and select "
            "the project again."
        )
    return env


def persist_preinit_launch_env(
    agi_env_cls: Any,
    updates: Mapping[str, str],
    *,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Persist launch-critical env values before constructing ``AgiEnv``."""
    if not updates:
        return
    environ = environ if environ is not None else os.environ
    setter = getattr(agi_env_cls, "set_env_var", None)
    for key, value in updates.items():
        environ[key] = value
        if callable(setter):
            setter(key, value)


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
    marker_apps_path: Path | None = None
    marker_error: Exception | None = None
    agi_path_file = default_agilab_path_file(
        os_name=os_name,
        environ=environ,
        home_path=home_path,
    )
    try:
        marker_apps_path = apps_path_from_agilab_path_file(agi_path_file)
    except (FileNotFoundError, ValueError) as exc:
        marker_error = exc

    if apps_arg is None and _looks_like_source_apps_path(marker_apps_path):
        apps_arg = marker_apps_path

    if apps_arg is None:
        env_apps = load_env_file_map(env_file_path).get("APPS_PATH")
        if env_apps and env_apps.strip() and not env_apps.startswith("/path/to"):
            apps_arg = env_apps.strip()

    if apps_arg is None:
        if marker_apps_path is not None:
            apps_arg = marker_apps_path
        elif marker_error is not None:
            raise marker_error

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

    def is_plain_app_name() -> bool:
        return (
            not provided.is_absolute()
            and provided.parent == Path(".")
            and "/" not in str(raw_value)
            and "\\" not in str(raw_value)
        )

    def add_root_candidate(root: Any, app_name: str) -> None:
        if not root or not app_name:
            return
        try:
            candidates.append((Path(root) / app_name).resolve())
        except (TypeError, RuntimeError, ValueError, OSError):
            return

    def prepend_root_candidate(root: Any, app_name: str) -> None:
        if not root or not app_name:
            return
        try:
            candidates.insert(0, (Path(root) / app_name).resolve())
        except (TypeError, RuntimeError, ValueError, OSError):
            return

    def source_checkout_project(candidate: Path) -> Path:
        if candidate.parent.name != "project":
            return candidate
        package_dir = candidate.parent.parent
        if not package_dir.name.startswith("agi_app_"):
            return candidate
        package_src = package_dir.parent
        package_root = package_src.parent
        if package_src.name != "src" or not package_root.name.startswith("agi-app-"):
            return candidate
        roots: list[Any] = [getattr(env, "builtin_apps_path", None)]
        apps_root = getattr(env, "apps_path", None)
        if apps_root:
            try:
                roots.append(Path(apps_root) / "builtin")
            except (TypeError, RuntimeError, ValueError):
                pass
        for root in roots:
            try:
                source_candidate = (Path(root) / candidate.name).resolve()
            except (TypeError, RuntimeError, ValueError, OSError):
                continue
            if source_candidate.exists():
                return source_candidate
        return candidate

    if provided.is_absolute():
        candidates.append(provided)
    else:
        if not is_plain_app_name():
            candidates.append((Path.cwd() / provided).resolve())
        add_root_candidate(getattr(env, "apps_path", None), str(provided))
        add_root_candidate(getattr(env, "apps_path", None), provided.name)
        add_root_candidate(getattr(env, "builtin_apps_path", None), str(provided))
        add_root_candidate(getattr(env, "builtin_apps_path", None), provided.name)
        add_root_candidate(getattr(env, "apps_repository_root", None), str(provided))
        add_root_candidate(getattr(env, "apps_repository_root", None), provided.name)
        if is_plain_app_name():
            candidates.append((Path.cwd() / provided).resolve())

    projects = getattr(env, "projects", set()) or set()
    if not provided.is_absolute():
        if raw_value in projects:
            for root in (
                getattr(env, "apps_repository_root", None),
                getattr(env, "builtin_apps_path", None),
                getattr(env, "apps_path", None),
            ):
                prepend_root_candidate(root, raw_value)
        elif provided.name in projects:
            for root in (
                getattr(env, "apps_repository_root", None),
                getattr(env, "builtin_apps_path", None),
                getattr(env, "apps_path", None),
            ):
                prepend_root_candidate(root, provided.name)

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        candidate = source_checkout_project(candidate)
        if candidate.exists():
            return candidate
    return None


def persisted_active_app_request(env: Any, raw_value: Any) -> str | None:
    """Resolve persisted app state as an app identity, not as authority over the launch root."""
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        path = Path(text).expanduser()
        name = path.name
    except (TypeError, RuntimeError, ValueError):
        return text
    if path.is_absolute():
        try:
            resolved_path = path.resolve(strict=False)
        except OSError:
            resolved_path = path
        for root in (
            getattr(env, "apps_path", None),
            getattr(env, "builtin_apps_path", None),
            getattr(env, "apps_repository_root", None),
        ):
            if not root:
                continue
            try:
                if resolved_path.is_relative_to(Path(root).resolve(strict=False)):
                    return text
            except (TypeError, RuntimeError, ValueError, OSError):
                continue
        if normalize_active_app_input(env, name) is not None:
            return name
        return None
    projects = getattr(env, "projects", set()) or set()
    if name in projects:
        return name
    return text


def _normalized_existing_or_requested_path(raw_value: Any) -> Path | None:
    try:
        return Path(raw_value).expanduser().resolve()
    except (TypeError, RuntimeError, ValueError, OSError):
        return None


def active_app_store_path(env: Any) -> Path:
    """Return the real active app path to persist for future launches."""
    active_app = getattr(env, "active_app", None)
    if active_app:
        try:
            return Path(active_app).expanduser()
        except (TypeError, RuntimeError, ValueError, OSError):
            pass
    return Path(env.apps_path) / env.app


def _active_app_path_matches(env: Any, target_path: Path) -> bool:
    current_path = getattr(env, "active_app", None)
    if current_path is None:
        return True
    normalized_current = _normalized_existing_or_requested_path(current_path)
    normalized_target = _normalized_existing_or_requested_path(target_path)
    if normalized_current is None or normalized_target is None:
        return False
    return normalized_current == normalized_target


def _rebootstrap_active_app_path(env: Any, target_path: Path, target_name: str, *, streamlit: Any) -> bool:
    """Switch to a resolved project path without using name-only change_app."""
    previous_init_done = getattr(env, "init_done", None)
    authorized_roots = getattr(env, "_agilab_authorized_app_container_roots", ())
    try:
        reinitialize = getattr(env, "reinitialize_for_app", None)
        if callable(reinitialize):
            reinitialize(
                apps_path=target_path.parent,
                app=target_name,
                verbose=getattr(env, "verbose", None),
            )
        else:
            env_cls = type(env)
            lock = getattr(env_cls, "_lock", None)
            if lock is None:
                env_cls.__init__(
                    env,
                    apps_path=target_path.parent,
                    app=target_name,
                    verbose=getattr(env, "verbose", None),
                    _agilab_reinitialize=True,
                )
            else:
                with lock:
                    env_cls.__init__(
                        env,
                        apps_path=target_path.parent,
                        app=target_name,
                        verbose=getattr(env, "verbose", None),
                        _agilab_reinitialize=True,
                    )
        if previous_init_done is not None:
            env.init_done = previous_init_done
        if authorized_roots:
            env._agilab_authorized_app_container_roots = authorized_roots
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        streamlit.warning(_project_switch_failure_message(target_name, exc))
        return False
    return True


def _bind_authorized_app_container_roots(
    env: Any,
    roots: tuple[Path, ...],
) -> None:
    """Bind immutable startup containers used for later query authorization."""
    normalized: list[Path] = []
    for root in roots:
        resolved = _normalize_path(root)
        if resolved is not None and resolved not in normalized:
            normalized.append(resolved)
    env._agilab_authorized_app_container_roots = tuple(normalized)


def _rebootstrap_same_named_active_app(
    env: Any, target_path: Path, target_name: str, *, streamlit: Any
) -> bool:
    """Switch to the same project name under another root without using name-only change_app."""
    return _rebootstrap_active_app_path(
        env,
        target_path,
        target_name,
        streamlit=streamlit,
    )


def apply_active_app_request(env: Any, request_value: Optional[str], *, streamlit: Any) -> bool:
    """Switch AgiEnv to the requested app name/path; returns True if a change occurred."""
    target_path = normalize_active_app_input(env, request_value)
    if not target_path:
        return False

    target_name = target_path.name
    if target_name == env.app:
        if _active_app_path_matches(env, target_path):
            return False
        return _rebootstrap_same_named_active_app(env, target_path, target_name, streamlit=streamlit)
    return _rebootstrap_active_app_path(env, target_path, target_name, streamlit=streamlit)


def sync_active_app_from_query(
    env: Any,
    *,
    streamlit: Any,
) -> bool:
    """Schedule a cold, atomic transition for a valid query-driven app change."""
    try:
        requested = streamlit.query_params.get("active_app")
    except (AttributeError, RuntimeError, TypeError):
        requested = None

    if isinstance(requested, (list, tuple)):
        requested_value = requested[0] if requested else None
    else:
        requested_value = requested

    transition_scheduled = False
    if requested_value and str(requested_value) != str(getattr(env, "app", "")):
        target_path = resolve_active_app_query_target(env, str(requested_value))
        target_matches_current = (
            target_path is not None
            and target_path.name == getattr(env, "app", None)
            and _active_app_path_matches(env, target_path)
        )
        if target_path is not None and not target_matches_current:
            rerun = getattr(streamlit, "rerun", None)
            session_state = getattr(streamlit, "session_state", None)
            if callable(rerun) and session_state is not None:
                try:
                    previous_first_run = session_state.get("first_run", False)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    previous_first_run = False
                try:
                    session_state["first_run"] = True
                    streamlit.query_params["active_app"] = str(target_path)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    try:
                        session_state["first_run"] = previous_first_run
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass
                else:
                    transition_scheduled = True
                    rerun()
                    return True

    if not requested_value or requested_value != env.app:
        try:
            streamlit.query_params["active_app"] = env.app
        except (AttributeError, RuntimeError, TypeError):
            pass
    return transition_scheduled


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
        store_last_active_app(active_app_store_path(env))
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def stop_startup_with_error(streamlit: Any, message: str) -> None:
    """Render a startup error and stop when the Streamlit API is available."""
    streamlit.error(message)
    stop = getattr(streamlit, "stop", None)
    if callable(stop):
        stop()


def is_cluster_share_startup_error(exc: BaseException) -> bool:
    """Return whether startup failed because a persisted cluster share is unusable."""
    message = str(exc)
    return message.startswith("Cluster mode requires AGI_CLUSTER_SHARE")


def cluster_share_startup_error_message(exc: BaseException) -> str:
    """Return a user-facing recovery message for stale/broken cluster settings."""
    return (
        f"{exc}\n\n"
        "Cluster mode is enabled for the active project, but the configured cluster share "
        "is not mounted and writable. Mount `AGI_CLUSTER_SHARE`, then reload AGILAB. "
        "To keep working locally, choose **Disable cluster mode and reload** below. "
        "Cluster execution stays disabled until you mount the share and re-enable it."
    )


def _startup_app_candidate(value: Any) -> tuple[str, str] | None:
    """Return a valid raw startup request and project basename."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    text = str(value or "").strip()
    if not text:
        return None
    app_name = Path(text).name
    if not app_name.endswith(("_project", "_worker")):
        return None
    return text, app_name


def _startup_apps_repository_root(
    saved_env: Mapping[str, str], ports: BootstrapPorts
) -> Path | None:
    """Resolve the configured external apps root with the runtime's own rules."""
    configured = str(
        saved_env.get("APPS_REPOSITORY") or ports.environ.get("APPS_REPOSITORY") or ""
    ).strip()
    if not configured:
        return None
    return get_apps_repository_root(
        envars={"APPS_REPOSITORY": configured},
        environ=ports.environ,
        logger=None,
        fix_windows_drive_fn=fix_windows_drive,
    )


def _path_matches_startup_root_candidate(
    path: Path,
    app_name: str,
    roots: tuple[Path, ...],
) -> bool:
    """Return whether ``path`` is an exact app candidate under an allowed root."""
    normalized_path = _normalize_path(path)
    if normalized_path is None:
        return False
    for root in roots:
        try:
            candidate = (root.expanduser() / app_name).resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if normalized_path == candidate:
            return True
    return False


def _path_is_allowed_startup_target(
    path: Path,
    app_name: str,
    *,
    container_roots: tuple[Path, ...],
    installed_projects: tuple[Any, ...],
) -> bool:
    """Allow exact configured-root candidates or provider-advertised paths."""
    if _path_matches_startup_root_candidate(path, app_name, container_roots):
        return True
    normalized_path = _normalize_path(path)
    if normalized_path is None:
        return False
    return any(
        normalized_path == _normalize_path(project.project_root)
        for project in installed_projects
    )


def _resolve_startup_candidate_path(
    raw_value: str,
    app_name: str,
    *,
    resolver_env: Any,
    allowed_roots: tuple[Path, ...],
    installed_projects: tuple[Any, ...],
) -> Path | None:
    """Resolve one existing startup project without accepting arbitrary paths."""
    try:
        provided = Path(raw_value).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    is_plain_name = not provided.is_absolute() and provided.parent == Path(".")
    if is_plain_name:
        target = normalize_active_app_input(resolver_env, raw_value)
        if target is None or not _path_is_allowed_startup_target(
            target,
            app_name,
            container_roots=allowed_roots,
            installed_projects=installed_projects,
        ):
            installed = resolve_installed_app_project(
                app_name,
                projects=installed_projects,
            )
            target = installed
    else:
        try:
            target = provided.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return None

    if target is None or not _path_is_allowed_startup_target(
        target,
        app_name,
        container_roots=allowed_roots,
        installed_projects=installed_projects,
    ):
        return None
    try:
        if not target.is_dir():
            return None
        return target.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def resolve_active_app_query_target(env: Any, raw_value: str) -> Path | None:
    """Resolve a warm-session query through the cold-start trust boundary."""
    candidate = _startup_app_candidate(raw_value)
    if candidate is None:
        return None
    raw_value, app_name = candidate
    allowed_roots = tuple(
        root
        for raw_root in getattr(
            env,
            "_agilab_authorized_app_container_roots",
            (),
        )
        if (root := _normalize_path(raw_root)) is not None
    )
    if not allowed_roots:
        return None

    target_path = _resolve_startup_candidate_path(
        raw_value,
        app_name,
        resolver_env=env,
        allowed_roots=allowed_roots,
        installed_projects=(),
    )
    if target_path is not None:
        return target_path

    try:
        installed_projects = tuple(discover_installed_app_projects())
    except (OSError, RuntimeError, TypeError, ValueError):
        installed_projects = ()
    if not installed_projects:
        return None
    return _resolve_startup_candidate_path(
        raw_value,
        app_name,
        resolver_env=env,
        allowed_roots=allowed_roots,
        installed_projects=installed_projects,
    )


def resolve_startup_app_request(
    *,
    streamlit: Any,
    args: argparse.Namespace,
    ports: BootstrapPorts,
    apps_path: Path,
    saved_env: Mapping[str, str],
    warm_env: Any | None = None,
) -> StartupAppRequest:
    """Resolve one existing project identity for construction and recovery.

    Explicit browser and CLI requests are authoritative but must resolve under
    the selected apps tree, configured apps repository, or an installed provider
    root. Remembered paths may rebase by project name into those current roots.
    """
    builtin_apps_path = (
        apps_path if apps_path.name == "builtin" else apps_path / "builtin"
    )
    apps_repository_root = _startup_apps_repository_root(saved_env, ports)
    try:
        installed_projects = tuple(discover_installed_app_projects())
    except (OSError, RuntimeError, TypeError, ValueError):
        installed_projects = ()
    allowed_roots = tuple(
        root
        for root in (
            apps_path,
            builtin_apps_path,
            apps_repository_root,
        )
        if root is not None
    )
    resolver_env = SimpleNamespace(
        apps_path=apps_path,
        builtin_apps_path=builtin_apps_path,
        apps_repository_root=apps_repository_root,
        projects={project.name for project in installed_projects},
    )

    def request_for(target_path: Path, source: str) -> StartupAppRequest:
        return StartupAppRequest(
            target_path.name,
            target_path,
            source,
            authorized_container_roots=allowed_roots,
        )

    def resolve_explicit(value: Any, source: str) -> StartupAppRequest | None:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        raw_value = str(value or "").strip()
        if not raw_value:
            return None
        candidate = _startup_app_candidate(raw_value)
        if candidate is None:
            raise ValueError(
                f"The {source} startup project must end in '_project' or '_worker'; "
                f"got {raw_value!r}."
            )
        raw_value, app_name = candidate
        target_path = _resolve_startup_candidate_path(
            raw_value,
            app_name,
            resolver_env=resolver_env,
            allowed_roots=allowed_roots,
            installed_projects=installed_projects,
        )
        if target_path is None:
            raise ValueError(
                f"The {source} startup project {raw_value!r} does not resolve to an "
                "existing app in the selected apps tree or a configured provider."
            )
        return request_for(target_path, source)

    try:
        query_value = streamlit.query_params.get("active_app")
    except (AttributeError, RuntimeError, TypeError):
        query_value = None

    for source, value in (("query", query_value), ("cli", args.active_app)):
        request = resolve_explicit(value, source)
        if request is not None:
            return request

    try:
        remembered_value = ports.load_last_active_app()
    except (OSError, RuntimeError, TypeError, ValueError):
        remembered_value = None
    remembered = _startup_app_candidate(remembered_value)
    if remembered is not None:
        raw_value, app_name = remembered
        target_path = _resolve_startup_candidate_path(
            raw_value,
            app_name,
            resolver_env=resolver_env,
            allowed_roots=allowed_roots,
            installed_projects=installed_projects,
        )
        if target_path is None:
            target_path = _resolve_startup_candidate_path(
                app_name,
                app_name,
                resolver_env=resolver_env,
                allowed_roots=allowed_roots,
                installed_projects=installed_projects,
            )
        if target_path is not None:
            return request_for(target_path, "last")

    if getattr(
        warm_env, "_agilab_session_scoped", False
    ) and _existing_env_matches_apps_path(warm_env, apps_path):
        warm_candidate = _startup_app_candidate(getattr(warm_env, "app", None))
        warm_path = _normalize_path(getattr(warm_env, "active_app", None))
        if warm_candidate is not None and warm_path is not None:
            _raw_value, app_name = warm_candidate
            validated_warm_path = _resolve_startup_candidate_path(
                str(warm_path),
                app_name,
                resolver_env=resolver_env,
                allowed_roots=allowed_roots,
                installed_projects=installed_projects,
            )
            if validated_warm_path is not None:
                return request_for(validated_warm_path, "warm")

    configured_default_value = str(saved_env.get("APP_DEFAULT") or "").strip()
    if configured_default_value:
        request = resolve_explicit(configured_default_value, "APP_DEFAULT")
        if request is not None:
            return request_for(request.target_path, "default")

    request = resolve_explicit(DEFAULT_STARTUP_APP_NAME, "built-in default")
    if request is None:  # pragma: no cover - the constant is non-empty
        raise ValueError("The built-in default project is empty.")
    return request_for(request.target_path, "default")


def startup_app_source_settings_file(
    startup_app: StartupAppRequest,
    *,
    apps_path: Path,
    saved_env: Mapping[str, str],
    ports: BootstrapPorts,
) -> Path | None:
    """Resolve source settings through the same search contract as ``AgiEnv``."""
    builtin_apps_path = (
        apps_path if apps_path.name == "builtin" else apps_path / "builtin"
    )
    source_envars = dict(ports.environ)
    source_envars.update(saved_env)
    source_settings = find_source_app_settings_file(
        target_app=startup_app.name,
        current_app=startup_app.name,
        app_src=startup_app.target_path / "src",
        active_app=startup_app.target_path,
        apps_path=apps_path,
        builtin_apps_path=builtin_apps_path,
        apps_repository_root=_startup_apps_repository_root(saved_env, ports),
        home_abs=Path.home(),
        envars=source_envars,
    )
    if source_settings is None:
        return None
    try:
        return source_settings if source_settings.is_file() else None
    except OSError:
        # Preserve an inaccessible selected path so the recovery write fails
        # closed instead of treating it as an authoritatively source-less app.
        return source_settings


def startup_active_app_name(streamlit: Any, args: argparse.Namespace, ports: BootstrapPorts) -> str | None:
    """Resolve the active app name before an ``AgiEnv`` instance exists."""
    query_params = getattr(streamlit, "query_params", {}) or {}
    query_value = None
    try:
        query_value = query_params.get("active_app")
    except AttributeError:
        query_value = None

    candidates = [query_value, args.active_app]
    try:
        candidates.append(ports.load_last_active_app())
    except (OSError, RuntimeError, TypeError, ValueError):
        pass

    for value in candidates:
        candidate = _startup_app_candidate(value)
        if candidate is not None:
            _raw_value, app_name = candidate
            return app_name
    return None


def workspace_app_settings_file(env_file_path: Path, app_name: str | None) -> Path | None:
    """Return the mutable per-user app settings path for a pre-init app name."""
    if not app_name:
        return None
    settings_path = (
        env_file_path.expanduser().parent / "apps" / app_name / "app_settings.toml"
    )
    _resolve_confined_workspace_settings_path(settings_path)
    return settings_path


def _resolve_confined_workspace_settings_path(settings_path: Path) -> Path:
    """Resolve one direct workspace settings target without following redirects."""
    lexical_path = settings_path.expanduser()
    try:
        workspace_apps_root = lexical_path.parents[1].resolve(strict=False)
        resolved_app_dir = lexical_path.parent.resolve(strict=False)
        resolved_settings = lexical_path.resolve(strict=False)
    except (IndexError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError(
            f"Cannot safely resolve workspace settings path `{lexical_path}`."
        ) from exc

    expected_app_dir = workspace_apps_root / lexical_path.parent.name
    expected_settings = expected_app_dir / lexical_path.name
    if resolved_app_dir != expected_app_dir or resolved_settings != expected_settings:
        raise ValueError(
            f"Workspace settings path `{lexical_path}` resolves outside its direct "
            f"workspace app directory `{expected_app_dir}`."
        )
    return resolved_settings


def disable_cluster_in_app_settings(
    settings_path: Path,
    *,
    source_settings_path: Path | None = None,
    source_settings_resolved: bool = False,
) -> bool:
    """Seed complete workspace settings, then disable cluster mode atomically."""
    if _tomli_writer is None:
        raise RuntimeError("Writing settings requires the 'tomli-w' package.")
    settings_path = _resolve_confined_workspace_settings_path(settings_path)

    def _disable_cluster(payload: dict[str, Any]) -> bool:
        missing_workspace = not settings_path.exists()
        if missing_workspace:
            if source_settings_path is not None:
                try:
                    source_exists = source_settings_path.is_file()
                except OSError as exc:
                    raise OSError(
                        "Cannot safely create workspace settings because the selected "
                        f"source settings `{source_settings_path}` cannot be inspected."
                    ) from exc
                if not source_exists:
                    raise FileNotFoundError(
                        "Cannot safely create workspace settings because the selected "
                        f"source settings `{source_settings_path}` no longer exist."
                    )
                payload.update(read_app_settings(source_settings_path))
            elif not source_settings_resolved:
                raise FileNotFoundError(
                    "Cannot safely create workspace settings because the complete "
                    f"source settings for `{settings_path.parent.name}` were not found."
                )
        cluster = payload.get("cluster")
        if cluster is None:
            cluster = {}
            payload["cluster"] = cluster
        elif not isinstance(cluster, dict):
            raise ValueError("The [cluster] settings section must be a TOML table.")
        if cluster.get("cluster_enabled") is False:
            return missing_workspace
        cluster["cluster_enabled"] = False
        return True

    _payload, changed = update_app_settings(
        settings_path,
        _disable_cluster,
        create_missing=True,
        dump_fn=_tomli_writer.dump,
    )
    return changed


def handle_cluster_share_startup_error(
    *,
    streamlit: Any,
    exc: BaseException,
    env_file_path: Path,
    args: argparse.Namespace,
    ports: BootstrapPorts,
    app_name: str | None = None,
    source_settings_path: Path | None = None,
    source_settings_resolved: bool = False,
    handle_data_root_failure: Callable[..., bool] | None = None,
) -> None:
    """Render cluster-share recovery controls before stopping startup."""
    app_name = app_name or startup_active_app_name(streamlit, args, ports)
    settings_path_error: str | None = None
    try:
        settings_path = workspace_app_settings_file(env_file_path, app_name)
    except (OSError, RuntimeError, ValueError) as path_err:
        settings_path = None
        settings_path_error = str(path_err)
    message = cluster_share_startup_error_message(exc)
    if settings_path is not None:
        message = f"{message}\n\nWorkspace settings: `{settings_path}`"
    elif settings_path_error:
        message = (
            f"{message}\n\nAutomatic local recovery is unavailable: "
            f"{settings_path_error}"
        )
    streamlit.error(message)

    button = getattr(streamlit, "button", None)
    if callable(button) and settings_path is not None and button("Disable cluster mode and reload"):
        try:
            changed = disable_cluster_in_app_settings(
                settings_path,
                source_settings_path=source_settings_path,
                source_settings_resolved=source_settings_resolved,
            )
        except (OSError, RuntimeError, ValueError) as write_err:
            streamlit.error(
                f"Could not disable cluster mode in `{settings_path}`: {write_err}"
            )
        else:
            if changed:
                streamlit.success(f"Disabled cluster mode in `{settings_path}`.")
                rerun = getattr(streamlit, "rerun", None)
                if callable(rerun):
                    rerun()
                return
            streamlit.error(
                f"Cluster mode was already disabled in `{settings_path}`; startup "
                "was not reloaded because the reported cluster failure would persist."
            )

    if handle_data_root_failure is not None:
        handle_data_root_failure(
            exc,
            agi_env_cls=ports.agi_env_cls,
            env_file_path=env_file_path,
            render_intro=False,
        )

    stop = getattr(streamlit, "stop", None)
    if callable(stop):
        stop()


def bootstrap_page_environment(
    *,
    streamlit: Any,
    env_file_path: Path,
    load_env_file_map: Callable[..., Mapping[str, str]],
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
    preinit_updates = source_launch_env_updates(apps_path)
    warm_env = streamlit.session_state.get("env")
    try:
        startup_env = load_env_file_map(env_file_path, include_commented=False)
        startup_app = resolve_startup_app_request(
            streamlit=streamlit,
            args=args,
            ports=ports,
            apps_path=apps_path,
            saved_env=startup_env,
            warm_env=warm_env,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        stop_startup_with_error(
            streamlit, f"Unable to resolve AGILAB startup project: {exc}"
        )
        return BootstrapResult(env=None, handled_recovery=True)
    source_settings_path = startup_app_source_settings_file(
        startup_app,
        apps_path=apps_path,
        saved_env=startup_env,
        ports=ports,
    )
    persist_preinit_launch_env(
        ports.agi_env_cls,
        preinit_updates,
        environ=ports.environ,
    )

    _streamlit_session_factory(ports.agi_env_cls)
    if (
        getattr(warm_env, "_agilab_session_scoped", False)
        and _existing_env_matches_apps_path(warm_env, apps_path)
        and getattr(warm_env, "app", None) == startup_app.name
        and _active_app_path_matches(warm_env, startup_app.target_path)
    ):
        env = warm_env
    else:
        try:
            env = _create_streamlit_session_env(
                ports.agi_env_cls,
                apps_path=apps_path,
                startup_app=startup_app,
                verbose=1,
            )
        except RuntimeError as exc:
            if is_cluster_share_startup_error(exc):
                handle_cluster_share_startup_error(
                    streamlit=streamlit,
                    exc=exc,
                    env_file_path=env_file_path,
                    args=args,
                    ports=ports,
                    app_name=startup_app.name,
                    source_settings_path=source_settings_path,
                    source_settings_resolved=True,
                    handle_data_root_failure=handle_data_root_failure,
                )
                return BootstrapResult(env=None, handled_recovery=True)
            if handle_data_root_failure(
                exc,
                agi_env_cls=ports.agi_env_cls,
                env_file_path=env_file_path,
            ):
                return BootstrapResult(env=None, handled_recovery=True)
            raise

    _bind_authorized_app_container_roots(
        env,
        _startup_runtime_authorized_roots(startup_app, env),
    )
    env.init_done = True
    streamlit.session_state["env"] = env
    streamlit.session_state["IS_SOURCE_ENV"] = env.is_source_env
    streamlit.session_state["IS_WORKER_ENV"] = env.is_worker_env

    services_enabled = ports.background_services_enabled()
    if services_enabled:
        # The process registry, not a session boolean, is the ownership source
        # of truth. Re-entering bootstrap must verify or relaunch the service.
        ports.activate_mlflow(env)

    remember_active_app(env, ports.store_last_active_app)

    try:
        refresh_env_from_file(env)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass

    saved_env = load_env_file_map(env_file_path)
    persist_bootstrap_env(
        env,
        apps_path=apps_path,
        explicit_apps_path=bool(args.apps_path) or bool(preinit_updates),
        saved_env=saved_env,
        agi_env_cls=ports.agi_env_cls,
        clean_openai_key=clean_openai_key,
        store_cluster_credentials=store_cluster_credentials,
        environ=ports.environ,
        logger=logger,
    )
    streamlit.session_state["first_run"] = False
    try:
        streamlit.query_params["active_app"] = env.app
    except (AttributeError, RuntimeError, TypeError):
        pass
    return BootstrapResult(env=env, should_rerun=services_enabled)
