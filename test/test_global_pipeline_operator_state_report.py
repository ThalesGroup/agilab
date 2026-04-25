from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_operator_state_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_operator_state.py").resolve()
DISPATCH_CORE_PATH = Path("src/agilab/global_pipeline_app_dispatch_smoke.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_operator_state_report_projects_completed_units_and_actions(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_operator_state_report_test_module")
    output_path = tmp_path / "operator_state.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline operator state report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_operator_state.v1"
    assert report["summary"]["run_status"] == "ready_for_operator_review"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["visible_unit_count"] == 2
    assert report["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert report["summary"]["handoff_count"] == 1
    assert report["summary"]["retry_action_count"] == 2
    assert report["summary"]["partial_rerun_action_count"] == 2
    assert "queue_metrics" in report["summary"]["available_artifact_ids"]
    assert "relay_metrics" in report["summary"]["available_artifact_ids"]
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_operator_state_schema",
        "global_pipeline_operator_state_units",
        "global_pipeline_operator_state_artifacts_handoffs",
        "global_pipeline_operator_state_actions",
        "global_pipeline_operator_state_persistence",
        "global_pipeline_operator_state_docs_reference",
    }


def test_operator_state_reads_existing_dispatch_state(tmp_path: Path) -> None:
    dispatch_module = _load_module(
        DISPATCH_CORE_PATH,
        "global_pipeline_app_dispatch_smoke_for_operator_state_test_module",
    )
    core_module = _load_module(CORE_PATH, "global_pipeline_operator_state_test_module")
    dispatch_path = tmp_path / "dispatch_state.json"
    operator_path = tmp_path / "operator_state.json"

    dispatch_module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=dispatch_path,
        run_root=tmp_path / "workspace",
    )
    proof = core_module.persist_operator_state(
        repo_root=Path.cwd(),
        output_path=operator_path,
        dispatch_state_path=dispatch_path,
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    state = proof.operator_state
    assert state["source"]["dispatch_state_path"] == str(dispatch_path)
    assert state["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert state["summary"]["retry_action_count"] == 2
    assert state["summary"]["partial_rerun_action_count"] == 2
    queue, relay = state["operator_units"]
    assert queue["operator_state"] == "completed"
    assert relay["operator_state"] == "completed"
    assert state["handoffs"][0]["from"] == "queue_baseline"
    assert state["handoffs"][0]["to"] == "relay_followup"
    assert state["handoffs"][0]["artifact"] == "queue_metrics"
    assert state["handoffs"][0]["status"] == "available"
    assert state["handoffs"][0]["path"].endswith("_summary_metrics.json")


def test_operator_state_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_operator_state_report_failure_test_module")
    missing = tmp_path / "missing_dispatch_state.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        dispatch_state_path=missing,
        output_path=tmp_path / "operator_state.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_operator_state_load",
            "label": "Global pipeline operator state load",
            "status": "fail",
            "summary": "global pipeline operator state could not be persisted",
        }
    ]
