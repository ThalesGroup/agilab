"""Structural validation for app_settings.toml core sections.

The schema is warning-first: it only errors on shapes core code already
refuses or silently discards (hiding real mistakes), and it never rejects
app-owned content ([args] payloads, per-page tables, [view_*] state,
connector references, extra keys anywhere).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from agi_env.project.app_settings_support import app_settings_contract_error

# Core sections whose presence requires a TOML table. Content stays free-form
# beyond the specific key rules below.
CORE_TABLE_SECTIONS = ("__meta__", "args", "cluster", "pages", "app_surface")
# cluster_enabled is read through a tolerant parser that accepts loose
# truthy/falsy strings without raising; pool/cython/rapids are read with a
# bare int(...) by core orchestration code, which raises on a non-numeric
# string (e.g. "true") instead of coercing it.
CLUSTER_LOOSE_BOOL_FLAGS = ("cluster_enabled",)
CLUSTER_STRICT_INT_FLAGS = ("pool", "cython", "rapids")
DIAGNOSTICS_VERBOSE_RANGE = range(0, 4)


def _crashes_bare_int_coercion(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        int(value)
    except (TypeError, ValueError):
        return True
    return False


@dataclass(frozen=True, slots=True)
class AppSettingsValidation:
    """Validation outcome split into refusals and likely-mistake warnings."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_table(value: Any) -> bool:
    return isinstance(value, Mapping)


