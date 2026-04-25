# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Live-update payload projection for AGILAB global pipeline evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from agilab.global_pipeline_dependency_view import (
    SCHEMA as DEPENDENCY_VIEW_SCHEMA,
    load_dependency_view,
    persist_dependency_view,
)


SCHEMA = "agilab.global_pipeline_live_state_updates.v1"
DEFAULT_RUN_ID = "global-dag-live-state-updates-proof"
PERSISTENCE_FORMAT = "json"
CREATED_AT = "2026-04-25T00:00:08Z"
UPDATED_AT = "2026-04-25T00:00:13Z"
GRAPH_READY_AT = "2026-04-25T00:00:08Z"
QUEUE_VISIBLE_AT = "2026-04-25T00:00:09Z"
ARTIFACT_VISIBLE_AT = "2026-04-25T00:00:10Z"
DEPENDENCY_VISIBLE_AT = "2026-04-25T00:00:11Z"
RELAY_VISIBLE_AT = "2026-04-25T00:00:12Z"
ACTIONS_VISIBLE_AT = "2026-04-25T00:00:13Z"


@dataclass(frozen=True)
class LiveStateUpdateIssue:
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
class LiveStateUpdateProof:
    ok: bool
    issues: tuple[LiveStateUpdateIssue, ...]
    path: str
    dependency_view_path: str
    live_state_updates: dict[str, Any]
    reloaded_updates: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.live_state_updates == self.reloaded_updates

    @property
    def update_count(self) -> int:
        updates = self.live_state_updates.get("updates", [])
        return len(updates) if isinstance(updates, list) else 0

    @property
    def unit_update_count(self) -> int:
        return _summary_int(self.live_state_updates, "unit_update_count")

    @property
    def artifact_update_count(self) -> int:
        return _summary_int(self.live_state_updates, "artifact_update_count")

    @property
    def dependency_update_count(self) -> int:
        return _summary_int(self.live_state_updates, "dependency_update_count")

    @property
    def action_update_count(self) -> int:
        return _summary_int(self.live_state_updates, "action_update_count")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "dependency_view_path": self.dependency_view_path,
            "round_trip_ok": self.round_trip_ok,
            "update_count": self.update_count,
            "unit_update_count": self.unit_update_count,
            "artifact_update_count": self.artifact_update_count,
            "dependency_update_count": self.dependency_update_count,
            "action_update_count": self.action_update_count,
            "live_state_updates": self.live_state_updates,
            "reloaded_updates": self.reloaded_updates,
        }


def _issue(location: str, message: str) -> LiveStateUpdateIssue:
    return LiveStateUpdateIssue(level="error", location=location, message=message)


def _summary_int(state: Mapping[str, Any], key: str) -> int:
    summary = state.get("summary", {})
    value = summary.get(key, 0) if isinstance(summary, dict) else 0
    return int(value or 0)


