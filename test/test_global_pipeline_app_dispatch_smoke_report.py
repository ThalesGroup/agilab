from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_app_dispatch_smoke_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_app_dispatch_smoke.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_app_dispatch_smoke_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_app_dispatch_smoke_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_app_dispatch_smoke_report_executes_queue_and_persists(tmp_path: Path) -> None:
    module = _load_report_module()
    output_path = tmp_path / "app_dispatch_smoke.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline app dispatch smoke report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_dispatch_state.v1"
    assert report["summary"]["smoke_schema"] == "agilab.global_pipeline_app_dispatch_smoke.v1"
    assert report["summary"]["run_id"] == "global-dag-real-dispatch-smoke"
    assert report["summary"]["run_status"] == "in_progress"
    assert report["summary"]["persistence_format"] == "json"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["unit_count"] == 2
    assert report["summary"]["completed_unit_ids"] == ["queue_baseline"]
    assert report["summary"]["runnable_unit_ids"] == ["relay_followup"]
    assert report["summary"]["real_executed_unit_ids"] == ["queue_baseline"]
    assert report["summary"]["readiness_only_unit_ids"] == ["relay_followup"]
    assert report["summary"]["real_execution_scope"] == "first_unit_only"
    assert report["summary"]["packets_generated"] > 0
    assert report["summary"]["available_artifact_ids"] == ["queue_metrics", "queue_reduce_summary"]
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_app_dispatch_smoke_schema",
        "global_pipeline_app_dispatch_smoke_real_queue",
        "global_pipeline_app_dispatch_smoke_artifacts",
        "global_pipeline_app_dispatch_smoke_relay_readiness",
        "global_pipeline_app_dispatch_smoke_persistence",
        "global_pipeline_app_dispatch_smoke_provenance",
        "global_pipeline_app_dispatch_smoke_docs_reference",
    }


def test_app_dispatch_smoke_state_contains_real_artifacts(tmp_path: Path) -> None:
    module = _load_core_module()

    proof = module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=tmp_path / "app_dispatch_smoke.json",
        run_root=tmp_path / "workspace",
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    state = proof.dispatch_state
    queue, relay = state["units"]
    metrics = queue["real_execution"]["summary_metrics"]
    workspace = Path(queue["real_execution"]["workspace"])
    assert state["provenance"]["real_app_execution"] is True
    assert state["provenance"]["real_execution_scope"] == "first_unit_only"
    assert queue["dispatch_status"] == "completed"
    assert queue["execution_mode"] == "real_app_entry"
    assert metrics["routing_policy"] == "queue_aware"
    assert metrics["packets_generated"] > 0
    assert relay["dispatch_status"] == "runnable"
    assert relay["execution_mode"] == "readiness_only"
    assert relay["unblocked_by"] == ["queue_metrics"]
    assert (workspace / queue["real_execution"]["summary_metrics_path"]).is_file()
    assert (workspace / queue["real_execution"]["reduce_artifact_path"]).is_file()


def test_app_dispatch_smoke_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_report_module()
    missing = tmp_path / "missing.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        dag_path=missing,
        output_path=tmp_path / "app_dispatch_smoke.json",
        workspace_path=tmp_path / "workspace",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_app_dispatch_smoke_load",
            "label": "Global pipeline app dispatch smoke load",
            "status": "fail",
            "summary": "global pipeline app dispatch smoke could not be persisted",
        }
    ]
