"""App-settings contract, transaction, and path helpers for AGILAB."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from io import BufferedWriter
import os
import shutil
from pathlib import Path
import tempfile
import threading
import tomllib
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from agi_env.runtime.env_config_support import clean_envar_value
from agi_env.runtime.atomic_write_support import (
    FILE_LOCK_TIMEOUT_SECONDS,
    acquire_bounded_file_lock,
    atomic_write_bytes,
    release_file_lock,
    run_with_windows_file_sharing_retry,
)

APP_SETTINGS_META_KEY = "__meta__"
APP_SETTINGS_SCHEMA = "agilab.app_settings.v1"
APP_SETTINGS_SCHEMA_VERSION = 1
PATH_VALUE_EXCEPTIONS = (TypeError, ValueError)
PATH_PROBE_EXCEPTIONS = (OSError,)
EXPORT_ROOT_EXCEPTIONS = (OSError, TypeError, ValueError)

_APP_SETTINGS_THREAD_LOCKS: dict[Path, threading.Lock] = {}
_APP_SETTINGS_THREAD_LOCKS_GUARD = threading.Lock()
_APP_SETTINGS_LOCK_TIMEOUT_SECONDS = FILE_LOCK_TIMEOUT_SECONDS


def _app_settings_thread_lock(settings_path: Path) -> threading.Lock:
    """Return the process-local lock paired with a settings transaction path."""

    try:
        lock_key = settings_path.resolve(strict=False)
    except OSError:
        lock_key = settings_path.absolute()
    with _APP_SETTINGS_THREAD_LOCKS_GUARD:
        return _APP_SETTINGS_THREAD_LOCKS.setdefault(lock_key, threading.Lock())


@contextmanager
def app_settings_file_lock(settings_path: str | Path) -> Iterator[None]:
    """Serialize thread and process read/merge/write settings transactions."""

    settings_path = Path(settings_path)
    lock_path = settings_path.with_name(settings_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _app_settings_thread_lock(settings_path)
    thread_locked = thread_lock.acquire(timeout=_APP_SETTINGS_LOCK_TIMEOUT_SECONDS)
    if not thread_locked:
        raise TimeoutError(
            f"Timed out waiting for AGILAB app-settings lock {lock_path}. "
            "Another session may still be updating these settings; retry after it finishes."
        )
    try:
        handle = lock_path.open("a+b")
        file_locked = False
        try:
            acquire_bounded_file_lock(
                handle,
                lock_path,
                timeout_seconds=_APP_SETTINGS_LOCK_TIMEOUT_SECONDS,
            )
            file_locked = True
            yield
        finally:
            try:
                if file_locked:
                    release_file_lock(handle)
            finally:
                handle.close()
    finally:
        thread_lock.release()


def _fsync_directory(path: Path) -> None:
    """Persist a settings-file directory entry after atomic publication."""

    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        if os.name == "nt":  # pragma: no cover - directory fsync is unsupported
            return
        raise
    try:
        try:
            os.fsync(directory_fd)
        except OSError:
            if os.name != "nt":
                raise
    finally:
        os.close(directory_fd)


def _default_app_settings_dumper(
    payload: dict[str, Any], stream: BufferedWriter
) -> None:
    try:
        import tomli_w  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        if getattr(exc, "name", None) != "tomli_w":
            raise
        try:
            from tomlkit import dumps as tomlkit_dumps
        except ModuleNotFoundError as fallback_exc:
            if getattr(fallback_exc, "name", None) != "tomlkit":
                raise
            raise RuntimeError(
                "Writing settings requires either 'tomli-w' or 'tomlkit'."
            ) from fallback_exc
        stream.write(tomlkit_dumps(payload).encode("utf-8"))
        return
    tomli_w.dump(payload, stream)


def read_app_settings_text(settings_path: str | Path) -> str:
    """Read mutable app settings through Windows' bounded sharing retry."""

    path = Path(settings_path)
    return run_with_windows_file_sharing_retry(
        lambda: path.read_text(encoding="utf-8")
    )


def read_app_settings(settings_path: str | Path) -> dict[str, Any]:
    """Parse mutable app settings without hiding TOML or permanent I/O errors."""

    return tomllib.loads(read_app_settings_text(settings_path))


