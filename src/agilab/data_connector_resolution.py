# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Connector-reference resolution for AGILAB app/page settings evidence."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any, Mapping

from agilab.data_connector_cloud import object_storage_target
from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    build_data_connector_facility,
    load_connector_catalog,
)
from agilab.data_connector_search import search_index_target


SCHEMA = "agilab.data_connector_resolution.v1"
DEFAULT_RUN_ID = "data-connector-resolution-proof"
DEFAULT_SETTINGS_RELATIVE_PATH = Path(
    "docs/source/data/data_connector_app_settings_sample.toml"
)
CREATED_AT = "2026-04-25T00:00:23Z"
UPDATED_AT = "2026-04-25T00:00:23Z"


def load_app_settings(path: Path) -> dict[str, Any]:
    payload = tomllib.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("app settings sample must be a TOML table")
    return payload


def _connector_by_id(facility_state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    connectors = facility_state.get("connectors", [])
    if not isinstance(connectors, list):
        return {}
    return {
        str(connector.get("id", "")): connector
        for connector in connectors
        if isinstance(connector, dict) and str(connector.get("id", ""))
    }


def _connector_target(connector: Mapping[str, Any]) -> str:
    kind = str(connector.get("kind", "") or "")
    if kind == "sql":
        return str(connector.get("uri", "") or "")
    if kind == "opensearch":
        return search_index_target(connector)
    if kind == "object_storage":
        return object_storage_target(connector)
    return ""


def _settings_catalog_path(
    settings: Mapping[str, Any],
    repo_root: Path,
    settings_path: Path | None = None,
) -> Path:
    catalog = settings.get("connector_catalog", {})
    raw_path = ""
    if isinstance(catalog, dict):
        raw_path = str(catalog.get("path", "") or "")
    path = Path(raw_path) if raw_path else repo_root / DEFAULT_CONNECTORS_RELATIVE_PATH
    if path.is_absolute():
        return path
    repo_candidate = repo_root / path
    if repo_candidate.exists() or str(path).startswith("docs/"):
        return repo_candidate
    if settings_path is not None:
        settings_candidate = settings_path.parent / path
        if settings_candidate.exists():
            return settings_candidate
    return repo_candidate


def _top_level_refs(settings: Mapping[str, Any]) -> dict[str, str]:
    refs = settings.get("connector_refs", {})
    if not isinstance(refs, dict):
        return {}
    return {
        str(name): str(connector_id)
        for name, connector_id in refs.items()
        if str(name) and str(connector_id)
    }


def _page_refs(settings: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    pages = settings.get("page_connector_refs", {})
    if not isinstance(pages, dict):
        return []
    refs: list[tuple[str, str, str]] = []
    for page, page_refs in pages.items():
        if not isinstance(page_refs, dict):
            continue
        for name, connector_id in page_refs.items():
            refs.append((str(page), str(name), str(connector_id)))
    return refs


def _legacy_paths(settings: Mapping[str, Any]) -> dict[str, str]:
    paths = settings.get("legacy_paths", {})
    if not isinstance(paths, dict):
        return {}
    return {
        str(name): str(path)
        for name, path in paths.items()
        if str(name) and str(path)
    }


def _resolution_row(
    *,
    source: str,
    ref_path: str,
    ref_name: str,
    connector_id: str,
    connector: Mapping[str, Any] | None,
    page: str = "",
) -> dict[str, Any]:
    if connector is None:
        return {
            "ref_path": ref_path,
            "ref_name": ref_name,
            "connector_id": connector_id,
            "status": "missing",
            "page": page,
            "source": source,
        }
    return {
        "ref_path": ref_path,
        "ref_name": ref_name,
        "connector_id": connector_id,
        "status": "resolved",
        "page": page,
        "kind": connector.get("kind", ""),
        "label": connector.get("label", ""),
        "resolved_target": _connector_target(connector),
        "auth_ref": connector.get("auth_ref", ""),
        "source": source,
    }


def build_data_connector_resolution(
    *,
    settings: Mapping[str, Any],
    facility_state: Mapping[str, Any],
    settings_path: Path | str,
    catalog_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    connectors = _connector_by_id(facility_state)
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    catalog_run_status = str(facility_state.get("run_status", "") or "")

    if catalog_run_status != "validated":
        issues.append(
            {
                "level": "error",
                "location": "connector_catalog",
                "message": f"catalog run status is not validated: {catalog_run_status}",
            }
        )

    for name, connector_id in _top_level_refs(settings).items():
        row = _resolution_row(
            source="connector_refs",
            ref_path=f"connector_refs.{name}",
            ref_name=name,
            connector_id=connector_id,
            connector=connectors.get(connector_id),
        )
        rows.append(row)
        if row["status"] != "resolved":
            issues.append(
                {
                    "level": "error",
                    "location": row["ref_path"],
                    "message": f"unknown connector id: {connector_id}",
                }
            )

    for page, name, connector_id in _page_refs(settings):
        row = _resolution_row(
            source="page_connector_refs",
            ref_path=f"page_connector_refs.{page}.{name}",
            ref_name=name,
            connector_id=connector_id,
            connector=connectors.get(connector_id),
            page=page,
        )
        rows.append(row)
        if row["status"] != "resolved":
            issues.append(
                {
                    "level": "error",
                    "location": row["ref_path"],
                    "message": f"unknown connector id: {connector_id}",
                }
            )

    legacy_rows = [
        {
            "ref_path": f"legacy_paths.{name}",
            "ref_name": name,
            "status": "legacy_path_fallback",
            "path": path,
            "expanded_path": str(Path(path).expanduser()),
            "source": "legacy_paths",
        }
        for name, path in _legacy_paths(settings).items()
    ]
    resolved_rows = [row for row in rows if row.get("status") == "resolved"]
    page_rows = [row for row in rows if row.get("page")]
    top_level_rows = [row for row in rows if not row.get("page")]
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "resolved" if not issues else "invalid",
        "execution_mode": "contract_resolution_only",
        "source": {
            "settings_path": str(settings_path),
            "catalog_path": str(catalog_path),
            "facility_schema": facility_state.get("schema", ""),
            "facility_run_status": catalog_run_status,
        },
        "summary": {
            "connector_ref_count": len(rows),
            "top_level_ref_count": len(top_level_rows),
            "resolved_connector_ref_count": len(resolved_rows),
            "page_connector_ref_count": len(page_rows),
            "legacy_path_count": len(legacy_rows),
            "missing_ref_count": len(rows) - len(resolved_rows),
            "network_probe_count": 0,
            "catalog_run_status": catalog_run_status,
            "legacy_fallback_preserved": bool(legacy_rows),
            "resolved_kinds": sorted({str(row.get("kind", "")) for row in resolved_rows}),
        },
        "resolutions": rows,
        "legacy_fallbacks": legacy_rows,
        "issues": issues,
        "provenance": {
            "executes_network_probe": False,
            "supports_app_settings_connector_refs": True,
            "supports_page_connector_refs": True,
            "legacy_paths_preserved": True,
        },
    }


def write_data_connector_resolution(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_resolution(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_resolution(
    *,
    repo_root: Path,
    output_path: Path,
    settings_path: Path | None = None,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    settings_path = settings_path or (repo_root / DEFAULT_SETTINGS_RELATIVE_PATH)
    if not settings_path.is_absolute():
        settings_path = repo_root / settings_path
    settings = load_app_settings(settings_path)
    catalog_path = catalog_path or _settings_catalog_path(settings, repo_root, settings_path)
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    catalog = load_connector_catalog(catalog_path)
    facility_state = build_data_connector_facility(catalog, source_path=catalog_path)
    state = build_data_connector_resolution(
        settings=settings,
        facility_state=facility_state,
        settings_path=settings_path,
        catalog_path=catalog_path,
    )
    path = write_data_connector_resolution(output_path, state)
    reloaded = load_data_connector_resolution(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "resolved",
        "path": str(path),
        "settings_path": str(settings_path),
        "catalog_path": str(catalog_path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
