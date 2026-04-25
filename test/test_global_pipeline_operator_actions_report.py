from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_operator_actions_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_operator_actions.py").resolve()
LIVE_UPDATES_CORE_PATH = Path("src/agilab/global_pipeline_live_state_updates.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_operator_actions_report_executes_retry_and_partial_rerun(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_operator_actions_report_test_module")
    output_path = tmp_path / "operator_actions.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline operator actions report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_operator_actions.v1"
    assert report["summary"]["run_status"] == "completed"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["action_request_count"] == 2
    assert report["summary"]["completed_action_count"] == 2
    assert report["summary"]["retry_execution_count"] == 1
    assert report["summary"]["partial_rerun_execution_count"] == 1
    assert report["summary"]["real_action_execution_count"] == 2
    assert report["summary"]["output_artifact_count"] == 4
    assert report["summary"]["event_count"] == 4
    assert report["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_operator_actions_schema",
        "global_pipeline_operator_actions_requests",
        "global_pipeline_operator_actions_real_replay",
        "global_pipeline_operator_actions_live_update_source",
        "global_pipeline_operator_actions_persistence",
        "global_pipeline_operator_actions_docs_reference",
    }


def test_operator_actions_read_existing_live_state_updates(tmp_path: Path) -> None:
    live_updates_module = _load_module(
        LIVE_UPDATES_CORE_PATH,
        "global_pipeline_live_updates_for_operator_actions_test_module",
    )
    core_module = _load_module(CORE_PATH, "global_pipeline_operator_actions_test_module")
    live_updates_path = tmp_path / "live_state_updates.json"
    actions_path = tmp_path / "operator_actions.json"

    live_updates_module.persist_live_state_updates(
        repo_root=Path.cwd(),
        output_path=live_updates_path,
        workspace_path=tmp_path / "source_workspace",
    )
    proof = core_module.persist_operator_actions(
        repo_root=Path.cwd(),
        output_path=actions_path,
        live_state_updates_path=live_updates_path,
        workspace_path=tmp_path / "action_workspace",
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    actions = proof.operator_actions
    assert actions["source"]["live_state_updates_path"] == str(live_updates_path)
    assert actions["summary"]["action_request_count"] == 2
    assert actions["summary"]["completed_action_count"] == 2
    retry, partial = actions["requests"]
    assert retry["action_id"] == "queue_baseline:retry"
    assert retry["execution_mode"] == "real_app_entry_action_replay"
    assert partial["action_id"] == "relay_followup:partial_rerun"
    assert partial["artifact_scope"] == ["relay_metrics"]
    assert partial["consumed_artifact_ids"] == ["queue_metrics_retry"]
    artifact_ids = {artifact["artifact"] for artifact in actions["artifacts"]}
    assert artifact_ids == {
        "queue_metrics_retry",
        "queue_reduce_summary_retry",
        "relay_metrics_partial_rerun",
        "relay_reduce_summary_partial_rerun",
    }
    for artifact in actions["artifacts"]:
        assert Path(artifact["path"]).is_file()
        if artifact["kind"] == "summary_metrics":
            assert artifact["packets_generated"] > 0


def test_operator_actions_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(
        REPORT_PATH,
        "global_pipeline_operator_actions_report_failure_test_module",
    )
    missing = tmp_path / "missing_live_updates.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        live_state_updates_path=missing,
        output_path=tmp_path / "operator_actions.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_operator_actions_load",
            "label": "Global pipeline operator actions load",
            "status": "fail",
            "summary": "global pipeline operator actions could not be persisted",
        }
    ]
