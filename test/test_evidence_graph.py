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
