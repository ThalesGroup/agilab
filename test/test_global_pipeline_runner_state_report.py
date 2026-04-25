from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_runner_state_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_runner_state.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_runner_state_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_runner_state_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runner_state_report_builds_dispatch_projection() -> None:
    module = _load_report_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["report"] == "Global pipeline runner state report"
    assert report["status"] == "pass"
    assert report["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert report["summary"]["schema"] == "agilab.global_pipeline_runner_state.v1"
    assert report["summary"]["runner_mode"] == "read_only_preview"
    assert report["summary"]["run_status"] == "not_started"
    assert report["summary"]["unit_count"] == 2
    assert report["summary"]["runnable_count"] == 1
    assert report["summary"]["blocked_count"] == 1
    assert report["summary"]["completed_count"] == 0
    assert report["summary"]["failed_count"] == 0
    assert report["summary"]["runnable_unit_ids"] == ["queue_baseline"]
    assert report["summary"]["blocked_unit_ids"] == ["relay_followup"]
    assert report["summary"]["retry_policy_count"] == 2
    assert report["summary"]["partial_rerun_record_count"] == 2
    assert report["summary"]["operator_state_count"] == 2
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_runner_state_schema",
        "global_pipeline_runner_state_dispatch_queue",
        "global_pipeline_runner_state_transitions",
        "global_pipeline_runner_state_retry_partial_rerun",
        "global_pipeline_runner_state_operator_ui",
        "global_pipeline_runner_state_provenance",
        "global_pipeline_runner_state_docs_reference",
    }


def test_runner_state_units_keep_transitions_and_operator_metadata() -> None:
    module = _load_core_module()

    state = module.build_runner_state(repo_root=Path.cwd())

    assert state.ok is True
    first, second = state.state_units
    assert first["id"] == "queue_baseline"
    assert first["dispatch_status"] == "runnable"
    assert first["operator_ui"]["state"] == "ready_to_dispatch"
    assert first["retry"] == {
        "attempt": 0,
        "last_error": "",
        "max_attempts": 0,
        "next_action": "configure retry policy before dispatching queue_baseline",
        "policy": "metadata_only",
        "status": "not_scheduled",
    }
    assert first["partial_rerun"] == {
        "artifact_scope": ["queue_metrics"],
        "eligible_after_completion": True,
        "policy": "metadata_only",
        "requested": False,
        "requires_completed_dependencies": [],
    }

    assert second["id"] == "relay_followup"
    assert second["dispatch_status"] == "blocked"
    assert second["operator_ui"] == {
        "blocked_by_artifacts": ["queue_metrics"],
        "message": "relay_followup is blocked until queue_metrics is available.",
        "severity": "info",
        "state": "waiting_for_artifacts",
    }
    assert second["partial_rerun"]["artifact_scope"] == ["relay_metrics"]
    assert second["partial_rerun"]["requires_completed_dependencies"] == ["queue_baseline"]
    assert second["provenance"] == {
        "pipeline_view": "src/agilab/apps/builtin/uav_relay_queue_project/pipeline_view.dot",
        "planning_mode": "read_only",
        "runner_state_mode": "read_only_preview",
        "source_app": "uav_relay_queue_project",
        "source_dag": "docs/source/data/multi_app_dag_sample.json",
        "source_plan_runner_status": "not_executed",
        "source_plan_schema": "agilab.global_pipeline_execution_plan.v1",
        "source_unit_id": "relay_followup",
    }
    transition_pairs = {
        (transition["from"], transition["to"])
        for unit in state.state_units
        for transition in unit["transitions"]
    }
    assert {
        ("pending", "runnable"),
        ("pending", "blocked"),
        ("blocked", "runnable"),
        ("runnable", "completed"),
        ("runnable", "failed"),
        ("failed", "runnable"),
        ("completed", "runnable"),
    }.issubset(transition_pairs)


def test_runner_state_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_report_module()
    missing = tmp_path / "missing.json"

    report = module.build_report(repo_root=Path.cwd(), dag_path=missing)

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_runner_state_load",
            "label": "Global pipeline runner state load",
            "status": "fail",
            "summary": "global pipeline runner state could not be assembled",
        }
    ]
