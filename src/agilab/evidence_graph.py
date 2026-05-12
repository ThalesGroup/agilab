"""Dependency-free evidence graph exports for AGILAB proof artifacts."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


EVIDENCE_GRAPH_SCHEMA = "agilab.evidence_graph.v1"
EVIDENCE_GRAPH_KIND = "agilab.evidence_graph"


def build_evidence_graph_from_workflow_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic provenance graph from a workflow run manifest."""
    builder = _GraphBuilder()
    manifest_id = _text(manifest.get("manifest_id")) or "workflow-manifest"
    run_id = _text(manifest.get("run_id")) or manifest_id
    status = _text(manifest.get("status")) or "unknown"
    created_at = _text(manifest.get("created_at"))

    manifest_node = f"manifest:{_token(manifest_id)}"
    run_node = f"run:{_token(run_id)}"
    builder.add_node(
        manifest_node,
        "manifest",
        manifest_id,
        {
            "kind": _text(manifest.get("kind")),
            "schema_version": manifest.get("schema_version"),
            "status": status,
            "created_at": created_at,
        },
    )
    builder.add_node(
        run_node,
        "run",
        run_id,
        {
            "status": status,
            "created_at": created_at,
        },
    )
    builder.add_edge(manifest_node, run_node, "describes")

    workflow = _mapping(manifest.get("workflow"))
    workflow_label = _text(workflow.get("dag_path")) or _text(workflow.get("source_type")) or "workflow"
    workflow_node = f"workflow:{_token(workflow_label)}"
    builder.add_node(
        workflow_node,
        "workflow",
        workflow_label,
        {
            "source_type": _text(workflow.get("source_type")),
            "dag_path": _text(workflow.get("dag_path")),
            "unit_count": workflow.get("unit_count", 0),
            "plan_schema": _text(workflow.get("plan_schema")),
        },
    )
    builder.add_edge(run_node, workflow_node, "executes")

    runtime_contract = _mapping(manifest.get("runtime_contract"))
    phase = _text(runtime_contract.get("phase")) or "unknown"
    phase_node = f"phase:{_token(phase)}"
    builder.add_node(
        phase_node,
        "runtime_phase",
        phase,
        {
            "run_status": _text(runtime_contract.get("run_status")),
            "event_count": _int(runtime_contract.get("event_count")),
        },
    )
    builder.add_edge(run_node, phase_node, "has_phase")

    stage_nodes = _add_stage_nodes(builder, workflow_node, manifest)
    artifact_nodes = _add_artifact_nodes(builder, stage_nodes, manifest)
    _add_validation_nodes(builder, manifest_node, run_node, manifest)
    _add_control_nodes(builder, run_node, runtime_contract)
    _add_evidence_artifact_nodes(builder, manifest_node, manifest, artifact_nodes)

    return {
        "schema": EVIDENCE_GRAPH_SCHEMA,
        "kind": EVIDENCE_GRAPH_KIND,
        "graph_id": f"evidence-graph:{manifest_id}",
        "source": {
            "manifest_id": manifest_id,
            "run_id": run_id,
            "status": status,
            "created_at": created_at,
        },
        "summary": builder.summary(),
        "nodes": builder.nodes(),
        "edges": builder.edges(),
    }


