from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any, Callable

import tomli_w
import tomllib


GLOBAL_DIAGNOSTICS_ENV_KEY = "AGILAB_RUNTIME_DIAGNOSTICS_VERBOSE"
DIAGNOSTICS_LEVELS: tuple[tuple[str, int, str], ...] = (
    ("Quiet", 0, "Show only essential progress and failures."),
    ("Standard", 1, "Show normal progress, warnings, and concise failures."),
    ("Detailed", 2, "Keep detailed runtime logs and filtered tracebacks."),
    ("Debug", 3, "Keep full diagnostic output for troubleshooting."),
)
DIAGNOSTICS_OPTIONS: tuple[str, ...] = tuple(label for label, _verbose, _description in DIAGNOSTICS_LEVELS)
DIAGNOSTICS_VERBOSE_BY_LABEL: dict[str, int] = {label: verbose for label, verbose, _description in DIAGNOSTICS_LEVELS}
DIAGNOSTICS_LABEL_BY_VERBOSE: dict[int, str] = {verbose: label for label, verbose, _description in DIAGNOSTICS_LEVELS}
DEFAULT_DIAGNOSTICS_VERBOSE = 1
RUNTIME_DIAGNOSTICS_HELP = (
    "Controls AgiEnv verbosity for generated install, distribute, run, service, "
    "and pipeline runtime snippets."
)


def coerce_diagnostics_verbose(value: Any, default: int = DEFAULT_DIAGNOSTICS_VERBOSE) -> int:
    if isinstance(value, bool):
        return default
    try:
        verbose = int(value)
    except (TypeError, ValueError):
        return default
    return verbose if verbose in DIAGNOSTICS_LABEL_BY_VERBOSE else default


def diagnostics_label(value: Any, default: int = DEFAULT_DIAGNOSTICS_VERBOSE) -> str:
    verbose = coerce_diagnostics_verbose(value, default=default)
    return DIAGNOSTICS_LABEL_BY_VERBOSE[verbose]


def diagnostics_verbose(value: Any, default: int = DEFAULT_DIAGNOSTICS_VERBOSE) -> int:
    if isinstance(value, str) and value in DIAGNOSTICS_VERBOSE_BY_LABEL:
        return DIAGNOSTICS_VERBOSE_BY_LABEL[value]
    return coerce_diagnostics_verbose(value, default=default)


def diagnostics_widget_key(app_name: Any) -> str:
    app_text = str(app_name or "default").strip() or "default"
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in app_text)
    legacy_prefixes = {
        "data_io_2026_project": "mission_decision_project",
        "flight_project": "flight_telemetry_project",
        "meteo_forecast_project": "weather_forecast_project",
    }
    for legacy, current in legacy_prefixes.items():
        if safe == legacy or safe.startswith(f"{legacy}_"):
            safe = f"{current}{safe[len(legacy):]}"
            break
    return f"runtime_diagnostics_level__{safe}"


def global_diagnostics_verbose(
    *,
    session_state: Any = None,
    envars: Mapping[str, Any] | None = None,
    environ: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    default: int = DEFAULT_DIAGNOSTICS_VERBOSE,
) -> int:
    """Resolve the project-agnostic diagnostics level with legacy TOML fallback."""
    for source in (session_state, envars, environ):
        if source is None:
            continue
        value = _state_get(source, GLOBAL_DIAGNOSTICS_ENV_KEY)
        if value is not None:
            return coerce_diagnostics_verbose(value, default=default)

    if settings:
        cluster = settings.get("cluster")
        if isinstance(cluster, Mapping):
            return coerce_diagnostics_verbose(cluster.get("verbose"), default=default)
    return default


def update_settings_diagnostics(
    settings: MutableMapping[str, Any],
    verbose: Any,
) -> int:
    selected_verbose = diagnostics_verbose(verbose)
    cluster = settings.setdefault("cluster", {})
    if not isinstance(cluster, MutableMapping):
        cluster = {}
        settings["cluster"] = cluster
    cluster["verbose"] = selected_verbose
    return selected_verbose


def _state_get(state: Any, key: str, default: Any = None) -> Any:
    try:
        return state.get(key, default)
    except AttributeError:
        return getattr(state, key, default)


def _state_pop(state: Any, key: str) -> None:
    try:
        state.pop(key, None)
    except AttributeError:
        if hasattr(state, key):
            delattr(state, key)


def render_runtime_diagnostics_control(
    streamlit: Any,
    container: Any,
    settings: MutableMapping[str, Any],
    *,
    app_name: Any,
    compact_choice_fn: Callable[..., Any],
    key: str | None = None,
    label: str = "Diagnostics level",
    options: Sequence[str] = DIAGNOSTICS_OPTIONS,
) -> int:
    cluster = settings.setdefault("cluster", {})
    if not isinstance(cluster, Mapping):
        cluster = {}
        settings["cluster"] = cluster
    current_verbose = coerce_diagnostics_verbose(cluster.get("verbose", DEFAULT_DIAGNOSTICS_VERBOSE))
    current_label = diagnostics_label(current_verbose)
    widget_key = key or diagnostics_widget_key(app_name)

    state = getattr(streamlit, "session_state", {})
    if _state_get(state, widget_key) not in options:
        _state_pop(state, widget_key)

    selected_label = compact_choice_fn(
        container,
        label,
        options,
        key=widget_key,
        default=current_label,
        help=RUNTIME_DIAGNOSTICS_HELP,
        inline_limit=len(options),
    )
    selected_verbose = diagnostics_verbose(selected_label)
    update_settings_diagnostics(settings, selected_verbose)
    return selected_verbose


def load_settings_file(settings_path: Path | str | None) -> dict[str, Any]:
    if settings_path in (None, ""):
        return {}
    path = Path(settings_path)
    if not path.exists():
        return {}
    try:
        with path.open("rb") as stream:
            loaded = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def persist_diagnostics_verbose(settings_path: Path | str | None, verbose: Any) -> dict[str, Any]:
    if settings_path in (None, ""):
        return {}
    path = Path(settings_path)
    settings = load_settings_file(path)
    update_settings_diagnostics(settings, verbose)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        tomli_w.dump(settings, stream)
    return settings
