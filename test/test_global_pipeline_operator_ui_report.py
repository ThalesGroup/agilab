from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


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


def test_operator_ui_helpers_handle_malformed_inputs(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "global_pipeline_operator_ui_helpers_test_module")
    issue = core_module._issue("source", "bad")
    proof = core_module.OperatorUiProof(
        ok=False,
        issues=(issue,),
        path=str(tmp_path / "ui.json"),
        html_path=str(tmp_path / "ui.html"),
        operator_actions_path=str(tmp_path / "actions.json"),
        operator_ui={"summary": "bad", "components": "bad"},
        reloaded_ui={},
    )

    assert issue.as_dict() == {"level": "error", "location": "source", "message": "bad"}
    assert proof.round_trip_ok is False
    assert proof.component_count == 0
    assert proof.unit_card_count == 0
    assert proof.action_control_count == 0
    assert proof.artifact_row_count == 0
    assert proof.as_dict()["issues"] == [issue.as_dict()]
    assert core_module._request_rows({"requests": "bad"}) == ()
    assert core_module._artifact_rows({"artifacts": "bad"}) == ()
    assert core_module._update_rows({"updates": "bad"}) == ()
    assert core_module._live_state_for_actions({"source": {}}) == {}
    assert core_module._unit_cards({"latest_state": {"unit_states": "bad"}})[0]["state"] == "completed"
    assert core_module._dependency_payload({"updates": [{"kind": "dependency_state_update", "payload": "bad"}]}) == {}

    html = core_module.render_operator_ui_html(
        {
            "components": [
                "bad",
                {"id": "custom", "title": "<Custom>", "payload": "<unsafe>"},
            ]
        }
    )

    assert "<Custom>" not in html
    assert "&lt;Custom&gt;" in html
    assert "payload" in html


def test_operator_ui_live_state_load_failure_and_persist_issues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    core_module = _load_module(CORE_PATH, "global_pipeline_operator_ui_issue_test_module")
    actions_path = tmp_path / "operator_actions.json"
    actions_path.write_text(
        core_module.json.dumps(
            {
                "schema": "wrong",
                "run_id": "run",
                "run_status": "ready",
                "source": {"live_state_updates_path": str(tmp_path / "missing.json")},
                "requests": [],
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core_module, "write_operator_ui_html", lambda path, operator_ui: path)

    proof = core_module.persist_operator_ui(
        repo_root=Path.cwd(),
        output_path=tmp_path / "operator_ui.json",
        html_output_path=tmp_path / "operator_ui.html",
        operator_actions_path=actions_path,
    )

    assert proof.ok is False
    assert {issue.location for issue in proof.issues} == {
        "source.operator_actions_schema",
        "rendering.html",
    }


def test_operator_ui_persist_reports_json_round_trip_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    core_module = _load_module(CORE_PATH, "global_pipeline_operator_ui_roundtrip_test_module")
    actions_path = tmp_path / "operator_actions.json"
    html_path = tmp_path / "operator_ui.html"
    actions_path.write_text(
        core_module.json.dumps(
            {
                "schema": core_module.OPERATOR_ACTIONS_SCHEMA,
                "run_id": "run",
                "run_status": "ready",
                "source": {},
                "requests": [],
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core_module, "load_operator_ui", lambda _path: {"changed": True})

    proof = core_module.persist_operator_ui(
        repo_root=Path.cwd(),
        output_path=tmp_path / "operator_ui.json",
        html_output_path=html_path,
        operator_actions_path=actions_path,
    )

    assert html_path.is_file()
    assert proof.ok is False
    assert proof.issues[0].location == "persistence.round_trip"
