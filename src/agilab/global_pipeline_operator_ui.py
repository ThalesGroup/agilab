# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Operator UI component model for AGILAB global pipeline evidence."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
from typing import Any, Mapping

from agilab.global_pipeline_live_state_updates import load_live_state_updates
from agilab.global_pipeline_operator_actions import (
    SCHEMA as OPERATOR_ACTIONS_SCHEMA,
    load_operator_actions,
    persist_operator_actions,
)


SCHEMA = "agilab.global_pipeline_operator_ui.v1"
DEFAULT_RUN_ID = "global-dag-operator-ui-proof"
PERSISTENCE_FORMAT = "json+html"
CREATED_AT = "2026-04-25T00:00:19Z"
UPDATED_AT = "2026-04-25T00:00:19Z"
ACTION_HANDLER_COMMAND = "tools/global_pipeline_operator_actions_report.py --compact"


@dataclass(frozen=True)
class OperatorUiIssue:
    level: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "location": self.location,
            "message": self.message,
        }


@dataclass(frozen=True)
class OperatorUiProof:
    ok: bool
    issues: tuple[OperatorUiIssue, ...]
    path: str
    html_path: str
    operator_actions_path: str
    operator_ui: dict[str, Any]
    reloaded_ui: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.operator_ui == self.reloaded_ui

    @property
    def component_count(self) -> int:
        return _summary_int(self.operator_ui, "component_count")

    @property
    def unit_card_count(self) -> int:
        return _summary_int(self.operator_ui, "unit_card_count")

    @property
    def action_control_count(self) -> int:
        return _summary_int(self.operator_ui, "action_control_count")

    @property
    def artifact_row_count(self) -> int:
        return _summary_int(self.operator_ui, "artifact_row_count")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "html_path": self.html_path,
            "operator_actions_path": self.operator_actions_path,
            "round_trip_ok": self.round_trip_ok,
            "component_count": self.component_count,
            "unit_card_count": self.unit_card_count,
            "action_control_count": self.action_control_count,
            "artifact_row_count": self.artifact_row_count,
            "operator_ui": self.operator_ui,
            "reloaded_ui": self.reloaded_ui,
        }


def _issue(location: str, message: str) -> OperatorUiIssue:
    return OperatorUiIssue(level="error", location=location, message=message)


def _summary_int(state: Mapping[str, Any], key: str) -> int:
    summary = state.get("summary", {})
    value = summary.get(key, 0) if isinstance(summary, dict) else 0
    return int(value or 0)


