# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Validation helpers for AGILAB multi-app DAG contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "agilab.multi_app_dag.v1"
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class DagIssue:
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
class MultiAppDagValidation:
    ok: bool
    issues: tuple[DagIssue, ...]
    node_count: int
    edge_count: int
    app_count: int
    cross_app_edge_count: int
    execution_order: tuple[str, ...]
    artifact_handoffs: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "app_count": self.app_count,
            "cross_app_edge_count": self.cross_app_edge_count,
            "execution_order": list(self.execution_order),
            "artifact_handoffs": list(self.artifact_handoffs),
        }


def load_multi_app_dag(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"multi-app DAG must be a JSON object: {path}")
    return payload


def builtin_app_names(repo_root: Path) -> set[str]:
    builtin_root = repo_root / "src" / "agilab" / "apps" / "builtin"
    return {
        path.name
        for path in builtin_root.glob("*_project")
        if (path / "pyproject.toml").is_file()
    }


def _issue(location: str, message: str) -> DagIssue:
    return DagIssue(level="error", location=location, message=message)


def _string_field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return str(value).strip() if isinstance(value, str) else ""


def _artifact_ids(rows: Any) -> set[str]:
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("id")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }


def _artifact_path_by_id(rows: Any) -> dict[str, str]:
    if not isinstance(rows, list):
        return {}
    paths: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        artifact_id = str(row.get("id", "")).strip()
        path = str(row.get("path", "")).strip()
        if artifact_id:
            paths[artifact_id] = path
    return paths


def _validate_artifact_rows(rows: Any, *, location: str) -> list[DagIssue]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        return [_issue(location, "artifact entries must be a list")]

    issues: list[DagIssue] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        row_location = f"{location}[{index}]"
        if not isinstance(row, dict):
            issues.append(_issue(row_location, "artifact entry must be an object"))
            continue
        artifact_id = _string_field(row, "id")
        if not artifact_id:
            issues.append(_issue(row_location, "artifact id is required"))
        elif artifact_id in seen:
            issues.append(_issue(row_location, f"duplicate artifact id {artifact_id!r}"))
        seen.add(artifact_id)
        artifact_path = _string_field(row, "path")
        if not artifact_path:
            issues.append(_issue(row_location, "artifact path is required"))
        elif Path(artifact_path).is_absolute() or ".." in Path(artifact_path).parts:
            issues.append(_issue(row_location, "artifact path must be portable and relative"))
    return issues


def _topological_order(node_ids: Sequence[str], edges: Sequence[Mapping[str, Any]]) -> tuple[list[str], bool]:
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source = str(edge.get("from", "")).strip()
        target = str(edge.get("to", "")).strip()
        if source not in incoming or target not in incoming:
            continue
        outgoing[source].append(target)
        incoming[target] += 1

    ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in sorted(outgoing[node_id]):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort()

    return order, len(order) == len(node_ids)


