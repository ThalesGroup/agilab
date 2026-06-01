from __future__ import annotations

import html
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


DATA_SHARE_SCAN_LIMIT = 200

INCOMPLETE_HEALTH_TOKENS = (
    "check",
    "empty",
    "incomplete",
    "missing",
    "no run",
    "needs",
    "not configured",
    "not selected",
    "not set",
    "optional",
    "stale",
    "unknown",
)


@dataclass(frozen=True)
class EnvironmentHealthCard:
    label: str
    value: str
    caption: str
    state: str = "ready"


@dataclass(frozen=True)
class EnvironmentHealth:
    cards: tuple[EnvironmentHealthCard, ...]
    details: tuple[tuple[str, str], ...]


def safe_display_path(value: Any) -> str:
    if value in (None, ""):
        return "not configured"
    try:
        return str(Path(value).expanduser())
    except (TypeError, ValueError, RuntimeError):
        return str(value)


def compact_path_caption(value: Any, *, fallback: str = "see environment details") -> str:
    """Return a card-safe path label while keeping the full path for details."""

    display = safe_display_path(value)
    lowered = display.lower()
    if lowered in {"", "not configured", "unknown"}:
        return display
    if os.sep not in display and (os.altsep is None or os.altsep not in display):
        return display if len(display) <= 48 else fallback
    try:
        path = Path(display)
    except (TypeError, ValueError, RuntimeError):
        return fallback

    name = path.name or display
    parent = path.parent.name
    if parent and parent not in {".", os.sep}:
        return f"{name} in {parent}"
    return name if len(name) <= 48 else fallback


def compact_data_share_caption(caption: str) -> str:
    if " in " in caption:
        return caption.split(" in ", 1)[0]
    return compact_path_caption(caption)


def header_value_state(value: str, caption: str = "", *, explicit: str | None = None) -> str:
    if explicit in {"ready", "incomplete"}:
        return explicit
    normalized = f"{value or ''} {caption or ''}".strip().lower()
    if not normalized:
        return "incomplete"
    if any(token in normalized for token in INCOMPLETE_HEALTH_TOKENS):
        return "incomplete"
    return "ready"


