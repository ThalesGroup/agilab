"""Pure app-settings path helpers for AGILAB."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from agi_env.env_config_support import clean_envar_value

APP_SETTINGS_META_KEY = "__meta__"
APP_SETTINGS_SCHEMA = "agilab.app_settings.v1"
APP_SETTINGS_SCHEMA_VERSION = 1
PATH_VALUE_EXCEPTIONS = (TypeError, ValueError)
PATH_PROBE_EXCEPTIONS = (OSError,)
EXPORT_ROOT_EXCEPTIONS = (OSError, TypeError, ValueError)


def sanitize_app_settings_for_toml(obj: Any) -> Any:
    """Recursively convert app-settings values into TOML-safe structures."""

    if isinstance(obj, dict):
        sanitized = {}
        for key, value in obj.items():
            if value is None:
                continue
            sanitized_value = sanitize_app_settings_for_toml(value)
            sanitized[key] = sanitized_value
        return sanitized
    if isinstance(obj, list):
        sanitized_items = []
        for item in obj:
            if item is None:
                continue
            sanitized_items.append(sanitize_app_settings_for_toml(item))
        return sanitized_items
    if isinstance(obj, tuple):
        return sanitize_app_settings_for_toml(list(obj))
    if isinstance(obj, Path):
        return str(obj)
    return obj


def ensure_app_settings_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Stamp app settings with the current persisted artifact contract."""

    meta = data.get(APP_SETTINGS_META_KEY)
    if not isinstance(meta, dict):
        meta = {}
        data[APP_SETTINGS_META_KEY] = meta
    meta.setdefault("schema", APP_SETTINGS_SCHEMA)
    meta.setdefault("version", APP_SETTINGS_SCHEMA_VERSION)
    return data


def app_settings_contract_error(data: dict[str, Any]) -> str:
    """Return a refusal reason when app-settings metadata is unsupported."""

    meta = data.get(APP_SETTINGS_META_KEY, {})
    if meta in ({}, None):
        return ""
    if not isinstance(meta, dict):
        return "app_settings.toml __meta__ must be a TOML table."
    raw_version = meta.get("version")
    if raw_version in (None, ""):
        return ""
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        return f"Unsupported app_settings.toml schema version {raw_version!r}."
    if version < 1 or version > APP_SETTINGS_SCHEMA_VERSION:
        return (
            f"Unsupported app_settings.toml schema version {version}; "
            "upgrade AGILAB before editing this app settings file."
        )
    return ""


