from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/global_pipeline_operator_ui_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_operator_ui.py").resolve()
ACTION_CORE_PATH = Path("src/agilab/global_pipeline_operator_actions.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_operator_ui_report_renders_components_and_actions(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_operator_ui_report_test_module")
    output_path = tmp_path / "operator_ui.json"
    html_path = tmp_path / "operator_ui.html"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        html_output_path=html_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline operator UI report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert html_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_operator_ui.v1"
    assert report["summary"]["run_status"] == "ready_for_operator_review"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["component_count"] == 6
    assert report["summary"]["unit_card_count"] == 2
    assert report["summary"]["action_control_count"] == 2
    assert report["summary"]["artifact_row_count"] == 4
    assert report["summary"]["timeline_update_count"] == 6
    assert report["summary"]["supported_action_ids"] == [
        "queue_baseline:retry",
        "relay_followup:partial_rerun",
    ]
    assert report["summary"]["source_real_execution_scope"] == "full_dag_smoke"
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_operator_ui_schema",
        "global_pipeline_operator_ui_components",
        "global_pipeline_operator_ui_action_controls",
        "global_pipeline_operator_ui_html_render",
        "global_pipeline_operator_ui_source_actions",
        "global_pipeline_operator_ui_persistence",
        "global_pipeline_operator_ui_docs_reference",
    }


def test_operator_ui_reads_existing_operator_actions(tmp_path: Path) -> None:
    action_module = _load_module(
        ACTION_CORE_PATH,
        "global_pipeline_operator_actions_for_ui_test_module",
    )
    core_module = _load_module(CORE_PATH, "global_pipeline_operator_ui_test_module")
    actions_path = tmp_path / "operator_actions.json"
    ui_path = tmp_path / "operator_ui.json"
    html_path = tmp_path / "operator_ui.html"

    action_module.persist_operator_actions(
        repo_root=Path.cwd(),
        output_path=actions_path,
        workspace_path=tmp_path / "action_workspace",
    )
    proof = core_module.persist_operator_ui(
        repo_root=Path.cwd(),
        output_path=ui_path,
        html_output_path=html_path,
        operator_actions_path=actions_path,
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    assert Path(proof.html_path).is_file()
    ui = proof.operator_ui
    assert ui["source"]["operator_actions_path"] == str(actions_path)
    assert ui["summary"]["component_count"] == 6
    assert ui["summary"]["supported_action_ids"] == [
        "queue_baseline:retry",
        "relay_followup:partial_rerun",
    ]
    action_component = next(
        component for component in ui["components"] if component["id"] == "action_controls"
    )
    assert [item["action_id"] for item in action_component["items"]] == [
        "queue_baseline:retry",
        "relay_followup:partial_rerun",
    ]
    html = html_path.read_text(encoding="utf-8")
    assert "queue_baseline" in html
    assert "relay_followup" in html
    assert "queue_baseline:retry" in html
    assert "relay_followup:partial_rerun" in html


def test_operator_ui_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "global_pipeline_operator_ui_report_failure_test_module")
    missing = tmp_path / "missing_operator_actions.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        operator_actions_path=missing,
        output_path=tmp_path / "operator_ui.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_operator_ui_load",
            "label": "Global pipeline operator UI load",
            "status": "fail",
            "summary": "global pipeline operator UI could not be persisted",
        }
    ]
