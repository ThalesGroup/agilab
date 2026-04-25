from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_dependency_view_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_dependency_view.py").resolve()
OPERATOR_CORE_PATH = Path("src/agilab/global_pipeline_operator_state.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dependency_view_report_projects_cross_app_adjacency(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_dependency_view_report_test_module")
    output_path = tmp_path / "dependency_view.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline dependency view report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_dependency_view.v1"
    assert report["summary"]["run_status"] == "ready_for_operator_review"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["node_count"] == 2
    assert report["summary"]["edge_count"] == 1
    assert report["summary"]["cross_app_edge_count"] == 1
    assert report["summary"]["upstream_dependency_count"] == 1
    assert report["summary"]["downstream_dependency_count"] == 1
    assert report["summary"]["visible_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_dependency_view_schema",
        "global_pipeline_dependency_view_nodes",
        "global_pipeline_dependency_view_cross_app_edge",
        "global_pipeline_dependency_view_artifact_flow",
        "global_pipeline_dependency_view_operator_linkage",
        "global_pipeline_dependency_view_persistence",
        "global_pipeline_dependency_view_docs_reference",
    }


def test_dependency_view_reads_existing_operator_state(tmp_path: Path) -> None:
    operator_module = _load_module(
        OPERATOR_CORE_PATH,
        "global_pipeline_operator_state_for_dependency_view_test_module",
    )
    core_module = _load_module(CORE_PATH, "global_pipeline_dependency_view_test_module")
    operator_path = tmp_path / "operator_state.json"
    dependency_path = tmp_path / "dependency_view.json"

    operator_module.persist_operator_state(
        repo_root=Path.cwd(),
        output_path=operator_path,
        workspace_path=tmp_path / "workspace",
    )
    proof = core_module.persist_dependency_view(
        repo_root=Path.cwd(),
        output_path=dependency_path,
        operator_state_path=operator_path,
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    view = proof.dependency_view
    assert view["source"]["operator_state_path"] == str(operator_path)
    assert view["summary"]["visible_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert view["summary"]["cross_app_edge_count"] == 1
    assert view["adjacency"]["upstream_by_unit"]["queue_baseline"] == []
    assert view["adjacency"]["upstream_by_unit"]["relay_followup"] == ["queue_baseline"]
    assert view["adjacency"]["downstream_by_unit"]["queue_baseline"] == ["relay_followup"]
    edge = view["edges"][0]
    assert edge["id"] == "queue_baseline->relay_followup:queue_metrics"
    assert edge["status"] == "available"
    assert edge["cross_app"] is True
    assert edge["producer_app"] == "uav_queue_project"
    assert edge["consumer_app"] == "uav_relay_queue_project"
    flow = next(row for row in view["artifact_flow"] if row["artifact"] == "queue_metrics")
    assert flow["producer_unit_id"] == "queue_baseline"
    assert flow["consumer_unit_ids"] == ["relay_followup"]


def test_dependency_view_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_dependency_view_report_failure_test_module")
    missing = tmp_path / "missing_operator_state.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        operator_state_path=missing,
        output_path=tmp_path / "dependency_view.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_dependency_view_load",
            "label": "Global pipeline dependency view load",
            "status": "fail",
            "summary": "global pipeline dependency view could not be persisted",
        }
    ]