def render_health_card(streamlit: Any, card: EnvironmentHealthCard) -> None:
    state = header_value_state(card.value, card.caption, explicit=card.state)
    streamlit.markdown(
        (
            f"<div class='agilab-header-card agilab-header-card--{state}'>"
            f"<div class='agilab-header-label'>{html.escape(card.label)}</div>"
            f"<div class='agilab-header-value agilab-header-value--{state}'>{html.escape(str(card.value))}</div>"
            f"<div class='agilab-header-caption'>{html.escape(card.caption)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_environment_details(streamlit: Any, rows: Sequence[tuple[str, Any]]) -> None:
    details = [(label, safe_display_path(value)) for label, value in rows if value not in (None, "")]
    if not details:
        return
    with streamlit.expander("Environment details", expanded=False):
        streamlit.code("\n".join(f"{label}: {value}" for label, value in details), language="text")


def format_byte_size(byte_count: int) -> str:
    value = float(max(byte_count, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            precision = 0 if value >= 10 else 1
            return f"{value:.{precision}f} {unit}"
        value /= 1024
    return f"{int(value)} B"


def data_share_content_summary(path_value: Any) -> tuple[str, str]:
    display_path = safe_display_path(path_value)
    if display_path == "not configured":
        return "not configured", display_path
    try:
        path = Path(path_value).expanduser()
    except (TypeError, ValueError, RuntimeError):
        return "not configured", str(path_value)

    try:
        if not path.exists():
            return "missing", display_path
        if path.is_file():
            size = path.stat().st_size
            return ("empty" if size <= 0 else format_byte_size(size)), display_path
        if not path.is_dir():
            return "unknown", display_path

        total_size = 0
        file_count = 0
        truncated = False
        for root, dirs, files in os.walk(path):
            dirs[:] = [dirname for dirname in dirs if not (Path(root) / dirname).is_symlink()]
            for filename in files:
                candidate = Path(root) / filename
                if candidate.is_symlink():
                    continue
                try:
                    total_size += candidate.stat().st_size
                except OSError:
                    continue
                file_count += 1
                if file_count >= DATA_SHARE_SCAN_LIMIT:
                    truncated = True
                    break
            if truncated:
                break
    except OSError:
        return "unknown", display_path

    if file_count == 0 or total_size <= 0:
        return "empty", display_path
    size_label = format_byte_size(total_size)
    file_label = f"{file_count} file" if file_count == 1 else f"{file_count} files"
    if truncated:
        size_label = f"{size_label}+"
        file_label = f"{file_count}+ files"
    return size_label, f"{file_label} in {display_path}"


def path_status(path: Any, *, venv: bool = False, file: bool = False) -> tuple[str, str]:
    if path in (None, ""):
        return "not configured", "not configured"
    try:
        candidate = Path(path)
    except (TypeError, ValueError, RuntimeError):
        return "not configured", str(path)
    if venv:
        python_bin = candidate / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if python_bin.exists():
            return "ready", safe_display_path(candidate)
        if candidate.exists() or candidate.is_symlink():
            return "incomplete", safe_display_path(candidate)
        return "missing", safe_display_path(candidate)
    if file:
        status = "ready" if candidate.exists() and candidate.is_file() else "missing"
        return status, safe_display_path(candidate)
    status = "ready" if candidate.exists() or candidate.is_symlink() else "missing"
    return status, safe_display_path(candidate)


def latest_project_mtime(project_root: Path | None) -> str:
    if project_root is None or not project_root.exists():
        return "unknown"
    try:
        latest = project_root.stat().st_mtime
        ignored_dirs = {".venv", "__pycache__", ".git"}
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [dirname for dirname in dirs if dirname not in ignored_dirs]
            for name in files:
                latest = max(latest, (Path(root) / name).stat().st_mtime)
    except OSError:
        return "unknown"
    return datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")


def run_history_summary(env: Any) -> tuple[str, str]:
    runenv = getattr(env, "runenv", None)
    if runenv:
        log_dir = Path(runenv)
    else:
        app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "app")
        log_dir = Path.home() / "log" / "execute" / app_name

    try:
        run_logs = sorted(path for path in log_dir.glob("run_*.log") if path.is_file())
    except OSError:
        return "0", "run log directory unavailable"

    if not run_logs:
        return "0", "no run logs yet"

    latest: Path | None = None
    latest_mtime: float | None = None
    for run_log in run_logs:
        try:
            mtime = run_log.stat().st_mtime
        except OSError:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest = run_log
            latest_mtime = mtime
    if latest is None or latest_mtime is None:
        return str(len(run_logs)), "latest run log unavailable"
    latest_label = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M")
    return str(len(run_logs)), f"latest {latest_label}"


def _default_install_status(env: Any) -> dict[str, Any]:
    try:
        from agilab.orchestrate_page_support import app_install_status

        return app_install_status(env)
    except Exception:
        active_app = getattr(env, "active_app", None)
        manager_venv = Path(active_app) / ".venv" if active_app else None
        worker_venv = Path(getattr(env, "wenv_abs", "")) / ".venv" if getattr(env, "wenv_abs", None) else None
        manager_exists = bool(manager_venv and manager_venv.exists())
        worker_exists = bool(worker_venv and worker_venv.exists())
        return {
            "workerless": False,
            "manager_ready": False,
            "worker_ready": False,
            "manager_exists": manager_exists,
            "worker_exists": worker_exists,
            "manager_problem": "manager environment status unavailable",
            "worker_problem": "worker environment status unavailable",
            "manager_venv": manager_venv,
            "worker_venv": worker_venv,
        }


def _environment_mapping(env: Any) -> Mapping[str, Any]:
    envars = getattr(env, "envars", None)
    if isinstance(envars, Mapping):
        return envars
    return {}


def _mapping_value(envars: Mapping[str, Any], name: str) -> str:
    raw = envars.get(name)
    if raw in (None, ""):
        raw = os.environ.get(name, "")
    return str(raw or "").strip()


def _looks_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    cleaned = str(value).strip()
    if not cleaned:
        return True
    upper_value = cleaned.upper()
    if cleaned in {"EMPTY", "None", "none", "null", "NULL"}:
        return True
    if "***" in cleaned or "..." in cleaned:
        return True
    if "YOUR-API-KEY" in upper_value or "YOUR_API_KEY" in upper_value:
        return True
    if cleaned in {"your-key", "sk-your-key", "sk-XXXX"}:
        return True
    return len(cleaned) < 12


def _api_key_card(env: Any) -> tuple[EnvironmentHealthCard, tuple[str, str]]:
    envars = _environment_mapping(env)
    providers: list[str] = []
    if not _looks_placeholder_secret(_mapping_value(envars, "OPENAI_API_KEY")):
        providers.append("OpenAI")
    if not _looks_placeholder_secret(_mapping_value(envars, "AZURE_OPENAI_API_KEY")):
        providers.append("Azure OpenAI")
    if not _looks_placeholder_secret(_mapping_value(envars, "MISTRAL_API_KEY")):
        providers.append("Mistral")
    compatible_key = _mapping_value(envars, "AGILAB_LLM_API_KEY")
    if not _looks_placeholder_secret(compatible_key):
        providers.append("OpenAI-compatible")

    if providers:
        caption = ", ".join(providers)
        return EnvironmentHealthCard("API keys", "Configured", caption, "ready"), ("API keys", caption)

    local_markers = (
        "GPT_OSS_ENDPOINT",
        "GPT_OSS_BACKEND",
        "UOAIC_MODE",
        "UOAIC_OLLAMA_ENDPOINT",
    )
    if any(_mapping_value(envars, name) for name in local_markers):
        return (
            EnvironmentHealthCard("API keys", "Local", "local LLM backend", "ready"),
            ("API keys", "local LLM backend"),
        )

    return (
        EnvironmentHealthCard("API keys", "Optional", "no online provider key found", "incomplete"),
        ("API keys", "no online provider key found"),
    )


def _app_settings_file(env: Any) -> Any:
    settings_file = getattr(env, "app_settings_file", None)
    if settings_file:
        return settings_file
    resolver = getattr(env, "resolve_user_app_settings_file", None)
    if callable(resolver):
        try:
            return resolver(ensure_exists=False)
        except TypeError:
            try:
                return resolver()
            except Exception:
                return None
        except Exception:
            return None
    return None


def _settings_card(env: Any) -> tuple[EnvironmentHealthCard, tuple[str, str]]:
    settings_file = _app_settings_file(env)
    status, display = path_status(settings_file, file=True)
    if status == "ready":
        return EnvironmentHealthCard("Settings", "Workspace", compact_path_caption(display), "ready"), (
            "Settings",
            display,
        )

    source_file = getattr(env, "app_settings_source_file", None)
    source_status, source_display = path_status(source_file, file=True)
    if source_status == "ready":
        return EnvironmentHealthCard("Settings", "Seed only", compact_path_caption(source_display), "incomplete"), (
            "Settings seed",
            source_display,
        )

    return EnvironmentHealthCard("Settings", "Missing", compact_path_caption(display), "incomplete"), (
        "Settings",
        display,
    )


def _is_local_worker_host(host: Any) -> bool:
    text = str(host or "").strip().lower()
    if not text:
        return False
    if text.startswith("tcp://"):
        text = text.split("://", 1)[1]
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    elif text.count(":") == 1:
        text = text.rsplit(":", 1)[0]
    return text in {"localhost", "127.0.0.1", "::1"}


def _cluster_has_nonlocal_workers(cluster_params: Mapping[str, Any]) -> bool:
    workers = cluster_params.get("workers", {})
    if isinstance(workers, Mapping):
        return any(not _is_local_worker_host(host) for host in workers)
    text = str(workers or "").strip()
    if text in {"", "{}", "[]", "None", "none"}:
        return False
    return not all(token in text.lower() for token in ("127.0.0.1",))


def _resolve_share_path(env: Any, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    home_abs = getattr(env, "home_abs", None)
    if home_abs:
        return Path(home_abs).expanduser() / candidate
    return candidate


def _cluster_share_card(env: Any, app_settings: Mapping[str, Any] | None) -> tuple[EnvironmentHealthCard, tuple[str, str]]:
    cluster_params = {}
    if app_settings:
        raw_cluster_params = app_settings.get("cluster", {})
        if isinstance(raw_cluster_params, Mapping):
            cluster_params = dict(raw_cluster_params)

    envars = _environment_mapping(env)
    raw_share = str(cluster_params.get("workers_data_path") or _mapping_value(envars, "AGI_CLUSTER_SHARE") or "").strip()
    cluster_enabled = bool(cluster_params.get("cluster_enabled", False))
    has_remote_workers = _cluster_has_nonlocal_workers(cluster_params) if cluster_enabled else False

    if raw_share and raw_share not in {"local", "localshare", "None", "none"}:
        share_path = _resolve_share_path(env, raw_share)
        status, display = path_status(share_path)
        if status == "ready":
            return EnvironmentHealthCard("Cluster share", "Configured", compact_path_caption(display), "ready"), (
                "Cluster share",
                display,
            )
        return EnvironmentHealthCard("Cluster share", "Check path", compact_path_caption(display), "incomplete"), (
            "Cluster share",
            display,
        )

    if not cluster_enabled:
        return EnvironmentHealthCard("Cluster share", "Local", "cluster off", "ready"), (
            "Cluster share",
            "cluster off",
        )

    if not has_remote_workers:
        return EnvironmentHealthCard("Cluster share", "Local Dask", "remote share not required", "ready"), (
            "Cluster share",
            "remote share not required",
        )

    return EnvironmentHealthCard("Cluster share", "Missing", "remote workers need workers_data_path", "incomplete"), (
        "Cluster share",
        "remote workers need workers_data_path",
    )


def _runtime_env_card(install_status: Mapping[str, Any], role: str) -> tuple[EnvironmentHealthCard, tuple[str, str]]:
    ready_key = f"{role}_ready"
    exists_key = f"{role}_exists"
    problem_key = f"{role}_problem"
    venv_key = f"{role}_venv"
    label = "Manager env" if role == "manager" else "Worker env"

    if role == "worker" and install_status.get("workerless"):
        return EnvironmentHealthCard(label, "not used", "workerless local app", "ready"), (
            label,
            "workerless local app",
        )

    status, display = path_status(install_status.get(venv_key), venv=True)
    detail = display
    state = "ready"
    if install_status.get(ready_key):
        status = "ready"
    else:
        status = "stale" if install_status.get(exists_key) else "missing"
        state = "incomplete"
        if install_status.get(exists_key) and install_status.get(problem_key):
            display = str(install_status.get(problem_key))
            detail = display
    return EnvironmentHealthCard(label, status, compact_path_caption(display), state), (label, detail)


def build_environment_health(
    env: Any,
    *,
    app_settings: Mapping[str, Any] | None = None,
    install_status: Mapping[str, Any] | None = None,
) -> EnvironmentHealth:
    if install_status is None:
        install_status = _default_install_status(env)

    active_app = Path(getattr(env, "active_app", "")) if getattr(env, "active_app", None) else None
    project_status, project_display = path_status(active_app)
    project_card = EnvironmentHealthCard(
        "Project path",
        project_status,
        compact_path_caption(project_display, fallback="active project"),
        header_value_state(project_status, project_display),
    )
    manager_card, manager_detail = _runtime_env_card(install_status, "manager")
    worker_card, worker_detail = _runtime_env_card(install_status, "worker")
    settings_card, settings_detail = _settings_card(env)
    share_size, share_caption = data_share_content_summary(getattr(env, "app_data_rel", None))
    share_card = EnvironmentHealthCard(
        "Data share",
        share_size,
        compact_data_share_caption(share_caption),
        header_value_state(share_size, share_caption),
    )
    cluster_card, cluster_detail = _cluster_share_card(env, app_settings)
    api_card, api_detail = _api_key_card(env)
    run_count, run_caption = run_history_summary(env)
    run_card = EnvironmentHealthCard("Runs", run_count, run_caption, header_value_state(run_count, run_caption))

    details = (
        ("Active project", project_display),
        manager_detail,
        worker_detail,
        settings_detail,
        ("Data share", share_caption),
        cluster_detail,
        api_detail,
    )
    return EnvironmentHealth(
        cards=(
            project_card,
            manager_card,
            worker_card,
            settings_card,
            share_card,
            cluster_card,
            api_card,
            run_card,
        ),
        details=details,
    )


def render_environment_health_panel(
    streamlit: Any,
    env: Any,
    *,
    app_settings: Mapping[str, Any] | None = None,
    install_status: Mapping[str, Any] | None = None,
) -> EnvironmentHealth:
    health = build_environment_health(env, app_settings=app_settings, install_status=install_status)
    expander_fn = getattr(streamlit, "expander", None)
    if callable(expander_fn):
        context = expander_fn("Environment Health", expanded=False)
        render_fallback_title = False
    else:
        context = streamlit.container(border=True)
        render_fallback_title = True
    with context:
        if render_fallback_title:
            streamlit.markdown("### Environment Health")
        for start in range(0, len(health.cards), 4):
            row_cards = health.cards[start : start + 4]
            columns = streamlit.columns(len(row_cards))
            for column, card in zip(columns, row_cards):
                with column:
                    render_health_card(streamlit, card)
    render_environment_details(streamlit, health.details)
    return health
