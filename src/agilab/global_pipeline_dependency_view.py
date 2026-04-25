# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Dependency-view projection for AGILAB global pipeline operator evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from agilab.global_pipeline_operator_state import (
    SCHEMA as OPERATOR_STATE_SCHEMA,
    load_operator_state,
    persist_operator_state,
)


SCHEMA = "agilab.global_pipeline_dependency_view.v1"
DEFAULT_RUN_ID = "global-dag-dependency-view-proof"
PERSISTENCE_FORMAT = "json"
CREATED_AT = "2026-04-25T00:00:07Z"
UPDATED_AT = "2026-04-25T00:00:07Z"


@dataclass(frozen=True)
class DependencyViewIssue:
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
class DependencyViewProof:
    ok: bool
    issues: tuple[DependencyViewIssue, ...]
    path: str
    operator_state_path: str
    dependency_view: dict[str, Any]
    reloaded_view: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.dependency_view == self.reloaded_view

    @property
    def node_count(self) -> int:
        nodes = self.dependency_view.get("nodes", [])
        return len(nodes) if isinstance(nodes, list) else 0

    @property
    def edge_count(self) -> int:
        edges = self.dependency_view.get("edges", [])
        return len(edges) if isinstance(edges, list) else 0

    @property
    def cross_app_edge_count(self) -> int:
        edges = self.dependency_view.get("edges", [])
        if not isinstance(edges, list):
            return 0
        return sum(
            1
            for edge in edges
            if isinstance(edge, dict) and edge.get("cross_app") is True
        )

    @property
    def visible_unit_ids(self) -> tuple[str, ...]:
        summary = self.dependency_view.get("summary", {})
        values = summary.get("visible_unit_ids", []) if isinstance(summary, dict) else []
        return tuple(str(value) for value in values if str(value))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "operator_state_path": self.operator_state_path,
            "round_trip_ok": self.round_trip_ok,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "cross_app_edge_count": self.cross_app_edge_count,
            "visible_unit_ids": list(self.visible_unit_ids),
            "dependency_view": self.dependency_view,
            "reloaded_view": self.reloaded_view,
        }


def _issue(location: str, message: str) -> DependencyViewIssue:
    return DependencyViewIssue(level="error", location=location, message=message)


