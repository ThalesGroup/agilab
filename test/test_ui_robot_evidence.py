from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/ui_robot_evidence.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_evidence_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _successful_run() -> dict[str, object]:
    return {
        "attempt": 1,
        "conclusion": "success",
        "createdAt": "2026-05-08T20:18:44Z",
        "databaseId": 25577485125,
        "event": "workflow_dispatch",
        "headBranch": "main",
        "headSha": "abc123",
        "name": "ui-robot-matrix",
        "status": "completed",
        "updatedAt": "2026-05-08T20:26:55Z",
        "url": "https://github.com/ThalesGroup/agilab/actions/runs/25577485125",
        "workflowName": "ui-robot-matrix",
    }


def _artifact() -> dict[str, object]:
    return {
        "name": "ui-robot-matrix-1",
        "expired": False,
        "size_bytes": 4902,
        "archive_download_url": "https://api.github.com/repos/ThalesGroup/agilab/actions/artifacts/1/zip",
    }


def _matrix_summary() -> dict[str, object]:
    return {
        "schema": "agilab.widget_robot_matrix.v1",
        "success": True,
        "page_count": 30,
        "widget_count": 532,
        "interacted_count": 348,
        "probed_count": 184,
        "skipped_count": 0,
        "failed_count": 0,
        "duration_seconds": 438.2,
        "failed_scenarios": [],
        "failure_samples": [],
    }


def _scenario_summary() -> dict[str, object]:
    return {
        "success": True,
        "app_count": 10,
        "page_count": 30,
        "widget_count": 532,
        "interacted_count": 348,
        "probed_count": 184,
        "skipped_count": 0,
        "failed_count": 0,
        "total_duration_seconds": 411.6,
        "within_target": True,
    }


def test_select_latest_successful_run_skips_failed_runs() -> None:
    module = _load_module()
    failed = {**_successful_run(), "databaseId": 1, "conclusion": "failure"}
    success = _successful_run()

    selected = module.select_latest_successful_run([failed, success])

    assert selected["databaseId"] == "25577485125"
    assert selected["workflowName"] == "ui-robot-matrix"


def test_load_artifact_payloads_and_build_evidence_contract(tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "ui-robot-matrix-1" / "test-results" / "ui-robot-matrix"
    artifact_root.mkdir(parents=True)
    (artifact_root / "summary.json").write_text(json.dumps(_matrix_summary()), encoding="utf-8")
    (artifact_root / "isolated-core-pages.json").write_text(
        json.dumps(_scenario_summary()),
        encoding="utf-8",
    )
    (artifact_root / "isolated-core-pages.ndjson").write_text("{}\n", encoding="utf-8")
    (artifact_root / "exit-code.txt").write_text("0\n", encoding="utf-8")

    matrix_summary, scenario_summary, artifact_checks = module.load_artifact_payloads(tmp_path)
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=matrix_summary,
        scenario_summary=scenario_summary,
        artifact_checks=artifact_checks,
        generated_at="2026-05-08T20:30:00Z",
    )
    report = module.build_report(evidence)

    assert evidence["schema"] == module.SCHEMA
    assert evidence["source"]["run_id"] == "25577485125"
    assert evidence["result"]["status"] == "pass"
    assert evidence["result"]["app_count"] == 10
    assert evidence["result"]["failed_count"] == 0
    assert evidence["artifact"]["required_files_present"] is True
    assert report["status"] == "pass"


def test_validate_evidence_rejects_failed_robot_result() -> None:
    module = _load_module()
    scenario = {**_scenario_summary(), "success": False, "failed_count": 1}
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary={**_matrix_summary(), "success": False, "failed_count": 1},
        scenario_summary=scenario,
        artifact_checks={"required_files_present": True, "exit_code": "1"},
        generated_at="2026-05-08T20:30:00Z",
    )

    report = module.build_report(evidence)

    assert report["status"] == "fail"
    failed_ids = {check["id"] for check in report["checks"] if check["status"] == "fail"}
    assert failed_ids == {"artifact", "robot_result"}


def test_main_check_validates_existing_evidence_file(tmp_path: Path, capsys) -> None:
    module = _load_module()
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=_matrix_summary(),
        scenario_summary=_scenario_summary(),
        artifact_checks={"required_files_present": True, "exit_code": "0", "progress_log_bytes": 3},
        generated_at="2026-05-08T20:30:00Z",
    )
    output = tmp_path / "ui_robot_evidence.json"
    module.write_evidence(output, evidence)

    exit_code = module.main(["--check", "--output", str(output), "--compact"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["schema"] == module.SCHEMA
    assert payload["status"] == "pass"