def validate_multi_app_dag(payload: Mapping[str, Any], *, repo_root: Path) -> MultiAppDagValidation:
    issues: list[DagIssue] = []
    schema = payload.get("schema")
    if schema != SCHEMA:
        issues.append(_issue("schema", f"unsupported schema {schema!r}; expected {SCHEMA!r}"))

    dag_id = _string_field(payload, "dag_id")
    if not dag_id:
        issues.append(_issue("dag_id", "dag_id is required"))

    nodes_payload = payload.get("nodes")
    edges_payload = payload.get("edges", [])
    if not isinstance(nodes_payload, list) or not nodes_payload:
        issues.append(_issue("nodes", "nodes must be a non-empty list"))
        nodes_payload = []
    if not isinstance(edges_payload, list):
        issues.append(_issue("edges", "edges must be a list"))
        edges_payload = []

    available_apps = builtin_app_names(repo_root)
    nodes_by_id: dict[str, Mapping[str, Any]] = {}
    for index, node in enumerate(nodes_payload):
        location = f"nodes[{index}]"
        if not isinstance(node, dict):
            issues.append(_issue(location, "node must be an object"))
            continue
        node_id = _string_field(node, "id")
        app = _string_field(node, "app")
        if not node_id:
            issues.append(_issue(location, "node id is required"))
        elif not NODE_ID_PATTERN.match(node_id):
            issues.append(_issue(location, f"node id {node_id!r} is not portable"))
        elif node_id in nodes_by_id:
            issues.append(_issue(location, f"duplicate node id {node_id!r}"))
        else:
            nodes_by_id[node_id] = node
        if not app:
            issues.append(_issue(location, "node app is required"))
        elif app not in available_apps:
            issues.append(_issue(location, f"node app {app!r} is not a checked-in built-in app"))
        issues.extend(_validate_artifact_rows(node.get("produces"), location=f"{location}.produces"))
        issues.extend(_validate_artifact_rows(node.get("consumes"), location=f"{location}.consumes"))

    edge_rows: list[Mapping[str, Any]] = [
        edge for edge in edges_payload if isinstance(edge, dict)
    ]
    for index, edge in enumerate(edges_payload):
        location = f"edges[{index}]"
        if not isinstance(edge, dict):
            issues.append(_issue(location, "edge must be an object"))
            continue
        source_id = _string_field(edge, "from")
        target_id = _string_field(edge, "to")
        artifact_id = _string_field(edge, "artifact")
        if source_id not in nodes_by_id:
            issues.append(_issue(location, f"edge source {source_id!r} does not match a node"))
        if target_id not in nodes_by_id:
            issues.append(_issue(location, f"edge target {target_id!r} does not match a node"))
        if source_id and source_id == target_id:
            issues.append(_issue(location, "edge cannot depend on itself"))
        if not artifact_id:
            issues.append(_issue(location, "edge artifact is required"))
            continue
        source_node = nodes_by_id.get(source_id)
        target_node = nodes_by_id.get(target_id)
        if source_node and artifact_id not in _artifact_ids(source_node.get("produces")):
            issues.append(_issue(location, f"source node does not produce artifact {artifact_id!r}"))
        target_consumes = _artifact_ids(target_node.get("consumes")) if target_node else set()
        if target_node and target_consumes and artifact_id not in target_consumes:
            issues.append(_issue(location, f"target node does not consume artifact {artifact_id!r}"))

    execution_order, acyclic = _topological_order(list(nodes_by_id), edge_rows)
    if nodes_by_id and not acyclic:
        issues.append(_issue("edges", "dependency graph contains a cycle"))

    apps = {
        _string_field(node, "app")
        for node in nodes_by_id.values()
        if _string_field(node, "app")
    }
    cross_app_edge_count = 0
    artifact_handoffs: list[dict[str, str]] = []
    for edge in edge_rows:
        source_node = nodes_by_id.get(_string_field(edge, "from"))
        target_node = nodes_by_id.get(_string_field(edge, "to"))
        if not source_node or not target_node:
            continue
        source_app = _string_field(source_node, "app")
        target_app = _string_field(target_node, "app")
        artifact_id = _string_field(edge, "artifact")
        source_paths = _artifact_path_by_id(source_node.get("produces"))
        if source_app != target_app:
            cross_app_edge_count += 1
        artifact_handoffs.append(
            {
                "from": _string_field(edge, "from"),
                "to": _string_field(edge, "to"),
                "from_app": source_app,
                "to_app": target_app,
                "artifact": artifact_id,
                "source_path": source_paths.get(artifact_id, ""),
                "handoff": _string_field(edge, "handoff"),
            }
        )

    if len(apps) < 2:
        issues.append(_issue("nodes", "multi-app DAG must reference at least two apps"))
    if edge_rows and cross_app_edge_count == 0:
        issues.append(_issue("edges", "DAG must include at least one cross-app edge"))

    return MultiAppDagValidation(
        ok=not issues,
        issues=tuple(issues),
        node_count=len(nodes_by_id),
        edge_count=len(edge_rows),
        app_count=len(apps),
        cross_app_edge_count=cross_app_edge_count,
        execution_order=tuple(execution_order),
        artifact_handoffs=tuple(artifact_handoffs),
    )


__all__ = [
    "SCHEMA",
    "DagIssue",
    "MultiAppDagValidation",
    "builtin_app_names",
    "load_multi_app_dag",
    "validate_multi_app_dag",
]