def update_app_settings(
    settings_path: str | Path,
    update: Callable[[dict[str, Any]], bool],
    *,
    create_missing: bool = True,
    dump_fn: Callable[[dict[str, Any], BufferedWriter], None] | None = None,
    prepare_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Apply one locked read/update/write transaction to ``app_settings.toml``.

    ``update`` receives the latest payload while the cross-process lock is held.
    It may mutate only the keys it owns and returns whether publication is needed.
    The existing file is retained if mutation, serialization, or atomic publication
    fails.
    """

    settings_path = Path(settings_path)
    writer = dump_fn or _default_app_settings_dumper
    prepare = prepare_fn or prepare_app_settings_for_write
    with app_settings_file_lock(settings_path):
        if settings_path.exists():
            payload = read_app_settings(settings_path)
        elif create_missing:
            payload = {}
        else:
            raise FileNotFoundError(f"Settings file not found: {settings_path}")

        if not update(payload):
            return payload, False

        prepared = prepare(payload)
        atomic_write_bytes(
            settings_path,
            lambda handle: writer(prepared, handle),
        )
        _fsync_directory(settings_path.parent)
        return prepared, True


_MISSING_APP_SETTINGS_VALUE = object()


def _app_settings_path_value(
    payload: Mapping[str, Any], path: Sequence[str]
) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING_APP_SETTINGS_VALUE
        current = current[part]
    return current


def _apply_app_settings_path_value(
    payload: dict[str, Any], path: Sequence[str], value: Any
) -> bool:
    if not path or any(not isinstance(part, str) or not part for part in path):
        raise ValueError("App-settings ownership paths must contain non-empty strings.")

    current: dict[str, Any] = payload
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            if value is _MISSING_APP_SETTINGS_VALUE:
                return False
            child = {}
            current[part] = child
        current = child

    leaf = path[-1]
    if value is _MISSING_APP_SETTINGS_VALUE:
        if leaf not in current:
            return False
        del current[leaf]
        return True

    copied = deepcopy(value)
    if current.get(leaf, _MISSING_APP_SETTINGS_VALUE) == copied:
        return False
    current[leaf] = copied
    return True


def update_app_settings_owned(
    settings_path: str | Path,
    payload: Mapping[str, Any],
    *,
    owned_paths: Iterable[Sequence[str]],
    default_paths: Iterable[Sequence[str]] = (),
    create_missing: bool = True,
    dump_fn: Callable[[dict[str, Any], BufferedWriter], None] | None = None,
    prepare_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Publish only explicitly owned paths from a possibly stale payload.

    Each owned value is selected from ``payload`` before the transaction, then
    applied to the latest on-disk document while its lock is held. A missing owned
    path means deletion; unrelated leaves written by other sessions remain
    untouched. ``default_paths`` are applied only when the latest document does not
    already contain that leaf, so first-render initialization cannot replace a
    concurrent writer's value.
    """

    normalized_paths = tuple(tuple(path) for path in owned_paths)
    normalized_default_paths = tuple(tuple(path) for path in default_paths)
    if not normalized_paths and not normalized_default_paths:
        raise ValueError(
            "At least one app-settings ownership or default path is required."
        )
    if set(normalized_paths) & set(normalized_default_paths):
        raise ValueError("App-settings ownership and default paths must be disjoint.")
    owned_values = tuple(
        (path, _app_settings_path_value(payload, path)) for path in normalized_paths
    )
    default_values = tuple(
        (path, _app_settings_path_value(payload, path))
        for path in normalized_default_paths
    )

    def _update(latest: dict[str, Any]) -> bool:
        changed = False
        for path, value in owned_values:
            changed = _apply_app_settings_path_value(latest, path, value) or changed
        for path, value in default_values:
            if value is _MISSING_APP_SETTINGS_VALUE:
                continue
            if _app_settings_path_value(latest, path) is _MISSING_APP_SETTINGS_VALUE:
                changed = (
                    _apply_app_settings_path_value(latest, path, value) or changed
                )
        return changed

    return update_app_settings(
        settings_path,
        _update,
        create_missing=create_missing,
        dump_fn=dump_fn,
        prepare_fn=prepare_fn,
    )


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
        base_path = Path(base)  # ty: ignore[invalid-argument-type]
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
    with app_settings_file_lock(workspace_file):
        if workspace_file.exists():
            return workspace_file

        source_file = find_source_file(target_app)
        if source_file is not None and source_file.exists():
            with tempfile.TemporaryDirectory(
                prefix=f".{workspace_file.name}.seed.",
                dir=workspace_file.parent,
            ) as staging_dir:
                staged_source = Path(staging_dir) / source_file.name
                copy_file(source_file, staged_source)

                def _copy_staged(handle: BufferedWriter) -> None:
                    with staged_source.open("rb") as source_handle:
                        shutil.copyfileobj(source_handle, handle)

                atomic_write_bytes(workspace_file, _copy_staged)
        else:
            atomic_write_bytes(workspace_file, lambda _handle: None)
        _fsync_directory(workspace_file.parent)
    return workspace_file
