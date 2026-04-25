# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Read-only assembly helpers for AGILAB global pipeline DAG evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agilab.multi_app_dag import load_multi_app_dag, validate_multi_app_dag


SCHEMA = "agilab.global_pipeline_dag.v1"
DEFAULT_DAG_RELATIVE_PATH = Path("docs/source/data/multi_app_dag_sample.json")
PIPELINE_VIEW_RELATIVE_PATH = Path("pipeline_view.dot")
DOT_NODE_PATTERN = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*label="([^"]*)"', re.MULTILINE)


@dataclass(frozen=True)
class GlobalPipelineIssue:
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
class AppPipelineView:
    app: str
    dag_node: str
    path: str
    local_nodes: tuple[dict[str, str], ...]
    local_edges: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "dag_node": self.dag_node,
            "path": self.path,
            "local_node_count": len(self.local_nodes),
            "local_edge_count": len(self.local_edges),
            "local_nodes": list(self.local_nodes),
            "local_edges": list(self.local_edges),
        }


@dataclass(frozen=True)
class GlobalPipelineDag:
    ok: bool
    issues: tuple[GlobalPipelineIssue, ...]
    dag_path: str
    schema: str
    runner_status: str
    execution_order: tuple[str, ...]
    nodes: tuple[dict[str, str], ...]
    edges: tuple[dict[str, str], ...]
    app_pipeline_views: tuple[AppPipelineView, ...]
    artifact_handoffs: tuple[dict[str, str], ...]

    @property
    def app_node_count(self) -> int:
        return sum(1 for node in self.nodes if node.get("kind") == "app")

    @property
    def app_step_node_count(self) -> int:
        return sum(1 for node in self.nodes if node.get("kind") == "app_step")

    @property
    def local_pipeline_edge_count(self) -> int:
        return sum(1 for edge in self.edges if edge.get("kind") == "app_pipeline")

    @property
    def cross_app_edge_count(self) -> int:
        return sum(1 for edge in self.edges if edge.get("kind") == "artifact_handoff")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "dag_path": self.dag_path,
            "schema": self.schema,
            "runner_status": self.runner_status,
            "execution_order": list(self.execution_order),
            "app_node_count": self.app_node_count,
            "app_step_node_count": self.app_step_node_count,
            "local_pipeline_edge_count": self.local_pipeline_edge_count,
            "cross_app_edge_count": self.cross_app_edge_count,
            "global_node_count": len(self.nodes),
            "global_edge_count": len(self.edges),
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "app_pipeline_views": [view.as_dict() for view in self.app_pipeline_views],
            "artifact_handoffs": list(self.artifact_handoffs),
        }


def _issue(location: str, message: str) -> GlobalPipelineIssue:
    return GlobalPipelineIssue(level="error", location=location, message=message)


def _string_field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return str(value).strip() if isinstance(value, str) else ""


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _clean_dot_label(label: str) -> str:
    return " | ".join(part.strip() for part in label.replace("\\n", "\n").splitlines() if part.strip())


def parse_pipeline_view_dot(dot_text: str) -> dict[str, tuple[dict[str, str], ...]]:
    labels = {
        match.group(1): _clean_dot_label(match.group(2))
        for match in DOT_NODE_PATTERN.finditer(dot_text)
        if match.group(1) not in {"graph", "node", "edge"}
    }
    edge_pairs: list[tuple[str, str]] = []
    statements = dot_text.replace("{", ";").replace("}", ";").split(";")
    for raw_statement in statements:
        statement = raw_statement.strip()
        if "->" not in statement:
            continue
        chain = statement.split("[", 1)[0].strip()
        parts = [part.strip() for part in chain.split("->") if part.strip()]
        for source, target in zip(parts, parts[1:]):
            edge_pairs.append((source, target))
            labels.setdefault(source, source)
            labels.setdefault(target, target)

    nodes = tuple(
        {"id": node_id, "label": labels[node_id]}
        for node_id in sorted(labels)
    )
    edges = tuple(
        {"from": source, "to": target}
        for source, target in edge_pairs
    )
    return {"nodes": nodes, "edges": edges}


