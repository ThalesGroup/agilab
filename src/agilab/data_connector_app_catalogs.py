# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""App-local connector catalog validation for AGILAB evidence reports."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any, Mapping

from agilab.data_connector_facility import (
    SUPPORTED_KINDS,
    build_data_connector_facility,
    load_connector_catalog,
)
from agilab.data_connector_resolution import (
    _settings_catalog_path,
    build_data_connector_resolution,
    load_app_settings,
)


SCHEMA = "agilab.data_connector_app_catalogs.v1"
DEFAULT_RUN_ID = "data-connector-app-catalogs-proof"
CREATED_AT = "2026-04-25T00:00:27Z"
UPDATED_AT = "2026-04-25T00:00:27Z"
DEFAULT_APPS_ROOT = Path("src/agilab/apps/builtin")


def _settings_with_catalog(settings_path: Path) -> dict[str, Any] | None:
    try:
        payload = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    catalog = payload.get("connector_catalog", {})
    if not isinstance(catalog, dict) or not str(catalog.get("path", "") or ""):
        return None
    return payload


def discover_app_connector_settings(repo_root: Path) -> list[Path]:
    apps_root = repo_root / DEFAULT_APPS_ROOT
    settings_paths = []
    for settings_path in sorted(apps_root.glob("*/src/app_settings.toml")):
        if _settings_with_catalog(settings_path) is not None:
            settings_paths.append(settings_path)
    return settings_paths


def _app_name(settings_path: Path) -> str:
    try:
        return settings_path.parents[1].name
    except IndexError:
        return settings_path.parent.name


def _app_row(
    *,
    repo_root: Path,
    settings_path: Path,
    settings: Mapping[str, Any],
    catalog_path: Path,
    facility_state: Mapping[str, Any],
    resolution_state: Mapping[str, Any],
) -> dict[str, Any]:
    facility_summary = facility_state.get("summary", {})
    resolution_summary = resolution_state.get("summary", {})
    connectors = [
        connector
        for connector in facility_state.get("connectors", [])
        if isinstance(connector, dict)
    ]
    return {
        "app": _app_name(settings_path),
        "settings_path": str(settings_path.relative_to(repo_root)),
        "catalog_path": str(catalog_path.relative_to(repo_root)),
        "catalog_scope": "app_local",
        "catalog_run_status": facility_state.get("run_status", ""),
        "resolution_run_status": resolution_state.get("run_status", ""),
        "connector_count": facility_summary.get("connector_count", 0),
        "supported_kinds": facility_summary.get("supported_kinds", []),
        "connector_ref_count": resolution_summary.get("connector_ref_count", 0),
        "page_connector_ref_count": resolution_summary.get("page_connector_ref_count", 0),
        "legacy_path_count": resolution_summary.get("legacy_path_count", 0),
        "missing_ref_count": resolution_summary.get("missing_ref_count", 0),
        "network_probe_count": (
            int(facility_summary.get("network_probe_count", 0) or 0)
            + int(resolution_summary.get("network_probe_count", 0) or 0)
        ),
        "connector_ids": [str(connector.get("id", "")) for connector in connectors],
        "page_ids": sorted(
            {
                str(row.get("page", ""))
                for row in resolution_state.get("resolutions", [])
                if isinstance(row, dict) and row.get("page")
            }
        ),
    }


def build_data_connector_app_catalogs(
    *,
    repo_root: Path,
    settings_paths: list[Path] | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    settings_paths = settings_paths or discover_app_connector_settings(repo_root)
    app_rows: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for raw_settings_path in settings_paths:
        settings_path = raw_settings_path
        if not settings_path.is_absolute():
            settings_path = repo_root / settings_path
        settings = load_app_settings(settings_path)
        catalog_path = _settings_catalog_path(settings, repo_root, settings_path)
        catalog = load_connector_catalog(catalog_path)
        facility_state = build_data_connector_facility(catalog, source_path=catalog_path)
        resolution_state = build_data_connector_resolution(
            settings=settings,
            facility_state=facility_state,
            settings_path=settings_path,
            catalog_path=catalog_path,
        )
        app_rows.append(
            _app_row(
                repo_root=repo_root,
                settings_path=settings_path,
                settings=settings,
                catalog_path=catalog_path,
                facility_state=facility_state,
                resolution_state=resolution_state,
            )
        )
        for state_name, state in (
            ("facility", facility_state),
            ("resolution", resolution_state),
        ):
            if state.get("run_status") not in {"validated", "resolved"}:
                issues.append(
                    {
                        "level": "error",
                        "location": f"{_app_name(settings_path)}.{state_name}",
                        "message": f"{state_name} state is not ready: {state.get('run_status')}",
                    }
                )
    missing_kinds = [
        row["app"]
        for row in app_rows
        if sorted(row.get("supported_kinds", [])) != sorted(SUPPORTED_KINDS)
    ]
    for app in missing_kinds:
        issues.append(
            {
                "level": "error",
                "location": app,
                "message": "app-local catalog does not cover all supported connector kinds",
            }
        )
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "validated" if not issues else "invalid",
        "execution_mode": "app_catalog_validation_only",
        "source": {
            "repo_root": str(repo_root),
            "apps_root": str((repo_root / DEFAULT_APPS_ROOT).relative_to(repo_root)),
        },
        "summary": {
            "app_catalog_count": len(app_rows),
            "app_count": len({row["app"] for row in app_rows}),
            "connector_count": sum(int(row["connector_count"]) for row in app_rows),
            "page_connector_ref_count": sum(
                int(row["page_connector_ref_count"]) for row in app_rows
            ),
            "legacy_path_count": sum(int(row["legacy_path_count"]) for row in app_rows),
            "missing_ref_count": sum(int(row["missing_ref_count"]) for row in app_rows),
            "network_probe_count": sum(int(row["network_probe_count"]) for row in app_rows),
            "apps": [row["app"] for row in app_rows],
            "required_kinds": list(SUPPORTED_KINDS),
        },
        "apps": app_rows,
        "issues": issues,
        "provenance": {
            "executes_network_probe": False,
            "uses_app_local_catalogs": True,
            "catalog_paths_resolved_from_app_settings": True,
        },
    }


def write_data_connector_app_catalogs(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_app_catalogs(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_app_catalogs(
    *,
    repo_root: Path,
    output_path: Path,
    settings_paths: list[Path] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    state = build_data_connector_app_catalogs(
        repo_root=repo_root,
        settings_paths=settings_paths,
    )
    path = write_data_connector_app_catalogs(output_path, state)
    reloaded = load_data_connector_app_catalogs(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "validated",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