def _node_rows(dependency_view: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = dependency_view.get("nodes", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _edge_rows(dependency_view: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = dependency_view.get("edges", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _artifact_flow_rows(dependency_view: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = dependency_view.get("artifact_flow", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _node_by_id(dependency_view: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node.get("id", "")): node for node in _node_rows(dependency_view)}


def _update_row(
    *,
    sequence: int,
    timestamp: str,
    kind: str,
    target_type: str,
    target_id: str,
    status: str,
    message: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "timestamp": timestamp,
        "kind": kind,
        "target_type": target_type,
        "target_id": target_id,
        "status": status,
        "message": message,
        "operator_visible": True,
        "payload": dict(payload),
    }


def _action_ids_for_prefix(node: Mapping[str, Any], prefix: str) -> list[str]:
    actions = node.get("action_ids", [])
    if not isinstance(actions, list):
        return []
    return [str(action) for action in actions if str(action).endswith(f":{prefix}")]


def _queue_metrics_flow(
    artifact_flow: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    for row in artifact_flow:
        if row.get("artifact") == "queue_metrics":
            return row
    return {}


def build_live_state_updates(
    *,
    dependency_view: Mapping[str, Any],
    dependency_view_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    nodes = _node_by_id(dependency_view)
    edges = _edge_rows(dependency_view)
    artifact_flow = _artifact_flow_rows(dependency_view)
    summary = dependency_view.get("summary", {})
    source = dependency_view.get("source", {})
    adjacency = dependency_view.get("adjacency", {})
    queue = nodes.get("queue_baseline", {})
    relay = nodes.get("relay_followup", {})
    edge = edges[0] if edges else {}
    queue_metrics = _queue_metrics_flow(artifact_flow)
    retry_action_ids = [
        *_action_ids_for_prefix(queue, "retry"),
        *_action_ids_for_prefix(relay, "retry"),
    ]
    partial_rerun_action_ids = [
        *_action_ids_for_prefix(queue, "partial_rerun"),
        *_action_ids_for_prefix(relay, "partial_rerun"),
    ]
    updates = [
        _update_row(
            sequence=1,
            timestamp=GRAPH_READY_AT,
            kind="dependency_graph_ready",
            target_type="global_dag",
            target_id="global_pipeline",
            status="ready",
            message="full-DAG dependency graph is ready for operator update rendering",
            payload={
                "node_count": summary.get("node_count", 0),
                "edge_count": summary.get("edge_count", 0),
                "adjacency": adjacency,
            },
        ),
        _update_row(
            sequence=2,
            timestamp=QUEUE_VISIBLE_AT,
            kind="unit_state_update",
            target_type="unit",
            target_id="queue_baseline",
            status=str(queue.get("operator_state", "")),
            message="queue_baseline is visible as completed",
            payload={
                "app": queue.get("app", ""),
                "produced_artifact_ids": queue.get("produced_artifact_ids", []),
                "downstream_unit_ids": queue.get("downstream_unit_ids", []),
            },
        ),
        _update_row(
            sequence=3,
            timestamp=ARTIFACT_VISIBLE_AT,
            kind="artifact_state_update",
            target_type="artifact",
            target_id="queue_metrics",
            status=str(queue_metrics.get("status", "")),
            message="queue_metrics is available for relay_followup",
            payload={
                "producer_unit_id": queue_metrics.get("producer_unit_id", ""),
                "consumer_unit_ids": queue_metrics.get("consumer_unit_ids", []),
                "path": queue_metrics.get("path", ""),
            },
        ),
        _update_row(
            sequence=4,
            timestamp=DEPENDENCY_VISIBLE_AT,
            kind="dependency_state_update",
            target_type="edge",
            target_id=str(edge.get("id", "")),
            status=str(edge.get("status", "")),
            message="queue_baseline -> relay_followup dependency is available",
            payload={
                "from": edge.get("from", ""),
                "to": edge.get("to", ""),
                "artifact": edge.get("artifact", ""),
                "cross_app": edge.get("cross_app", False),
                "producer_app": edge.get("producer_app", ""),
                "consumer_app": edge.get("consumer_app", ""),
            },
        ),
        _update_row(
            sequence=5,
            timestamp=RELAY_VISIBLE_AT,
            kind="unit_state_update",
            target_type="unit",
            target_id="relay_followup",
            status=str(relay.get("operator_state", "")),
            message="relay_followup is visible as completed",
            payload={
                "app": relay.get("app", ""),
                "consumed_artifact_ids": relay.get("consumed_artifact_ids", []),
                "upstream_unit_ids": relay.get("upstream_unit_ids", []),
            },
        ),
        _update_row(
            sequence=6,
            timestamp=ACTIONS_VISIBLE_AT,
            kind="operator_actions_update",
            target_type="run",
            target_id="global_pipeline",
            status="ready_for_operator_review",
            message="retry and partial-rerun actions are visible for completed units",
            payload={
                "retry_action_ids": retry_action_ids,
                "partial_rerun_action_ids": partial_rerun_action_ids,
            },
        ),
    ]
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "ready_for_operator_review",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "source": {
            "dependency_view_path": str(dependency_view_path),
            "dependency_view_schema": dependency_view.get("schema", ""),
            "dependency_view_run_id": dependency_view.get("run_id", ""),
            "dependency_view_run_status": dependency_view.get("run_status", ""),
            "source_real_execution_scope": (
                summary.get("source_real_execution_scope", "")
                if isinstance(summary, dict)
                else ""
            ),
            "source_operator_state_path": source.get("operator_state_path", ""),
        },
        "summary": {
            "update_count": len(updates),
            "graph_update_count": 1,
            "unit_update_count": 2,
            "artifact_update_count": 1,
            "dependency_update_count": 1,
            "action_update_count": 1,
            "visible_unit_ids": summary.get("visible_unit_ids", []),
            "cross_app_edge_count": summary.get("cross_app_edge_count", 0),
            "retry_action_count": len(retry_action_ids),
            "partial_rerun_action_count": len(partial_rerun_action_ids),
            "source_real_execution_scope": (
                summary.get("source_real_execution_scope", "")
                if isinstance(summary, dict)
                else ""
            ),
        },
        "update_stream": {
            "mode": "deterministic_replay_contract",
            "transport": "json_snapshot",
            "live_runtime_service": False,
            "ui_component": False,
        },
        "updates": updates,
        "latest_state": {
            "unit_states": {
                "queue_baseline": queue.get("operator_state", ""),
                "relay_followup": relay.get("operator_state", ""),
            },
            "artifact_states": {"queue_metrics": queue_metrics.get("status", "")},
            "dependency_states": {str(edge.get("id", "")): edge.get("status", "")},
        },
        "provenance": {
            "projection_mode": "live_update_stream_from_dependency_view",
            "source_dependency_view_schema": dependency_view.get("schema", ""),
            "source_dependency_view_run_id": dependency_view.get("run_id", ""),
            "source_dependency_view_path": str(dependency_view_path),
        },
    }


def write_live_state_updates(path: Path, updates: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updates, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_live_state_updates(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_live_state_updates(
    *,
    repo_root: Path,
    output_path: Path,
    dependency_view_path: Path | None = None,
    workspace_path: Path | None = None,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> LiveStateUpdateProof:
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser()
    if dependency_view_path is None:
        generated_dependency_view_path = (
            output_path.parent / "global_pipeline_dependency_view.json"
        )
        persist_dependency_view(
            repo_root=repo_root,
            output_path=generated_dependency_view_path,
            workspace_path=workspace_path
            or (output_path.parent / "global_pipeline_live_state_workspace"),
            dag_path=dag_path,
        )
        dependency_view_path = generated_dependency_view_path

    dependency_view = load_dependency_view(dependency_view_path)
    issues: list[LiveStateUpdateIssue] = []
    updates = build_live_state_updates(
        dependency_view=dependency_view,
        dependency_view_path=dependency_view_path,
        run_id=run_id,
    )
    path = write_live_state_updates(output_path, updates)
    reloaded = load_live_state_updates(path)
    if updates != reloaded:
        issues.append(
            _issue(
                "persistence.round_trip",
                "live state updates changed after JSON write/read",
            )
        )
    if updates.get("source", {}).get("dependency_view_schema") != DEPENDENCY_VIEW_SCHEMA:
        issues.append(
            _issue(
                "source.dependency_view_schema",
                "live state updates source is not a dependency-view JSON",
            )
        )
    return LiveStateUpdateProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        dependency_view_path=str(dependency_view_path),
        live_state_updates=updates,
        reloaded_updates=reloaded,
    )


__all__ = [
    "DEFAULT_RUN_ID",
    "PERSISTENCE_FORMAT",
    "SCHEMA",
    "LiveStateUpdateIssue",
    "LiveStateUpdateProof",
    "build_live_state_updates",
    "load_live_state_updates",
    "persist_live_state_updates",
    "write_live_state_updates",
]