def _request_rows(operator_actions: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = operator_actions.get("requests", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _artifact_rows(operator_actions: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = operator_actions.get("artifacts", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _update_rows(live_state_updates: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = live_state_updates.get("updates", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _live_state_for_actions(operator_actions: Mapping[str, Any]) -> dict[str, Any]:
    path = operator_actions.get("source", {}).get("live_state_updates_path", "")
    if not path:
        return {}
    try:
        return load_live_state_updates(Path(str(path)))
    except Exception:
        return {}


def _unit_cards(live_state_updates: Mapping[str, Any]) -> list[dict[str, Any]]:
    unit_states = live_state_updates.get("latest_state", {}).get("unit_states", {})
    if not isinstance(unit_states, dict):
        unit_states = {}
    return [
        {
            "unit_id": "queue_baseline",
            "title": "Queue baseline",
            "state": str(unit_states.get("queue_baseline", "completed")),
            "app": "uav_queue_project",
        },
        {
            "unit_id": "relay_followup",
            "title": "Relay follow-up",
            "state": str(unit_states.get("relay_followup", "completed")),
            "app": "uav_relay_queue_project",
        },
    ]


def _dependency_payload(live_state_updates: Mapping[str, Any]) -> dict[str, Any]:
    for update in _update_rows(live_state_updates):
        if update.get("kind") == "dependency_state_update":
            payload = update.get("payload", {})
            return payload if isinstance(payload, dict) else {}
    return {
        "from": "queue_baseline",
        "to": "relay_followup",
        "artifact": "queue_metrics",
        "cross_app": True,
    }


def _action_controls(operator_actions: Mapping[str, Any]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for request in _request_rows(operator_actions):
        action_id = str(request.get("action_id", ""))
        action = str(request.get("action", ""))
        unit_id = str(request.get("unit_id", ""))
        label_action = "Retry" if action == "retry" else "Partial rerun"
        controls.append(
            {
                "id": f"control:{action_id}",
                "control_type": "button",
                "label": f"{label_action} {unit_id}",
                "action_id": action_id,
                "unit_id": unit_id,
                "action": action,
                "enabled": True,
                "execution_status": str(request.get("status", "")),
                "handler_command": ACTION_HANDLER_COMMAND,
            }
        )
    return controls


def _artifact_table_rows(operator_actions: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "artifact": str(artifact.get("artifact", "")),
            "producer": str(artifact.get("producer", "")),
            "kind": str(artifact.get("kind", "")),
            "status": str(artifact.get("status", "")),
            "path": str(artifact.get("path", "")),
        }
        for artifact in _artifact_rows(operator_actions)
    ]


def build_operator_ui(
    *,
    operator_actions: Mapping[str, Any],
    operator_actions_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    live_state_updates = _live_state_for_actions(operator_actions)
    unit_cards = _unit_cards(live_state_updates)
    dependency_payload = _dependency_payload(live_state_updates)
    updates = list(_update_rows(live_state_updates))
    action_controls = _action_controls(operator_actions)
    artifact_rows = _artifact_table_rows(operator_actions)
    source = operator_actions.get("source", {})
    components = [
        {
            "id": "status_banner",
            "component": "status_banner",
            "title": "Global DAG status",
            "state": operator_actions.get("run_status", ""),
            "message": "Global DAG action replay evidence is ready.",
        },
        {
            "id": "unit_cards",
            "component": "unit_cards",
            "title": "DAG units",
            "items": unit_cards,
        },
        {
            "id": "dependency_graph",
            "component": "dependency_graph",
            "title": "Cross-app dependency",
            "edge": dependency_payload,
        },
        {
            "id": "update_timeline",
            "component": "timeline",
            "title": "Live update stream",
            "items": updates,
        },
        {
            "id": "action_controls",
            "component": "action_controls",
            "title": "Operator actions",
            "items": action_controls,
        },
        {
            "id": "artifact_table",
            "component": "artifact_table",
            "title": "Action artifacts",
            "items": artifact_rows,
        },
    ]
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "ready_for_operator_review",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "source": {
            "operator_actions_path": str(operator_actions_path),
            "operator_actions_schema": operator_actions.get("schema", ""),
            "operator_actions_run_id": operator_actions.get("run_id", ""),
            "operator_actions_run_status": operator_actions.get("run_status", ""),
            "source_real_execution_scope": source.get("source_real_execution_scope", ""),
        },
        "summary": {
            "component_count": len(components),
            "unit_card_count": len(unit_cards),
            "action_control_count": len(action_controls),
            "artifact_row_count": len(artifact_rows),
            "timeline_update_count": len(updates),
            "supported_action_ids": [
                control["action_id"]
                for control in action_controls
            ],
            "source_real_execution_scope": source.get("source_real_execution_scope", ""),
        },
        "components": components,
        "rendering": {
            "renderer": "static_html_components",
            "streamlit_page": False,
            "supports_operator_actions": True,
            "action_handler_command": ACTION_HANDLER_COMMAND,
        },
        "provenance": {
            "projection_mode": "operator_ui_components_from_action_outcomes",
            "source_operator_actions_schema": operator_actions.get("schema", ""),
            "source_operator_actions_run_id": operator_actions.get("run_id", ""),
            "source_operator_actions_path": str(operator_actions_path),
        },
    }


def render_operator_ui_html(operator_ui: Mapping[str, Any]) -> str:
    components = operator_ui.get("components", [])
    iterable_components = components if isinstance(components, list) else []
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>AGILAB Global DAG Operator UI</title></head>",
        "<body><main data-agilab-component=\"global-dag-operator-ui\">",
        "<h1>AGILAB Global DAG Operator UI</h1>",
    ]
    for component in iterable_components:
        if not isinstance(component, dict):
            continue
        component_id = escape(str(component.get("id", "")))
        title = escape(str(component.get("title", component_id)))
        parts.append(f"<section id=\"{component_id}\" data-component=\"{component_id}\">")
        parts.append(f"<h2>{title}</h2>")
        if component_id == "unit_cards":
            for item in component.get("items", []):
                parts.append(
                    "<article class=\"unit-card\">"
                    f"<h3>{escape(str(item.get('unit_id', '')))}</h3>"
                    f"<p>{escape(str(item.get('state', '')))}</p>"
                    f"<small>{escape(str(item.get('app', '')))}</small>"
                    "</article>"
                )
        elif component_id == "action_controls":
            for item in component.get("items", []):
                action_id = escape(str(item.get("action_id", "")))
                label = escape(str(item.get("label", "")))
                status = escape(str(item.get("execution_status", "")))
                parts.append(
                    f"<button data-action-id=\"{action_id}\" "
                    f"data-handler=\"{escape(ACTION_HANDLER_COMMAND)}\">"
                    f"{label}</button><span>{status}</span>"
                )
        elif component_id == "artifact_table":
            parts.append("<table><tbody>")
            for item in component.get("items", []):
                parts.append(
                    "<tr>"
                    f"<td>{escape(str(item.get('artifact', '')))}</td>"
                    f"<td>{escape(str(item.get('status', '')))}</td>"
                    f"<td>{escape(str(item.get('path', '')))}</td>"
                    "</tr>"
                )
            parts.append("</tbody></table>")
        else:
            parts.append(f"<pre>{escape(json.dumps(component, sort_keys=True))}</pre>")
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def write_operator_ui(path: Path, operator_ui: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(operator_ui, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_operator_ui(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def write_operator_ui_html(path: Path, operator_ui: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_operator_ui_html(operator_ui) + "\n", encoding="utf-8")
    return path


def persist_operator_ui(
    *,
    repo_root: Path,
    output_path: Path,
    html_output_path: Path | None = None,
    operator_actions_path: Path | None = None,
    workspace_path: Path | None = None,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> OperatorUiProof:
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser()
    html_output_path = html_output_path or output_path.with_suffix(".html")
    workspace_path = workspace_path or (
        output_path.parent / "global_pipeline_operator_ui_workspace"
    )
    if operator_actions_path is None:
        generated_operator_actions_path = (
            output_path.parent / "global_pipeline_operator_actions.json"
        )
        persist_operator_actions(
            repo_root=repo_root,
            output_path=generated_operator_actions_path,
            workspace_path=workspace_path,
            dag_path=dag_path,
        )
        operator_actions_path = generated_operator_actions_path

    operator_actions = load_operator_actions(operator_actions_path)
    issues: list[OperatorUiIssue] = []
    operator_ui = build_operator_ui(
        operator_actions=operator_actions,
        operator_actions_path=operator_actions_path,
        run_id=run_id,
    )
    path = write_operator_ui(output_path, operator_ui)
    html_path = write_operator_ui_html(html_output_path, operator_ui)
    reloaded = load_operator_ui(path)
    if operator_ui != reloaded:
        issues.append(
            _issue(
                "persistence.round_trip",
                "operator UI model changed after JSON write/read",
            )
        )
    if operator_ui.get("source", {}).get("operator_actions_schema") != OPERATOR_ACTIONS_SCHEMA:
        issues.append(
            _issue(
                "source.operator_actions_schema",
                "operator UI source is not an operator-actions JSON",
            )
        )
    if not Path(html_path).is_file():
        issues.append(_issue("rendering.html", "operator UI HTML was not written"))
    return OperatorUiProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        html_path=str(html_path),
        operator_actions_path=str(operator_actions_path),
        operator_ui=operator_ui,
        reloaded_ui=reloaded,
    )


__all__ = [
    "ACTION_HANDLER_COMMAND",
    "DEFAULT_RUN_ID",
    "PERSISTENCE_FORMAT",
    "SCHEMA",
    "OperatorUiIssue",
    "OperatorUiProof",
    "build_operator_ui",
    "load_operator_ui",
    "persist_operator_ui",
    "render_operator_ui_html",
    "write_operator_ui",
    "write_operator_ui_html",
]