def _unit_rows(operator_state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = operator_state.get("operator_units", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _artifact_rows(operator_state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = operator_state.get("artifacts", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _handoff_rows(operator_state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = operator_state.get("handoffs", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _adjacency_from_handoffs(
    unit_ids: tuple[str, ...],
    handoffs: tuple[dict[str, Any], ...],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    upstream = {unit_id: [] for unit_id in unit_ids}
    downstream = {unit_id: [] for unit_id in unit_ids}
    for handoff in handoffs:
        producer = str(handoff.get("from", ""))
        consumer = str(handoff.get("to", ""))
        if producer in downstream and consumer and consumer not in downstream[producer]:
            downstream[producer].append(consumer)
        if consumer in upstream and producer and producer not in upstream[consumer]:
            upstream[consumer].append(producer)
    return upstream, downstream


def _artifact_ids_for_unit(artifacts: tuple[dict[str, Any], ...], unit_id: str) -> list[str]:
    return [
        str(artifact.get("artifact", ""))
        for artifact in artifacts
        if artifact.get("producer") == unit_id and artifact.get("artifact")
    ]


def _consumed_artifacts_for_unit(
    handoffs: tuple[dict[str, Any], ...],
    unit_id: str,
) -> list[str]:
    return [
        str(handoff.get("artifact", ""))
        for handoff in handoffs
        if handoff.get("to") == unit_id and handoff.get("artifact")
    ]


def _action_ids_for_unit(unit: Mapping[str, Any]) -> list[str]:
    actions = unit.get("actions", [])
    if not isinstance(actions, list):
        return []
    return [
        str(action.get("id", ""))
        for action in actions
        if isinstance(action, dict) and action.get("id")
    ]


def _node_rows(
    *,
    units: tuple[dict[str, Any], ...],
    artifacts: tuple[dict[str, Any], ...],
    handoffs: tuple[dict[str, Any], ...],
    upstream: Mapping[str, list[str]],
    downstream: Mapping[str, list[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit in units:
        unit_id = str(unit.get("id", ""))
        produced_artifact_ids = _artifact_ids_for_unit(artifacts, unit_id)
        consumed_artifact_ids = _consumed_artifacts_for_unit(handoffs, unit_id)
        rows.append(
            {
                "id": unit_id,
                "app": str(unit.get("app", "")),
                "operator_state": str(unit.get("operator_state", "")),
                "dispatch_status": str(unit.get("dispatch_status", "")),
                "real_execution": bool(unit.get("real_execution")),
                "upstream_unit_ids": upstream.get(unit_id, []),
                "downstream_unit_ids": downstream.get(unit_id, []),
                "produced_artifact_ids": produced_artifact_ids,
                "consumed_artifact_ids": consumed_artifact_ids,
                "action_ids": _action_ids_for_unit(unit),
                "provenance": dict(unit.get("provenance", {})),
            }
        )
    return rows


def _edge_rows(
    *,
    handoffs: tuple[dict[str, Any], ...],
    units_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for handoff in handoffs:
        producer = str(handoff.get("from", ""))
        consumer = str(handoff.get("to", ""))
        artifact = str(handoff.get("artifact", ""))
        producer_unit = units_by_id.get(producer, {})
        consumer_unit = units_by_id.get(consumer, {})
        producer_app = str(producer_unit.get("app", ""))
        consumer_app = str(consumer_unit.get("app", ""))
        rows.append(
            {
                "id": f"{producer}->{consumer}:{artifact}",
                "from": producer,
                "to": consumer,
                "relation": "artifact_handoff",
                "artifact": artifact,
                "status": str(handoff.get("status", "")),
                "path": str(handoff.get("path", "")),
                "handoff": str(handoff.get("handoff", "")),
                "producer_app": producer_app,
                "consumer_app": consumer_app,
                "producer_state": str(producer_unit.get("operator_state", "")),
                "consumer_state": str(consumer_unit.get("operator_state", "")),
                "cross_app": bool(producer_app and consumer_app and producer_app != consumer_app),
                "operator_visible": bool(producer_unit and consumer_unit),
            }
        )
    return rows


def _artifact_flow_rows(
    *,
    artifacts: tuple[dict[str, Any], ...],
    handoffs: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    consumers_by_artifact: dict[str, list[str]] = {}
    for handoff in handoffs:
        artifact = str(handoff.get("artifact", ""))
        consumer = str(handoff.get("to", ""))
        if artifact and consumer:
            consumers_by_artifact.setdefault(artifact, []).append(consumer)
    return [
        {
            "artifact": str(artifact.get("artifact", "")),
            "producer_unit_id": str(artifact.get("producer", "")),
            "consumer_unit_ids": consumers_by_artifact.get(str(artifact.get("artifact", "")), []),
            "status": str(artifact.get("status", "")),
            "kind": str(artifact.get("kind", "")),
            "path": str(artifact.get("path", "")),
        }
        for artifact in artifacts
        if artifact.get("artifact")
    ]


def build_dependency_view(
    *,
    operator_state: Mapping[str, Any],
    operator_state_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    units = _unit_rows(operator_state)
    artifacts = _artifact_rows(operator_state)
    handoffs = _handoff_rows(operator_state)
    unit_ids = tuple(str(unit.get("id", "")) for unit in units if unit.get("id"))
    upstream, downstream = _adjacency_from_handoffs(unit_ids, handoffs)
    units_by_id = {str(unit.get("id", "")): unit for unit in units if unit.get("id")}
    nodes = _node_rows(
        units=units,
        artifacts=artifacts,
        handoffs=handoffs,
        upstream=upstream,
        downstream=downstream,
    )
    edges = _edge_rows(handoffs=handoffs, units_by_id=units_by_id)
    artifact_flow = _artifact_flow_rows(artifacts=artifacts, handoffs=handoffs)
    source_summary = operator_state.get("summary", {})
    source = operator_state.get("source", {})
    available_artifact_ids = [
        str(artifact.get("artifact", ""))
        for artifact in artifacts
        if artifact.get("status") == "available" and artifact.get("artifact")
    ]
    cross_app_edges = [
        edge for edge in edges if isinstance(edge, dict) and edge.get("cross_app") is True
    ]
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "ready_for_operator_review",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "source": {
            "operator_state_path": str(operator_state_path),
            "operator_state_schema": operator_state.get("schema", ""),
            "operator_state_run_id": operator_state.get("run_id", ""),
            "operator_state_run_status": operator_state.get("run_status", ""),
            "source_real_execution_scope": (
                source_summary.get("source_real_execution_scope", "")
                if isinstance(source_summary, dict)
                else ""
            ),
            "source_dispatch_state_path": source.get("dispatch_state_path", ""),
            "source_dag": source.get("source_dag", ""),
        },
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "cross_app_edge_count": len(cross_app_edges),
            "artifact_flow_count": len(artifact_flow),
            "upstream_dependency_count": sum(len(values) for values in upstream.values()),
            "downstream_dependency_count": sum(len(values) for values in downstream.values()),
            "visible_unit_ids": list(unit_ids),
            "available_artifact_ids": available_artifact_ids,
            "source_real_execution_scope": (
                source_summary.get("source_real_execution_scope", "")
                if isinstance(source_summary, dict)
                else ""
            ),
        },
        "nodes": nodes,
        "edges": edges,
        "adjacency": {
            "upstream_by_unit": upstream,
            "downstream_by_unit": downstream,
        },
        "artifact_flow": artifact_flow,
        "provenance": {
            "projection_mode": "dependency_view_from_operator_state",
            "source_operator_state_schema": operator_state.get("schema", ""),
            "source_operator_state_run_id": operator_state.get("run_id", ""),
            "source_operator_state_path": str(operator_state_path),
        },
    }


def write_dependency_view(path: Path, view: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_dependency_view(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_dependency_view(
    *,
    repo_root: Path,
    output_path: Path,
    operator_state_path: Path | None = None,
    workspace_path: Path | None = None,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> DependencyViewProof:
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser()
    if operator_state_path is None:
        generated_operator_state_path = (
            output_path.parent / "global_pipeline_operator_state.json"
        )
        persist_operator_state(
            repo_root=repo_root,
            output_path=generated_operator_state_path,
            workspace_path=workspace_path
            or (output_path.parent / "global_pipeline_dependency_view_workspace"),
            dag_path=dag_path,
        )
        operator_state_path = generated_operator_state_path

    operator_state = load_operator_state(operator_state_path)
    issues: list[DependencyViewIssue] = []
    view = build_dependency_view(
        operator_state=operator_state,
        operator_state_path=operator_state_path,
        run_id=run_id,
    )
    path = write_dependency_view(output_path, view)
    reloaded = load_dependency_view(path)
    if view != reloaded:
        issues.append(
            _issue(
                "persistence.round_trip",
                "dependency view changed after JSON write/read",
            )
        )
    if view.get("source", {}).get("operator_state_schema") != OPERATOR_STATE_SCHEMA:
        issues.append(
            _issue(
                "source.operator_state_schema",
                "dependency view source is not an operator-state JSON",
            )
        )
    return DependencyViewProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        operator_state_path=str(operator_state_path),
        dependency_view=view,
        reloaded_view=reloaded,
    )


__all__ = [
    "DEFAULT_RUN_ID",
    "PERSISTENCE_FORMAT",
    "SCHEMA",
    "DependencyViewIssue",
    "DependencyViewProof",
    "build_dependency_view",
    "load_dependency_view",
    "persist_dependency_view",
    "write_dependency_view",
]