def _table_or_none(data: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = data.get(key)
    return value if _is_table(value) else None


def _validate_meta(data: Mapping[str, Any], errors: list[str]) -> None:
    contract_error = app_settings_contract_error(dict(data))
    if contract_error:
        errors.append(contract_error)


def _validate_args(data: Mapping[str, Any], errors: list[str], warnings: list[str]) -> None:
    args = _table_or_none(data, "args")
    if args is None:
        return
    if "args" in args and "stages" in args:
        errors.append(
            "args: cannot contain both legacy 'args.args' and current "
            "'args.stages'; keep only 'stages'."
        )
    elif "args" in args:
        warnings.append(
            "args.args: legacy run-stage key; it is migrated to 'args.stages' "
            "on the next settings write."
        )


def _validate_cluster(data: Mapping[str, Any], errors: list[str], warnings: list[str]) -> None:
    cluster = _table_or_none(data, "cluster")
    if cluster is None:
        return

    verbose = cluster.get("verbose")
    if isinstance(verbose, bool):
        warnings.append(
            "cluster.verbose: boolean values are ignored and coerced to the "
            "default 1; use an integer 0-3."
        )
    elif isinstance(verbose, int) and verbose not in DIAGNOSTICS_VERBOSE_RANGE:
        warnings.append(
            f"cluster.verbose: {verbose} is outside 0-3 and is coerced to 1."
        )

    for flag in CLUSTER_LOOSE_BOOL_FLAGS:
        value = cluster.get(flag)
        if value is not None and not isinstance(value, bool):
            warnings.append(
                f"cluster.{flag}: expected a boolean; other values are "
                "interpreted loosely and may not mean what you intend."
            )

    for flag in CLUSTER_STRICT_INT_FLAGS:
        value = cluster.get(flag)
        if value is None or isinstance(value, bool):
            continue
        if _crashes_bare_int_coercion(value):
            errors.append(
                f"cluster.{flag}: {value!r} cannot be coerced to an integer; "
                "AGILAB reads this flag with int(...) and will raise at "
                "runtime. Use a boolean or an integer."
            )
        elif not isinstance(value, int):
            warnings.append(
                f"cluster.{flag}: expected a boolean or integer; other "
                "numeric-looking values are coerced with int(...)."
            )

    scheduler = cluster.get("scheduler")
    if scheduler is not None and not isinstance(scheduler, str):
        warnings.append("cluster.scheduler: expected a string address.")

    if "workers" in cluster:
        workers = cluster["workers"]
        if not _is_table(workers):
            errors.append("cluster.workers: must be a TOML table of host -> count.")
        else:
            for host, count in workers.items():
                if isinstance(count, float) and not isinstance(count, bool):
                    warnings.append(
                        f"cluster.workers.{host}: fractional value {count} is "
                        f"truncated to {int(count)} by AGILAB; use an integer."
                    )
                elif (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or count < 0
                ):
                    errors.append(
                        f"cluster.workers.{host}: worker count must be a "
                        "non-negative integer."
                    )

    if "service_health" in cluster and not _is_table(cluster["service_health"]):
        errors.append("cluster.service_health: must be a TOML table.")


def _validate_pages(data: Mapping[str, Any], errors: list[str], warnings: list[str]) -> None:
    pages = _table_or_none(data, "pages")
    if pages is None:
        return

    default_view = pages.get("default_view")
    if default_view is not None and not isinstance(default_view, str):
        errors.append("pages.default_view: must be a string page-module name.")

    if "view_module" in pages:
        view_module = pages["view_module"]
        if not isinstance(view_module, list):
            errors.append(
                "pages.view_module: must be an array of page-module name "
                "strings; other shapes are silently ignored by AGILAB."
            )
        else:
            for index, item in enumerate(view_module):
                if not isinstance(item, str):
                    errors.append(
                        f"pages.view_module[{index}]: entries must be strings."
                    )
                elif not item.strip():
                    warnings.append(
                        f"pages.view_module[{index}]: blank entries are skipped."
                    )


def _surface_declares_target(entry: Mapping[str, Any]) -> bool:
    return bool(
        str(entry.get("entrypoint") or "").strip()
        or str(entry.get("url") or "").strip()
    )


def _validate_app_surface(
    data: Mapping[str, Any], errors: list[str], warnings: list[str]
) -> None:
    app_surface = _table_or_none(data, "app_surface")
    if app_surface is None:
        return

    root_default = app_surface.get("default")
    if isinstance(root_default, bool):
        warnings.append(
            "app_surface.default: at the section root this key selects a "
            "surface by name; use a string, not a boolean."
        )

    backends = app_surface.get("backends")
    backend_declares_target = False
    if backends is not None and not _is_table(backends):
        errors.append("app_surface.backends: must be a TOML table of backend tables.")
    elif _is_table(backends):
        for name, entry in backends.items():
            if not _is_table(entry):
                errors.append(f"app_surface.backends.{name}: must be a TOML table.")
                continue
            if _surface_declares_target(entry):
                backend_declares_target = True
            else:
                warnings.append(
                    f"app_surface.backends.{name}: declares neither "
                    "'entrypoint' nor 'url'; this backend is skipped."
                )
            entry_default = entry.get("default")
            if entry_default is not None and not isinstance(entry_default, bool):
                warnings.append(
                    f"app_surface.backends.{name}.default: only the boolean "
                    "true marks the default backend; other values are ignored."
                )

    if not _surface_declares_target(app_surface) and not backend_declares_target:
        warnings.append(
            "app_surface: declares neither 'entrypoint' nor 'url' (directly or "
            "in a backend); the surface is dropped."
        )


def _validate_passthrough_paths(
    data: Mapping[str, Any], warnings: list[str]
) -> None:
    connector_catalog = _table_or_none(data, "connector_catalog")
    if connector_catalog is not None:
        path = connector_catalog.get("path")
        if path is not None and not isinstance(path, str):
            warnings.append("connector_catalog.path: expected a string path.")

    legacy_paths = _table_or_none(data, "legacy_paths")
    if legacy_paths is not None:
        for key in ("data_in", "data_out"):
            value = legacy_paths.get(key)
            if value is not None and not isinstance(value, str):
                warnings.append(f"legacy_paths.{key}: expected a string path.")


def validate_app_settings(data: Any) -> AppSettingsValidation:
    """Validate the structure of one parsed app_settings payload."""

    if not _is_table(data):
        return AppSettingsValidation(
            errors=("app_settings.toml payload must be a TOML table.",)
        )

    errors: list[str] = []
    warnings: list[str] = []

    for section in CORE_TABLE_SECTIONS:
        if section in data and not _is_table(data[section]):
            errors.append(f"{section}: must be a TOML table.")

    if _is_table(data.get("__meta__")):
        _validate_meta(data, errors)
    _validate_args(data, errors, warnings)
    _validate_cluster(data, errors, warnings)
    _validate_pages(data, errors, warnings)
    _validate_app_surface(data, errors, warnings)
    _validate_passthrough_paths(data, warnings)

    return AppSettingsValidation(errors=tuple(errors), warnings=tuple(warnings))


def validate_app_settings_file(settings_path: str | Path) -> AppSettingsValidation:
    """Validate one app_settings.toml file; a missing file is a valid app marker."""

    path = Path(settings_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AppSettingsValidation()
    except OSError as exc:
        return AppSettingsValidation(
            warnings=(f"app_settings.toml is unreadable: {exc}",)
        )
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return AppSettingsValidation(
            errors=(f"app_settings.toml is not valid TOML: {exc}",)
        )
    return validate_app_settings(payload)


def log_app_settings_validation(
    settings_path: str | Path, *, logger: Any
) -> AppSettingsValidation:
    """Validate one settings file and report findings without failing the caller."""

    try:
        validation = validate_app_settings_file(settings_path)
        if logger is not None:
            for message in validation.errors:
                logger.warning(f"{settings_path}: {message}")
            for message in validation.warnings:
                logger.info(f"{settings_path}: {message}")
    except Exception as exc:  # defensive: never let validation break env init
        if logger is not None:
            try:
                logger.debug(f"app_settings validation skipped for {settings_path}: {exc}")
            except Exception:
                pass
        return AppSettingsValidation()
    return validation
