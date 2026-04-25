# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Static connector UI preview assembly for AGILAB evidence reports."""

from __future__ import annotations

from collections import Counter
from html import escape
import json
from pathlib import Path
from typing import Any, Mapping

from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    build_data_connector_facility,
    load_connector_catalog,
)
from agilab.data_connector_health import build_data_connector_health
from agilab.data_connector_resolution import (
    DEFAULT_SETTINGS_RELATIVE_PATH,
    build_data_connector_resolution,
    load_app_settings,
)


SCHEMA = "agilab.data_connector_ui_preview.v1"
DEFAULT_RUN_ID = "data-connector-ui-preview-proof"
CREATED_AT = "2026-04-25T00:00:25Z"
UPDATED_AT = "2026-04-25T00:00:25Z"


def _by_connector_id(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("connector_id", "") or "") for row in rows)


def _connector_cards(
    connectors: list[dict[str, Any]],
    resolution_rows: list[dict[str, Any]],
    health_probes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs_by_connector = _by_connector_id(resolution_rows)
    probe_by_connector = {
        str(probe.get("connector_id", "") or ""): probe
        for probe in health_probes
        if isinstance(probe, dict)
    }
    cards = []
    for connector in connectors:
        connector_id = str(connector.get("id", "") or "")
        probe = probe_by_connector.get(connector_id, {})
        auth_ref = str(connector.get("auth_ref", "") or "")
        cards.append(
            {
                "component": "connector_card",
                "connector_id": connector_id,
                "label": str(connector.get("label", "") or ""),
                "kind": str(connector.get("kind", "") or ""),
                "reference_count": refs_by_connector[connector_id],
                "health_status": probe.get("status", "unknown_not_probed"),
                "probe_type": probe.get("probe_type", ""),
                "operator_context_required": probe.get(
                    "operator_context_required",
                    True,
                ),
                "auth_boundary": "env_ref" if auth_ref.startswith("env:") else "none",
            }
        )
    return cards


def _html_table(title: str, rows: list[dict[str, Any]], columns: list[str]) -> str:
    header = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "\n".join(body_rows) or f"<tr><td colspan=\"{len(columns)}\">none</td></tr>"
    return (
        f"<section><h2>{escape(title)}</h2><table><thead><tr>{header}</tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def render_connector_ui_preview(state: Mapping[str, Any]) -> str:
    cards = [row for row in state.get("connector_cards", []) if isinstance(row, dict)]
    page_bindings = [
        row
        for row in state.get("page_bindings", [])
        if isinstance(row, dict)
    ]
    legacy_fallbacks = [
        row
        for row in state.get("legacy_fallbacks", [])
        if isinstance(row, dict)
    ]
    summary = state.get("summary", {})
    return "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset=\"utf-8\"><title>Connector UI Preview</title>",
            "<style>body{font-family:Arial,sans-serif;margin:2rem;}"
            "table{border-collapse:collapse;width:100%;margin-bottom:1.5rem;}"
            "th,td{border:1px solid #ccd;padding:.5rem;text-align:left;}"
            ".banner{background:#eef7f1;border:1px solid #9bc5a8;padding:1rem;}</style>",
            "</head><body>",
            "<h1>Data Connector UI Preview</h1>",
            (
                "<p class=\"banner\">"
                f"Mode: {escape(str(summary.get('execution_mode', '')))}; "
                f"network probes executed: {summary.get('network_probe_count', 0)}; "
                "health status remains unknown until operator opt-in."
                "</p>"
            ),
            _html_table(
                "Connector cards",
                cards,
                [
                    "connector_id",
                    "kind",
                    "reference_count",
                    "health_status",
                    "probe_type",
                    "auth_boundary",
                ],
            ),
            _html_table(
                "Page connector references",
                page_bindings,
                ["page", "ref_name", "connector_id", "kind", "resolved_target"],
            ),
            _html_table(
                "Legacy path fallbacks",
                legacy_fallbacks,
                ["ref_name", "status", "path", "expanded_path"],
            ),
            "</body></html>",
        ]
    )


