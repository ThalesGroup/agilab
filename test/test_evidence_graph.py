from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("src/agilab/evidence_graph.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("evidence_graph_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sample_manifest() -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "agilab.workflow_run_manifest",
        "manifest_id": "demo-run-abc123",
        "run_id": "demo-run",
        "status": "pass",
        "created_at": "2026-05-12T08:01:00Z",
        "workflow": {
            "source_type": "multi_app_dag",
            "dag_path": "demo/dag.json",
            "unit_count": 2,
            "plan_schema": "agilab.multi_app_dag.v1",
        },
        "runtime_contract": {
            "phase": "completed",
            "event_count": 2,
            "controls": [
                {"id": "stop", "label": "Stop", "enabled": False, "reason": "workflow is completed"},
            ],
        },
        "artifact_contracts": {
            "produced": [
                {
                    "artifact": "features",
                    "producer": "load",
                    "app": "demo_project",
                    "kind": "table",
                    "path": "features.json",
                }
            ],
            "consumed": [
                {
                    "artifact": "features",
                    "consumer": "train",
                    "from": "load",
                    "from_app": "demo_project",
                    "source_path": "features.json",
                }
            ],
        },
        "stages": [
            {
                "id": "train",
                "app": "demo_project",
                "status": "completed",
                "order_index": 1,
                "depends_on": ["load"],
                "produces": [],
            },
            {
                "id": "load",
                "app": "demo_project",
                "status": "completed",
                "order_index": 0,
                "depends_on": [],
                "produces": ["features"],
            },
        ],
        "validations": [
            {"id": "run_outcome", "status": "pass", "summary": "workflow completed all stages"},
        ],
        "evidence_ledger": {
            "kind": "agilab.evidence_ledger",
            "path": "/tmp/evidence_ledger.json",
        },
        "evidence_graph": {
            "kind": "agilab.evidence_graph",
            "path": "/tmp/evidence_graph.json",
        },
    }


def test_evidence_graph_builds_context_edges_from_workflow_manifest() -> None:
    module = _load_module()

    graph = module.build_evidence_graph_from_workflow_manifest(_sample_manifest())

    assert module.validate_evidence_graph(graph) == ()
    assert graph == module.build_evidence_graph_from_workflow_manifest(_sample_manifest())
    assert graph["schema"] == module.EVIDENCE_GRAPH_SCHEMA
    assert graph["kind"] == module.EVIDENCE_GRAPH_KIND
    assert graph["summary"]["node_kinds"]["stage"] == 2
    assert graph["summary"]["node_kinds"]["artifact"] == 1
    assert graph["summary"]["node_kinds"]["validation"] == 1
    assert {"source": "stage:load", "target": "stage:train", "kind": "precedes"} in graph["edges"]
    assert {"source": "stage:load", "target": "artifact:features", "kind": "produced"} in graph["edges"]
    assert {"source": "artifact:features", "target": "stage:train", "kind": "consumed_by"} in graph["edges"]
    assert {"source": "validation:run_outcome", "target": "run:demo-run", "kind": "validates"} in graph["edges"]


def test_evidence_graph_validation_rejects_dangling_edges() -> None:
    module = _load_module()
    graph = {
        "schema": module.EVIDENCE_GRAPH_SCHEMA,
        "kind": module.EVIDENCE_GRAPH_KIND,
        "nodes": [{"id": "run:demo", "kind": "run", "label": "demo"}],
        "edges": [{"source": "run:demo", "target": "missing:node", "kind": "references"}],
    }

    assert module.validate_evidence_graph(graph) == (
        "evidence graph edge #0 target is unknown: missing:node",
    )


def test_evidence_graph_validation_reports_shape_and_reference_errors() -> None:
    module = _load_module()

    graph = {
        "schema": "wrong",
        "kind": "wrong",
        "nodes": [
            "bad-node",
            {},
            {"id": "run:demo"},
            {"id": "run:demo", "kind": "run"},
            {"id": "run:demo", "kind": "run"},
        ],
        "edges": [
            "bad-edge",
            {},
            {"source": "missing:source", "target": "run:demo"},
            {"source": "run:demo", "target": "missing:target", "kind": ""},
        ],
    }

    issues = module.validate_evidence_graph(graph)

    assert "evidence graph schema is unsupported" in issues
    assert "evidence graph kind is unsupported" in issues
    assert "evidence graph node #0 must be an object" in issues
    assert "evidence graph node #1 id is missing" in issues
    assert "evidence graph node run:demo kind is missing" in issues
    assert "evidence graph node id is duplicated: run:demo" in issues
    assert "evidence graph edge #0 must be an object" in issues
    assert "evidence graph edge #1 source/target is missing" in issues
    assert "evidence graph edge #2 source is unknown: missing:source" in issues
    assert "evidence graph edge #2 kind is missing" in issues
    assert "evidence graph edge #3 target is unknown: missing:target" in issues
    assert "evidence graph edge #3 kind is missing" in issues
    assert module.validate_evidence_graph({"nodes": "bad", "edges": "bad"}) == (
        "evidence graph schema is unsupported",
        "evidence graph kind is unsupported",
        "evidence graph nodes must be a list",
        "evidence graph edges must be a list",
    )


