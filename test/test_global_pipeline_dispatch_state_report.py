from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_dispatch_state_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_dispatch_state.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_dispatch_state_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_dispatch_state_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dispatch_state_report_persists_and_reloads_json(tmp_path: Path) -> None:
    module = _load_report_module()
    output_path = tmp_path / "dispatch_state.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=output_path)

    assert report["report"] == "Global pipeline dispatch state report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_dispatch_state.v1"
    assert report["summary"]["run_id"] == "global-dag-dispatch-proof"
    assert report["summary"]["run_status"] == "in_progress"
    assert report["summary"]["persistence_format"] == "json"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["unit_count"] == 2
    assert report["summary"]["completed_unit_ids"] == ["queue_baseline"]
    assert report["summary"]["runnable_unit_ids"] == ["relay_followup"]
    assert report["summary"]["blocked_unit_ids"] == []
    assert report["summary"]["available_artifact_ids"] == ["queue_metrics"]
    assert report["summary"]["retry_counter_count"] == 2
    assert report["summary"]["partial_rerun_flag_count"] == 2
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_dispatch_state_schema",
        "global_pipeline_dispatch_state_round_trip",
        "global_pipeline_dispatch_state_progress",
        "global_pipeline_dispatch_state_artifact_unblock",
        "global_pipeline_dispatch_state_retry_partial_rerun",
        "global_pipeline_dispatch_state_timestamps_provenance",
        "global_pipeline_dispatch_state_docs_reference",
    }


def test_dispatch_state_records_progress_artifacts_and_provenance(tmp_path: Path) -> None:
    module = _load_core_module()

    proof = module.persist_dispatch_state(
        repo_root=Path.cwd(),
        output_path=tmp_path / "dispatch_state.json",
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    state = proof.dispatch_state
    assert state["created_at"] == "2026-04-25T00:00:00Z"
    assert state["updated_at"] == "2026-04-25T00:00:03Z"
    assert state["summary"] == {
        "available_artifact_ids": ["queue_metrics"],
        "blocked_unit_ids": [],
        "completed_unit_ids": ["queue_baseline"],
        "event_count": 5,
        "runnable_unit_ids": ["relay_followup"],
        "unit_count": 2,
    }
    queue, relay = state["units"]
    assert queue["id"] == "queue_baseline"
    assert queue["dispatch_status"] == "completed"
    assert queue["retry"] == {
        "attempt": 1,
        "last_error": "",
        "max_attempts": 0,
        "retry_count": 0,
    }
    assert queue["operator_ui"] == {
        "blocked_by_artifacts": [],
        "message": "queue_baseline completed and published queue_metrics.",
        "severity": "success",
        "state": "completed",
    }
    assert relay["id"] == "relay_followup"
    assert relay["dispatch_status"] == "runnable"
    assert relay["operator_ui"] == {
        "blocked_by_artifacts": [],
        "message": "relay_followup is runnable after queue_metrics became available.",
        "severity": "info",
        "state": "ready_to_dispatch",
    }
    assert state["artifacts"] == [
        {
            "artifact": "queue_metrics",
            "available_at": "2026-04-25T00:00:01Z",
            "kind": "summary_metrics",
            "path": "queue_analysis/uav_queue_summary_metrics.json",
            "producer": "queue_baseline",
            "status": "available",
        }
    ]
    assert [event["kind"] for event in state["events"]] == [
        "run_created",
        "unit_completed",
        "artifact_available",
        "unit_unblocked",
        "state_persisted",
    ]
    assert state["provenance"] == {
        "dispatch_mode": "simulated_persistent_state",
        "real_app_execution": False,
        "source_dag": "docs/source/data/multi_app_dag_sample.json",
        "source_plan_schema": "agilab.global_pipeline_execution_plan.v1",
        "source_runner_state_schema": "agilab.global_pipeline_runner_state.v1",
    }


def test_dispatch_state_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_report_module()
    missing = tmp_path / "missing.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        dag_path=missing,
        output_path=tmp_path / "dispatch_state.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_dispatch_state_load",
            "label": "Global pipeline dispatch state load",
            "status": "fail",
            "summary": "global pipeline dispatch state could not be persisted",
        }
    ]
