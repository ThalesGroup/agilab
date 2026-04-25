from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_live_state_updates_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_live_state_updates.py").resolve()
DEPENDENCY_CORE_PATH = Path("src/agilab/global_pipeline_dependency_view.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_state_updates_report_projects_ordered_update_stream(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_live_state_updates_report_test_module")
    output_path = tmp_path / "live_state_updates.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline live state updates report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_live_state_updates.v1"
    assert report["summary"]["run_status"] == "ready_for_operator_review"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["update_count"] == 6
    assert report["summary"]["graph_update_count"] == 1
    assert report["summary"]["unit_update_count"] == 2
    assert report["summary"]["artifact_update_count"] == 1
    assert report["summary"]["dependency_update_count"] == 1
    assert report["summary"]["action_update_count"] == 1
    assert report["summary"]["retry_action_count"] == 2
    assert report["summary"]["partial_rerun_action_count"] == 2
    assert report["summary"]["visible_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_live_state_updates_schema",
        "global_pipeline_live_state_updates_sequence",
        "global_pipeline_live_state_updates_units",
        "global_pipeline_live_state_updates_dependency",
        "global_pipeline_live_state_updates_actions",
        "global_pipeline_live_state_updates_persistence",
        "global_pipeline_live_state_updates_docs_reference",
    }


def test_live_state_updates_read_existing_dependency_view(tmp_path: Path) -> None:
    dependency_module = _load_module(
        DEPENDENCY_CORE_PATH,
        "global_pipeline_dependency_view_for_live_updates_test_module",
    )
    core_module = _load_module(CORE_PATH, "global_pipeline_live_state_updates_test_module")
    dependency_path = tmp_path / "dependency_view.json"
    updates_path = tmp_path / "live_state_updates.json"

    dependency_module.persist_dependency_view(
        repo_root=Path.cwd(),
        output_path=dependency_path,
        workspace_path=tmp_path / "workspace",
    )
    proof = core_module.persist_live_state_updates(
        repo_root=Path.cwd(),
        output_path=updates_path,
        dependency_view_path=dependency_path,
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    updates = proof.live_state_updates
    assert updates["source"]["dependency_view_path"] == str(dependency_path)
    assert updates["summary"]["update_count"] == 6
    assert updates["update_stream"]["mode"] == "deterministic_replay_contract"
    assert updates["update_stream"]["live_runtime_service"] is False
    assert [row["sequence"] for row in updates["updates"]] == [1, 2, 3, 4, 5, 6]
    assert [row["kind"] for row in updates["updates"]] == [
        "dependency_graph_ready",
        "unit_state_update",
        "artifact_state_update",
        "dependency_state_update",
        "unit_state_update",
        "operator_actions_update",
    ]
    assert updates["latest_state"]["unit_states"] == {
        "queue_baseline": "completed",
        "relay_followup": "completed",
    }
    dependency_update = updates["updates"][3]
    assert dependency_update["target_id"] == "queue_baseline->relay_followup:queue_metrics"
    assert dependency_update["payload"]["artifact"] == "queue_metrics"
    action_update = updates["updates"][5]
    assert action_update["payload"]["retry_action_ids"] == [
        "queue_baseline:retry",
        "relay_followup:retry",
    ]
    assert action_update["payload"]["partial_rerun_action_ids"] == [
        "queue_baseline:partial_rerun",
        "relay_followup:partial_rerun",
    ]


def test_live_state_updates_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(
        REPORT_PATH,
        "global_pipeline_live_state_updates_report_failure_test_module",
    )
    missing = tmp_path / "missing_dependency_view.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        dependency_view_path=missing,
        output_path=tmp_path / "live_state_updates.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_live_state_updates_load",
            "label": "Global pipeline live state updates load",
            "status": "fail",
            "summary": "global pipeline live state updates could not be persisted",
        }
    ]