def test_evidence_graph_summary_and_messy_manifest_edge_cases() -> None:
    module = _load_module()

    assert module.evidence_graph_summary(
        {
            "nodes": [
                {"kind": "run"},
                {"kind": ""},
                "skip",
            ],
            "edges": [
                {"kind": "references"},
                {"kind": ""},
                "skip",
            ],
        }
    ) == {
        "node_count": 2,
        "edge_count": 2,
        "node_kinds": {"run": 1, "unknown": 1},
        "edge_kinds": {"references": 1, "unknown": 1},
    }

    messy_manifest = {
        "manifest_id": "demo manifest!",
        "run_id": "",
        "status": "",
        "workflow": {"source_type": "generated"},
        "runtime_contract": {
            "phase": "",
            "event_count": "bad",
            "controls": [
                {"label": "", "enabled": True},
                {"label": "Retry", "enabled": True, "reason": ""},
            ],
        },
        "stages": [
            {"id": "", "order_index": 0},
            {"id": "late", "order_index": "bad", "depends_on": ["missing"]},
            {"id": "first", "order_index": 1, "depends_on": ["late"]},
        ],
        "artifact_contracts": {
            "produced": [
                {"artifact": "", "producer": "first"},
                {"artifact": "loose", "producer": "missing"},
            ],
            "consumed": [
                {"artifact": "", "consumer": "first"},
                {"artifact": "external", "consumer": "missing", "source_path": "input.csv"},
            ],
        },
        "validations": [
            {"label": "", "status": "", "summary": ""},
            {"label": "Smoke", "status": "", "summary": "ok"},
        ],
        "artifacts": [
            {"name": "loose", "kind": "table", "path": "loose.csv", "exists": False, "sha256": ""},
            {"path": "unnamed.txt", "kind": "", "exists": True, "sha256": "abc"},
        ],
        "evidence_ledger": {"path": "ledger.json"},
        "evidence_graph": {"kind": "graph"},
    }

    graph = module.build_evidence_graph_from_workflow_manifest(messy_manifest)
    assert module.validate_evidence_graph(graph) == ()
    assert graph["source"]["run_id"] == "demo manifest!"
    assert graph["source"]["status"] == "unknown"
    assert {"source": "stage:late", "target": "stage:first", "kind": "precedes"} in graph["edges"]
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    assert node_by_id["phase:unknown"]["properties"] == {"event_count": 0}
    assert node_by_id["control:Retry"]["properties"] == {"enabled": True}
    assert node_by_id["validation:validation"]["properties"] == {"status": "unknown"}
    assert node_by_id["artifact:loose"]["kind"] == "artifact"
    assert node_by_id["artifact:loose"]["properties"] == {"kind": "table", "path": "loose.csv", "exists": False}
    assert node_by_id["evidence_artifact:unnamed.txt"]["properties"] == {
        "path": "unnamed.txt",
        "exists": True,
        "sha256": "abc",
    }
    assert node_by_id["evidence_artifact:evidence_ledger"]["properties"] == {"path": "ledger.json"}
    assert node_by_id["evidence_artifact:evidence_graph"]["properties"] == {"kind": "graph"}

    builder = module._GraphBuilder()
    builder.add_node("n", "kind", "", {"drop": "", "keep": "a"})
    builder.add_node("n", "kind", "ignored", {"drop": [], "keep": "b", "other": 1})
    builder.add_edge("", "n", "bad")
    builder.add_edge("n", "n", "self")
    assert builder.nodes() == [{"id": "n", "kind": "kind", "label": "n", "properties": {"keep": "b", "other": 1}}]
    assert builder.edges() == [{"source": "n", "target": "n", "kind": "self"}]
    assert module._mapping("bad") == {}
    assert module._sequence("bad") == ()
    assert module._int(object()) == 0
    assert module._token("   ") == "item"