def normalize_app_settings_run_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return app settings with the run-stage payload using the current key names."""

    run_payload = data.get("args")
    if not isinstance(run_payload, dict) or "args" not in run_payload:
        return data

    normalized = dict(data)
    normalized_run_payload = dict(run_payload)
    legacy_stages = normalized_run_payload.pop("args")
    if "stages" in normalized_run_payload:
        raise ValueError(
            "app_settings.toml run payload cannot contain both legacy 'args.args' "
            "and current 'args.stages'; keep only 'stages'."
        )
    normalized_run_payload["stages"] = legacy_stages
    normalized["args"] = normalized_run_payload
    return normalized


def prepare_app_settings_for_write(
    payload: dict[str, Any],
    *,
    sanitize: bool = True,
) -> dict[str, Any]:
    """Validate and stamp app settings before persisting them."""

    data = sanitize_app_settings_for_toml(payload) if sanitize else dict(payload)
    if not isinstance(data, dict):
        raise ValueError("app_settings.toml payload must be a TOML table.")
    data = normalize_app_settings_run_payload(data)
    error = app_settings_contract_error(data)
    if error:
        raise ValueError(error)
    return ensure_app_settings_metadata(data)


def app_settings_aliases(app_name: str | None) -> set[str]:
    """Return common project/worker aliases for ``app_name``."""

    if not app_name:
        return set()
    if app_name.endswith("_project_worker"):
        base_name = app_name[: -len("_project_worker")]
        return {base_name + "_project", base_name + "_project_worker"}
    if app_name.endswith("_project"):
        base_name = app_name[: -len("_project")]
        return {app_name, base_name + "_worker"}
    if app_name.endswith("_worker"):
        base_name = app_name[: -len("_worker")]
        return {app_name, base_name + "_project"}
    return {app_name}


def candidate_app_settings_path(base: object) -> Path | None:
    """Return a safe candidate path for ``app_settings.toml`` or ``None``."""

    try:
        base_path = Path(base)
    except PATH_VALUE_EXCEPTIONS:
        return None

    if base_path.name == "src":
        candidates = [base_path / "app_settings.toml"]
    else:
        candidates = [base_path / "app_settings.toml", base_path / "src" / "app_settings.toml"]

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except PATH_PROBE_EXCEPTIONS:
            continue

    try:
        src_dir = base_path / "src"
        if base_path.is_dir() and src_dir.is_dir():
            return src_dir / "app_settings.toml"
    except PATH_PROBE_EXCEPTIONS:
        pass
    return None


def app_settings_source_roots(
    *,
    target_app: str | None,
    current_app: str | None,
    app_src: Path | None,
    active_app: Path | None,
    apps_path: Path | None,
    builtin_apps_path: Path | None,
    apps_repository_root: Path | None,
    home_abs: Path,
    envars: dict | None,
) -> list[Path]:
    """Collect source roots that may contain ``app_settings.toml`` for an app."""

    aliases = app_settings_aliases(target_app)
    current_aliases = app_settings_aliases(current_app)

    roots: list[Path] = []
    if aliases and current_aliases and aliases & current_aliases:
        if app_src is not None:
            roots.append(app_src)
        if active_app is not None:
            roots.append(active_app)
            roots.append(active_app / "src")

    if apps_path is not None:
        for alias in aliases:
            roots.append(apps_path / alias)
            roots.append(apps_path / alias / "src")

    if builtin_apps_path is not None:
        for alias in aliases:
            roots.append(builtin_apps_path / alias)
            roots.append(builtin_apps_path / alias / "src")

    if apps_repository_root is not None:
        roots.append(apps_repository_root)
        for alias in aliases:
            roots.append(apps_repository_root / alias)
            roots.append(apps_repository_root / alias / "src")
            roots.append(apps_repository_root / "src" / alias)

    if target_app:
        for alias in aliases:
            roots.append(home_abs / "wenv" / alias)
            roots.append(home_abs / "wenv" / alias / "src")

    export_root = clean_envar_value(envars, "AGI_EXPORT_DIR", fallback_to_process=True)
    if export_root:
        try:
            expanded_export = Path(export_root).expanduser()
            if not expanded_export.is_absolute():
                expanded_export = home_abs / expanded_export
            roots.append(expanded_export)
            for alias in aliases:
                roots.append(expanded_export / alias)
                roots.append(expanded_export / alias / "src")
        except EXPORT_ROOT_EXCEPTIONS:
            pass

    normalized: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        norm = str(root)
        if norm in seen:
            continue
        seen.add(norm)
        normalized.append(root)
    return normalized


def find_source_app_settings_file(
    *,
    target_app: str | None,
    current_app: str | None,
    app_src: Path | None,
    active_app: Path | None,
    apps_path: Path | None,
    builtin_apps_path: Path | None,
    apps_repository_root: Path | None,
    home_abs: Path,
    envars: dict | None,
) -> Path | None:
    """Return the versioned/source ``app_settings.toml`` for an app when available."""

    for root in app_settings_source_roots(
        target_app=target_app,
        current_app=current_app,
        app_src=app_src,
        active_app=active_app,
        apps_path=apps_path,
        builtin_apps_path=builtin_apps_path,
        apps_repository_root=apps_repository_root,
        home_abs=home_abs,
        envars=envars,
    ):
        candidate = candidate_app_settings_path(root)
        if candidate is not None:
            return candidate
    return None


def resolve_user_app_settings_file(
    *,
    target_app: str | None,
    resources_path: Path,
    ensure_exists: bool = True,
    find_source_file: Callable[[str | None], Path | None],
    copy_file: Callable[[Path, Path], object] = shutil.copy2,
) -> Path:
    """Return the per-user mutable ``app_settings.toml`` path for an app."""

    if not target_app:
        raise RuntimeError("Cannot resolve app settings without an app name")

    workspace_file = resources_path / "apps" / target_app / "app_settings.toml"
    if not ensure_exists:
        return workspace_file

    workspace_file.parent.mkdir(parents=True, exist_ok=True)
    if workspace_file.exists():
        return workspace_file

    source_file = find_source_file(target_app)
    if source_file is not None and source_file.exists():
        copy_file(source_file, workspace_file)
    else:
        workspace_file.touch()
    return workspace_file