def build_data_connector_ui_preview(
    *,
    settings: Mapping[str, Any],
    catalog: Mapping[str, Any],
    settings_path: Path | str,
    catalog_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    facility_state = build_data_connector_facility(catalog, source_path=catalog_path)
    resolution_state = build_data_connector_resolution(
        settings=settings,
        facility_state=facility_state,
        settings_path=settings_path,
        catalog_path=catalog_path,
    )
    health_state = build_data_connector_health(catalog, source_path=catalog_path)
    connectors = [
        connector
        for connector in facility_state.get("connectors", [])
        if isinstance(connector, dict)
    ]
    resolution_rows = [
        row
        for row in resolution_state.get("resolutions", [])
        if isinstance(row, dict)
    ]
    page_bindings = [row for row in resolution_rows if row.get("source") == "page_connector_refs"]
    legacy_fallbacks = [
        row
        for row in resolution_state.get("legacy_fallbacks", [])
        if isinstance(row, dict)
    ]
    health_probes = [
        probe
        for probe in health_state.get("probes", [])
        if isinstance(probe, dict)
    ]
    issues = []
    for name, state in (
        ("facility", facility_state),
        ("resolution", resolution_state),
        ("health", health_state),
    ):
        if state.get("run_status") not in {"validated", "resolved", "planned"}:
            issues.append(
                {
                    "level": "error",
                    "location": name,
                    "message": f"{name} state is not ready: {state.get('run_status')}",
                }
            )
    connector_cards = _connector_cards(connectors, resolution_rows, health_probes)
    summary = {
        "execution_mode": "static_ui_preview_only",
        "persistence_format": "json+html",
        "connector_card_count": len(connector_cards),
        "page_binding_count": len(page_bindings),
        "legacy_fallback_count": len(legacy_fallbacks),
        "health_probe_status_count": len(health_probes),
        "component_count": 5 + len(connector_cards),
        "network_probe_count": 0,
        "html_rendered": True,
        "source_execution_modes": {
            "facility": facility_state.get("execution_mode", ""),
            "resolution": resolution_state.get("execution_mode", ""),
            "health": health_state.get("execution_mode", ""),
        },
    }
    state = {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "ready_for_ui_preview" if not issues else "invalid",
        "execution_mode": summary["execution_mode"],
        "persistence_format": summary["persistence_format"],
        "source": {
            "settings_path": str(settings_path),
            "catalog_path": str(catalog_path),
        },
        "summary": summary,
        "connector_cards": connector_cards,
        "page_bindings": page_bindings,
        "legacy_fallbacks": legacy_fallbacks,
        "health_probes": health_probes,
        "issues": issues,
        "provenance": {
            "executes_network_probe": False,
            "renders_static_html": True,
            "operator_opt_in_required_for_health": True,
        },
    }
    state["html"] = render_connector_ui_preview(state)
    return state


def write_data_connector_ui_preview(
    json_path: Path,
    html_path: Path,
    state: Mapping[str, Any],
) -> tuple[Path, Path]:
    json_path = json_path.expanduser()
    html_path = html_path.expanduser()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(str(state.get("html", "")), encoding="utf-8")
    return json_path, html_path


def load_data_connector_ui_preview(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_ui_preview(
    *,
    repo_root: Path,
    output_path: Path,
    html_output_path: Path,
    settings_path: Path | None = None,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    settings_path = settings_path or (repo_root / DEFAULT_SETTINGS_RELATIVE_PATH)
    catalog_path = catalog_path or (repo_root / DEFAULT_CONNECTORS_RELATIVE_PATH)
    if not settings_path.is_absolute():
        settings_path = repo_root / settings_path
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    settings = load_app_settings(settings_path)
    catalog = load_connector_catalog(catalog_path)
    state = build_data_connector_ui_preview(
        settings=settings,
        catalog=catalog,
        settings_path=settings_path,
        catalog_path=catalog_path,
    )
    json_path, html_path = write_data_connector_ui_preview(
        output_path,
        html_output_path,
        state,
    )
    reloaded = load_data_connector_ui_preview(json_path)
    return {
        "ok": state == reloaded and state.get("run_status") == "ready_for_ui_preview",
        "path": str(json_path),
        "html_path": str(html_path),
        "settings_path": str(settings_path),
        "catalog_path": str(catalog_path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
        "html_written": html_path.is_file() and html_path.stat().st_size > 0,
    }