def validate_evidence_graph(graph: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the exported graph shape and references."""
    issues: list[str] = []
    if _text(graph.get("schema")) != EVIDENCE_GRAPH_SCHEMA:
        issues.append("evidence graph schema is unsupported")
    if _text(graph.get("kind")) != EVIDENCE_GRAPH_KIND:
        issues.append("evidence graph kind is unsupported")

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_ids: set[str] = set()
    if not isinstance(nodes, list):
        issues.append("evidence graph nodes must be a list")
        nodes = []
    if not isinstance(edges, list):
        issues.append("evidence graph edges must be a list")
        edges = []

    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            issues.append(f"evidence graph node #{index} must be an object")
            continue
        node_id = _text(node.get("id"))
        if not node_id:
            issues.append(f"evidence graph node #{index} id is missing")
            continue
        if node_id in node_ids:
            issues.append(f"evidence graph node id is duplicated: {node_id}")
        node_ids.add(node_id)
        if not _text(node.get("kind")):
            issues.append(f"evidence graph node {node_id} kind is missing")

    for index, edge in enumerate(edges):
        if not isinstance(edge, Mapping):
            issues.append(f"evidence graph edge #{index} must be an object")
            continue
        source = _text(edge.get("source"))
        target = _text(edge.get("target"))
        if not source or not target:
            issues.append(f"evidence graph edge #{index} source/target is missing")
            continue
        if source not in node_ids:
            issues.append(f"evidence graph edge #{index} source is unknown: {source}")
        if target not in node_ids:
            issues.append(f"evidence graph edge #{index} target is unknown: {target}")
        if not _text(edge.get("kind")):
            issues.append(f"evidence graph edge #{index} kind is missing")

    return tuple(issues)


def evidence_graph_summary(graph: Mapping[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_kinds: dict[str, int] = {}
    edge_kinds: dict[str, int] = {}
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, Mapping):
                kind = _text(node.get("kind")) or "unknown"
                node_kinds[kind] = node_kinds.get(kind, 0) + 1
    if isinstance(edges, list):
        for edge in edges:
            if isinstance(edge, Mapping):
                kind = _text(edge.get("kind")) or "unknown"
                edge_kinds[kind] = edge_kinds.get(kind, 0) + 1
    return {
        "node_count": sum(node_kinds.values()),
        "edge_count": sum(edge_kinds.values()),
        "node_kinds": dict(sorted(node_kinds.items())),
        "edge_kinds": dict(sorted(edge_kinds.items())),
    }


def _add_stage_nodes(
    builder: "_GraphBuilder",
    workflow_node: str,
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    stage_nodes: dict[str, str] = {}
    stages = [dict(stage) for stage in _sequence(manifest.get("stages")) if isinstance(stage, Mapping)]
    stages.sort(key=_stage_sort_key)
    for stage in stages:
        stage_id = _text(stage.get("id"))
        if not stage_id:
            continue
        node_id = f"stage:{_token(stage_id)}"
        stage_nodes[stage_id] = node_id
        builder.add_node(
            node_id,
            "stage",
            stage_id,
            {
                "app": _text(stage.get("app")),
                "status": _text(stage.get("status")),
                "order_index": stage.get("order_index"),
                "execution_contract_sha256": _text(stage.get("execution_contract_sha256")),
            },
        )
        builder.add_edge(workflow_node, node_id, "contains_stage")

    for stage in stages:
        stage_id = _text(stage.get("id"))
        target = stage_nodes.get(stage_id)
        if not target:
            continue
        for dependency in _sequence(stage.get("depends_on")):
            dependency_id = _text(dependency)
            source = stage_nodes.get(dependency_id)
            if source:
                builder.add_edge(source, target, "precedes")
    return stage_nodes


def _add_artifact_nodes(
    builder: "_GraphBuilder",
    stage_nodes: Mapping[str, str],
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    artifact_nodes: dict[str, str] = {}
    contracts = _mapping(manifest.get("artifact_contracts"))
    produced = [dict(item) for item in _sequence(contracts.get("produced")) if isinstance(item, Mapping)]
    consumed = [dict(item) for item in _sequence(contracts.get("consumed")) if isinstance(item, Mapping)]

    for artifact in sorted(produced, key=lambda item: (_text(item.get("artifact")), _text(item.get("producer")))):
        artifact_id = _text(artifact.get("artifact"))
        if not artifact_id:
            continue
        node_id = _artifact_node_id(artifact_id)
        artifact_nodes[artifact_id] = node_id
        builder.add_node(
            node_id,
            "artifact",
            artifact_id,
            {
                "kind": _text(artifact.get("kind")),
                "path": _text(artifact.get("path")),
                "status": _text(artifact.get("status")),
                "app": _text(artifact.get("app")),
            },
        )
        producer = stage_nodes.get(_text(artifact.get("producer")))
        if producer:
            builder.add_edge(producer, node_id, "produced")

    for artifact in sorted(consumed, key=lambda item: (_text(item.get("artifact")), _text(item.get("consumer")))):
        artifact_id = _text(artifact.get("artifact"))
        if not artifact_id:
            continue
        node_id = artifact_nodes.setdefault(artifact_id, _artifact_node_id(artifact_id))
        builder.add_node(
            node_id,
            "artifact",
            artifact_id,
            {
                "path": _text(artifact.get("source_path")),
                "app": _text(artifact.get("from_app")),
            },
        )
        consumer = stage_nodes.get(_text(artifact.get("consumer")))
        if consumer:
            builder.add_edge(node_id, consumer, "consumed_by")
    return artifact_nodes


def _add_validation_nodes(
    builder: "_GraphBuilder",
    manifest_node: str,
    run_node: str,
    manifest: Mapping[str, Any],
) -> None:
    validations = [dict(item) for item in _sequence(manifest.get("validations")) if isinstance(item, Mapping)]
    validations.sort(key=lambda item: _text(item.get("id")) or _text(item.get("label")))
    for validation in validations:
        validation_id = _text(validation.get("id")) or _text(validation.get("label")) or "validation"
        node_id = f"validation:{_token(validation_id)}"
        builder.add_node(
            node_id,
            "validation",
            validation_id,
            {
                "status": _text(validation.get("status")) or "unknown",
                "summary": _text(validation.get("summary")),
            },
        )
        builder.add_edge(manifest_node, node_id, "has_validation")
        builder.add_edge(node_id, run_node, "validates")


def _add_control_nodes(
    builder: "_GraphBuilder",
    run_node: str,
    runtime_contract: Mapping[str, Any],
) -> None:
    controls = [dict(item) for item in _sequence(runtime_contract.get("controls")) if isinstance(item, Mapping)]
    controls.sort(key=lambda item: _text(item.get("id")) or _text(item.get("label")))
    for control in controls:
        control_id = _text(control.get("id")) or _text(control.get("label"))
        if not control_id:
            continue
        node_id = f"control:{_token(control_id)}"
        builder.add_node(
            node_id,
            "runtime_control",
            _text(control.get("label")) or control_id,
            {
                "enabled": bool(control.get("enabled")),
                "reason": _text(control.get("reason")),
            },
        )
        builder.add_edge(run_node, node_id, "offers_control")


def _add_evidence_artifact_nodes(
    builder: "_GraphBuilder",
    manifest_node: str,
    manifest: Mapping[str, Any],
    artifact_nodes: Mapping[str, str],
) -> None:
    artifacts = [dict(item) for item in _sequence(manifest.get("artifacts")) if isinstance(item, Mapping)]
    evidence_ledger = _mapping(manifest.get("evidence_ledger"))
    evidence_graph = _mapping(manifest.get("evidence_graph"))
    artifacts.extend(
        item
        for item in (
            {
                "name": "evidence_ledger",
                "kind": _text(evidence_ledger.get("kind")),
                "path": _text(evidence_ledger.get("path")),
            },
            {
                "name": "evidence_graph",
                "kind": _text(evidence_graph.get("kind")),
                "path": _text(evidence_graph.get("path")),
            },
        )
        if item["kind"] or item["path"]
    )
    for artifact in sorted(artifacts, key=lambda item: (_text(item.get("kind")), _text(item.get("name")))):
        name = _text(artifact.get("name")) or _text(artifact.get("path")) or "artifact"
        node_id = artifact_nodes.get(name, f"evidence_artifact:{_token(name)}")
        builder.add_node(
            node_id,
            "evidence_artifact",
            name,
            {
                "kind": _text(artifact.get("kind")),
                "path": _text(artifact.get("path")),
                "exists": artifact.get("exists"),
                "sha256": _text(artifact.get("sha256")),
            },
        )
        builder.add_edge(manifest_node, node_id, "references_artifact")


def _artifact_node_id(artifact_id: str) -> str:
    return f"artifact:{_token(artifact_id)}"


def _stage_sort_key(stage: Mapping[str, Any]) -> tuple[int, str]:
    try:
        order_index = int(stage.get("order_index", 999_999))
    except (TypeError, ValueError):
        order_index = 999_999
    return order_index, _text(stage.get("id"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _token(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-")
    return safe or "item"


class _GraphBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: set[tuple[str, str, str]] = set()

    def add_node(self, node_id: str, kind: str, label: str, properties: Mapping[str, Any] | None = None) -> None:
        current = self._nodes.get(node_id)
        clean_properties = _clean_mapping(properties or {})
        if current is None:
            self._nodes[node_id] = {
                "id": node_id,
                "kind": kind,
                "label": label or node_id,
                "properties": clean_properties,
            }
            return
        merged = dict(current.get("properties", {}))
        merged.update({key: value for key, value in clean_properties.items() if value not in ("", None, [], {})})
        current["properties"] = merged

    def add_edge(self, source: str, target: str, kind: str) -> None:
        if source and target and kind:
            self._edges.add((source, target, kind))

    def nodes(self) -> list[dict[str, Any]]:
        return [self._nodes[node_id] for node_id in sorted(self._nodes)]

    def edges(self) -> list[dict[str, str]]:
        return [
            {"source": source, "target": target, "kind": kind}
            for source, target, kind in sorted(self._edges)
        ]

    def summary(self) -> dict[str, Any]:
        node_kinds: dict[str, int] = {}
        edge_kinds: dict[str, int] = {}
        for node in self._nodes.values():
            kind = _text(node.get("kind")) or "unknown"
            node_kinds[kind] = node_kinds.get(kind, 0) + 1
        for _source, _target, kind in self._edges:
            edge_kinds[kind] = edge_kinds.get(kind, 0) + 1
        return {
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "node_kinds": dict(sorted(node_kinds.items())),
            "edge_kinds": dict(sorted(edge_kinds.items())),
        }


def _clean_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if value in ("", None, [], {}):
            continue
        clean[str(key)] = value
    return clean
