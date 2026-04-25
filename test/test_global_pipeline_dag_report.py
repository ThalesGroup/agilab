from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_dag_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_dag.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_dag_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_dag_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_global_pipeline_dag_report_builds_checked_in_graph() -> None:
    module = _load_report_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["report"] == "Global pipeline DAG report"
    assert report["status"] == "pass"
    assert report["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert report["summary"]["runner_status"] == "not_executed"
    assert report["summary"]["app_node_count"] == 2
    assert report["summary"]["app_step_node_count"] == 8
    assert report["summary"]["local_pipeline_edge_count"] == 6
    assert report["summary"]["cross_app_edge_count"] == 1
    assert report["summary"]["global_node_count"] == 10
    assert report["summary"]["global_edge_count"] == 7
    assert report["summary"]["execution_order"] == ["queue_baseline", "relay_followup"]
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_dag_source_contract",
        "global_pipeline_dag_app_views",
        "global_pipeline_dag_graph_shape",
        "global_pipeline_dag_artifact_edge",
        "global_pipeline_dag_docs_reference",
    }

    edge = next(edge for edge in report["graph"]["edges"] if edge["kind"] == "artifact_handoff")
    assert edge == {
        "artifact": "queue_metrics",
        "from": "queue_baseline",
        "from_app": "uav_queue_project",
        "handoff": "Use base queue summary metrics as the relay scenario context.",
        "kind": "artifact_handoff",
        "source": "docs/source/data/multi_app_dag_sample.json",
        "to": "relay_followup",
        "to_app": "uav_relay_queue_project",
    }


def test_parse_pipeline_view_dot_expands_chained_edges() -> None:
    module = _load_core_module()

    parsed = module.parse_pipeline_view_dot(
        """
        digraph demo {
          start [label="Start"];
          middle [label="Middle\\nstep"];
          finish [label="Finish"];
          start -> middle -> finish;
        }
        """
    )

    assert parsed["nodes"] == (
        {"id": "finish", "label": "Finish"},
        {"id": "middle", "label": "Middle | step"},
        {"id": "start", "label": "Start"},
    )
    assert parsed["edges"] == (
        {"from": "start", "to": "middle"},
        {"from": "middle", "to": "finish"},
    )


def test_global_pipeline_dag_reports_missing_pipeline_view(tmp_path: Path) -> None:
    module = _load_core_module()
    dag_path = tmp_path / "dag.json"
    dag_path.write_text(
        json.dumps(
            {
                "schema": "agilab.multi_app_dag.v1",
                "dag_id": "missing-view",
                "nodes": [
                    {
                        "id": "a",
                        "app": "uav_queue_project",
                        "produces": [{"id": "a_out", "path": "a.json"}],
                    },
                    {
                        "id": "b",
                        "app": "uav_relay_queue_project",
                        "consumes": [{"id": "a_out", "path": "a.json"}],
                    },
                ],
                "edges": [{"from": "a", "to": "b", "artifact": "a_out"}],
            }
        ),
        encoding="utf-8",
    )
    for app in ("uav_queue_project", "uav_relay_queue_project"):
        app_root = tmp_path / "src" / "agilab" / "apps" / "builtin" / app
        app_root.mkdir(parents=True)
        (app_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "agilab" / "apps" / "builtin" / "uav_queue_project" / "pipeline_view.dot").write_text(
        'digraph demo { start [label="Start"]; finish [label="Finish"]; start -> finish; }\n',
        encoding="utf-8",
    )

    graph = module.build_global_pipeline_dag(repo_root=tmp_path, dag_path=dag_path)

    assert graph.ok is False
    assert {
        issue.message
        for issue in graph.issues
    } >= {"app 'uav_relay_queue_project' does not expose pipeline_view.dot"}
