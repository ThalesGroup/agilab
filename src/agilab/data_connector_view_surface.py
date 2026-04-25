# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Connector-aware Release Decision view-surface contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    load_connector_catalog,
)
from agilab.data_connector_live_ui import build_data_connector_live_ui
from agilab.data_connector_resolution import (
    DEFAULT_SETTINGS_RELATIVE_PATH,
    load_app_settings,
)


SCHEMA = "agilab.data_connector_view_surface.v1"
DEFAULT_RUN_ID = "data-connector-view-surface-proof"
CREATED_AT = "2026-04-25T00:00:42Z"
UPDATED_AT = "2026-04-25T00:00:42Z"
DEFAULT_RELEASE_DECISION_PAGE = Path(
    "src/agilab/apps-pages/view_release_decision/src/"
    "view_release_decision/view_release_decision.py"
)


def _read_text(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        return path.read_text(encoding="utf-8"), []
    except Exception as exc:
        return "", [
            {
                "level": "error",
                "location": str(path),
                "message": f"unable to read release decision page: {exc}",
            }
        ]


def _has_all(text: str, needles: tuple[str, ...]) -> bool:
    return all(needle in text for needle in needles)


def _call_text(calls: list[dict[str, Any]]) -> str:
    return json.dumps(calls, sort_keys=True)


def _surface(
    surface_id: str,
    label: str,
    purpose: str,
    ready: bool,
    *,
    evidence: list[str],
    details: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "id": surface_id,
        "label": label,
        "page": "release_decision",
        "status": "ready" if ready else "missing",
        "purpose": purpose,
        "evidence": evidence,
        "details": dict(details),
    }


def _source_flags(page_text: str, *, page_loaded: bool) -> dict[str, bool]:
    return {
        "release_decision_page_loaded": page_loaded,
        "imports_live_renderer": "render_connector_live_ui" in page_text,
        "builds_connector_preview": "build_data_connector_ui_preview(" in page_text,
        "calls_live_renderer": "render_connector_live_ui(" in page_text,
        "stores_connector_live_ui_state": "release_decision_connector_live_ui" in page_text,
        "renders_connector_registry_paths": "connector_registry_rows" in page_text
        and "Shared connector roots" in page_text,
        "parses_manifest_import_args": "_build_manifest_import_rows" in page_text,
        "exports_imported_manifest_evidence": "imported_run_manifest_evidence" in page_text,
        "writes_promotion_decision": "_write_decision" in page_text
        and "Promotion decision exported" in page_text,
        "parses_ci_artifact_harvest": "_build_ci_artifact_harvest_rows" in page_text,
        "renders_ci_artifact_harvest": "CI artifact harvest evidence" in page_text,
        "exports_ci_artifact_harvest_evidence": "ci_artifact_harvest_evidence" in page_text,
        "tracks_artifact_attachment_status": "artifact_attachment_status" in page_text,
        "tracks_external_source_machine": "source_machine" in page_text,
    }


def build_data_connector_view_surface(
    *,
    repo_root: Path,
    settings_path: Path | None = None,
    catalog_path: Path | None = None,
    release_decision_page: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    settings_path = settings_path or (repo_root / DEFAULT_SETTINGS_RELATIVE_PATH)
    catalog_path = catalog_path or (repo_root / DEFAULT_CONNECTORS_RELATIVE_PATH)
    release_decision_page = release_decision_page or (repo_root / DEFAULT_RELEASE_DECISION_PAGE)
    if not settings_path.is_absolute():
        settings_path = repo_root / settings_path
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    if not release_decision_page.is_absolute():
        release_decision_page = repo_root / release_decision_page

    settings = load_app_settings(settings_path)
    catalog = load_connector_catalog(catalog_path)
    live_ui = build_data_connector_live_ui(
        settings=settings,
        catalog=catalog,
        settings_path=settings_path,
        catalog_path=catalog_path,
        release_decision_page=release_decision_page,
    )
    page_text, issues = _read_text(release_decision_page)
    flags = _source_flags(page_text, page_loaded=not issues)
    live_summary = live_ui.get("summary", {})
    render_payload = live_ui.get("render_payload", {})
    render_summary = render_payload.get("summary", {})
    health_probes = [
        row for row in render_payload.get("health_probes", []) if isinstance(row, dict)
    ]
    streamlit_calls = [
        row for row in live_ui.get("streamlit_calls", []) if isinstance(row, dict)
    ]
    calls_text = _call_text(streamlit_calls)
    release_decision_page_evidence = str(release_decision_page)
    renderer_evidence = "src/agilab/data_connector_live_ui.py"

    connector_state_ready = (
        live_ui.get("run_status") == "ready_for_live_ui"
        and flags["imports_live_renderer"]
        and flags["calls_live_renderer"]
        and flags["stores_connector_live_ui_state"]
        and int(render_summary.get("connector_card_count", 0) or 0) >= 3
        and int(render_summary.get("page_binding_count", 0) or 0) >= 2
        and flags["renders_connector_registry_paths"]
    )
    health_ready = (
        live_ui.get("run_status") == "ready_for_live_ui"
        and int(render_summary.get("health_probe_status_count", 0) or 0) >= 3
        and render_summary.get("operator_opt_in_required_for_health") is True
        and int(render_summary.get("network_probe_count", 0) or 0) == 0
        and {probe.get("status") for probe in health_probes} == {"unknown_not_probed"}
        and "Health probes remain unknown_not_probed until an operator opts in." in calls_text
    )
    import_export_ready = (
        flags["parses_manifest_import_args"]
        and flags["exports_imported_manifest_evidence"]
        and flags["writes_promotion_decision"]
    )
    external_artifact_ready = (
        flags["parses_ci_artifact_harvest"]
        and flags["renders_ci_artifact_harvest"]
        and flags["exports_ci_artifact_harvest_evidence"]
        and flags["tracks_artifact_attachment_status"]
        and flags["tracks_external_source_machine"]
    )
    surfaces = [
        _surface(
            "connector_state_provenance_panel",
            "Connector state and provenance panel",
            "Show connector cards, page bindings, fallback paths, and registry roots.",
            connector_state_ready,
            evidence=[release_decision_page_evidence, renderer_evidence],
            details={
                "connector_card_count": render_summary.get("connector_card_count", 0),
                "page_binding_count": render_summary.get("page_binding_count", 0),
                "legacy_fallback_count": render_summary.get("legacy_fallback_count", 0),
                "renders_connector_registry_paths": flags["renders_connector_registry_paths"],
            },
        ),
        _surface(
            "connector_health_status_panel",
            "Connector health/status panel",
            "Show planned connector health rows while keeping live probes operator-gated.",
            health_ready,
            evidence=[renderer_evidence, str(catalog_path)],
            details={
                "health_probe_status_count": render_summary.get(
                    "health_probe_status_count", 0
                ),
                "network_probe_count": render_summary.get("network_probe_count", 0),
                "operator_opt_in_required_for_health": render_summary.get(
                    "operator_opt_in_required_for_health"
                ),
                "health_status_values": render_summary.get("health_status_values", []),
            },
        ),
        _surface(
            "import_export_provenance_panel",
            "Import/export provenance panel",
            "Import external run-manifest evidence and export it in promotion decisions.",
            import_export_ready,
            evidence=[release_decision_page_evidence],
            details={
                "parses_manifest_import_args": flags["parses_manifest_import_args"],
                "exports_imported_manifest_evidence": flags[
                    "exports_imported_manifest_evidence"
                ],
                "writes_promotion_decision": flags["writes_promotion_decision"],
            },
        ),
        _surface(
            "external_artifact_traceability_panel",
            "External artifact traceability panel",
            "Import CI artifact harvest evidence with checksum, provenance, and source-machine fields.",
            external_artifact_ready,
            evidence=[release_decision_page_evidence],
            details={
                "parses_ci_artifact_harvest": flags["parses_ci_artifact_harvest"],
                "renders_ci_artifact_harvest": flags["renders_ci_artifact_harvest"],
                "exports_ci_artifact_harvest_evidence": flags[
                    "exports_ci_artifact_harvest_evidence"
                ],
                "tracks_artifact_attachment_status": flags[
                    "tracks_artifact_attachment_status"
                ],
                "tracks_external_source_machine": flags["tracks_external_source_machine"],
            },
        ),
    ]
    for surface in surfaces:
        if surface["status"] != "ready":
            issues.append(
                {
                    "level": "error",
                    "location": surface["id"],
                    "message": f"{surface['label']} is not ready",
                }
            )
    ready_count = sum(1 for surface in surfaces if surface["status"] == "ready")
    network_probe_count = int(live_summary.get("network_probe_count", 0) or 0)
    summary = {
        "execution_mode": "connector_view_surface_contract_only",
        "view_surface_count": len(surfaces),
        "ready_view_surface_count": ready_count,
        "missing_view_surface_count": len(surfaces) - ready_count,
        "release_decision_surface_count": sum(
            1 for surface in surfaces if surface.get("page") == "release_decision"
        ),
        "page_source_loaded": flags["release_decision_page_loaded"],
        "source_check_count": len(flags),
        "source_check_passed_count": sum(1 for passed in flags.values() if passed),
        "live_ui_run_status": live_ui.get("run_status", ""),
        "live_ui_schema": live_ui.get("schema", ""),
        "connector_card_count": render_summary.get("connector_card_count", 0),
        "page_binding_count": render_summary.get("page_binding_count", 0),
        "health_probe_status_count": render_summary.get("health_probe_status_count", 0),
        "external_artifact_traceability_ready": external_artifact_ready,
        "import_export_provenance_ready": import_export_ready,
        "network_probe_count": network_probe_count,
        "command_execution_count": 0,
    }
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "validated" if not issues else "invalid",
        "execution_mode": summary["execution_mode"],
        "source": {
            "settings_path": str(settings_path),
            "catalog_path": str(catalog_path),
            "release_decision_page": str(release_decision_page),
        },
        "summary": summary,
        "source_flags": flags,
        "view_surfaces": surfaces,
        "live_ui_summary": live_summary,
        "issues": issues,
        "provenance": {
            "executes_commands": False,
            "executes_network_probe": False,
            "imports_streamlit": False,
            "uses_streamlit_recorder": True,
            "source": "local_repository_files",
        },
    }


def write_data_connector_view_surface(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_view_surface(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_view_surface(
    *,
    repo_root: Path,
    output_path: Path,
    settings_path: Path | None = None,
    catalog_path: Path | None = None,
    release_decision_page: Path | None = None,
) -> dict[str, Any]:
    state = build_data_connector_view_surface(
        repo_root=repo_root,
        settings_path=settings_path,
        catalog_path=catalog_path,
        release_decision_page=release_decision_page,
    )
    path = write_data_connector_view_surface(output_path, state)
    reloaded = load_data_connector_view_surface(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "validated",
        "path": str(path),
        "settings_path": state.get("source", {}).get("settings_path", ""),
        "catalog_path": state.get("source", {}).get("catalog_path", ""),
        "release_decision_page": state.get("source", {}).get("release_decision_page", ""),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