def _load_app_pipeline_view(
    *,
    repo_root: Path,
    app: str,
    dag_node: str,
) -> tuple[AppPipelineView | None, tuple[GlobalPipelineIssue, ...]]:
    path = repo_root / "src" / "agilab" / "apps" / "builtin" / app / PIPELINE_VIEW_RELATIVE_PATH
    location = f"pipeline_views.{dag_node}"
    if not path.is_file():
        return None, (_issue(location, f"app {app!r} does not expose pipeline_view.dot"),)

    parsed = parse_pipeline_view_dot(path.read_text(encoding="utf-8"))
    local_nodes = parsed["nodes"]
    local_edges = parsed["edges"]
    issues: list[GlobalPipelineIssue] = []
    if not local_nodes:
        issues.append(_issue(location, f"app {app!r} pipeline_view.dot has no labeled nodes"))
    if not local_edges:
        issues.append(_issue(location, f"app {app!r} pipeline_view.dot has no edges"))

    return (
        AppPipelineView(
            app=app,
            dag_node=dag_node,
            path=_relative(path, repo_root),
            local_nodes=local_nodes,
            local_edges=local_edges,
        ),
        tuple(issues),
    )


def _node_rows(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = payload.get("nodes")
    if not isinstance(rows, list):
        return {}
    return {
        _string_field(row, "id"): row
        for row in rows
        if isinstance(row, dict) and _string_field(row, "id")
    }


def _edge_rows(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    rows = payload.get("edges")
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def build_global_pipeline_dag(
    *,
    repo_root: Path,
    dag_path: Path | None = None,
) -> GlobalPipelineDag:
    repo_root = repo_root.resolve()
    dag_path = (dag_path or (repo_root / DEFAULT_DAG_RELATIVE_PATH)).expanduser()
    if not dag_path.is_absolute():
        dag_path = repo_root / dag_path

    issues: list[GlobalPipelineIssue] = []
    payload = load_multi_app_dag(dag_path)
    validation = validate_multi_app_dag(payload, repo_root=repo_root)
    for issue in validation.issues:
        issues.append(_issue(f"multi_app_dag.{issue.location}", issue.message))

    rows_by_id = _node_rows(payload)
    execution_order = validation.execution_order or tuple(rows_by_id)
    nodes: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []
    views: list[AppPipelineView] = []

    for dag_node in execution_order:
        row = rows_by_id.get(dag_node)
        if row is None:
            continue
        app = _string_field(row, "app")
        nodes.append(
            {
                "id": dag_node,
                "kind": "app",
                "app": app,
                "label": _string_field(row, "purpose") or app,
                "runner_status": "not_executed",
            }
        )
        view, view_issues = _load_app_pipeline_view(
            repo_root=repo_root,
            app=app,
            dag_node=dag_node,
        )
        issues.extend(view_issues)
        if view is None:
            continue
        views.append(view)
        for local_node in view.local_nodes:
            local_id = local_node["id"]
            nodes.append(
                {
                    "id": f"{dag_node}.{local_id}",
                    "kind": "app_step",
                    "app": app,
                    "dag_node": dag_node,
                    "step": local_id,
                    "label": local_node["label"],
                    "source": view.path,
                }
            )
        for local_edge in view.local_edges:
            edges.append(
                {
                    "from": f"{dag_node}.{local_edge['from']}",
                    "to": f"{dag_node}.{local_edge['to']}",
                    "kind": "app_pipeline",
                    "app": app,
                    "dag_node": dag_node,
                    "source": view.path,
                }
            )

    for edge in _edge_rows(payload):
        source = _string_field(edge, "from")
        target = _string_field(edge, "to")
        source_row = rows_by_id.get(source, {})
        target_row = rows_by_id.get(target, {})
        edges.append(
            {
                "from": source,
                "to": target,
                "kind": "artifact_handoff",
                "from_app": _string_field(source_row, "app"),
                "to_app": _string_field(target_row, "app"),
                "artifact": _string_field(edge, "artifact"),
                "handoff": _string_field(edge, "handoff"),
                "source": _relative(dag_path, repo_root),
            }
        )

    return GlobalPipelineDag(
        ok=not issues,
        issues=tuple(issues),
        dag_path=_relative(dag_path, repo_root),
        schema=SCHEMA,
        runner_status="not_executed",
        execution_order=tuple(execution_order),
        nodes=tuple(nodes),
        edges=tuple(edges),
        app_pipeline_views=tuple(views),
        artifact_handoffs=validation.artifact_handoffs,
    )


__all__ = [
    "SCHEMA",
    "AppPipelineView",
    "GlobalPipelineDag",
    "GlobalPipelineIssue",
    "build_global_pipeline_dag",
    "parse_pipeline_view_dot",
]
