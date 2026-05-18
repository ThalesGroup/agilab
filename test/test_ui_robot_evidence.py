from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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


def _trend_report() -> dict[str, object]:
    return {
        "schema": "agilab.ui_robot_trend_report.v1",
        "success": True,
        "summary": {
            "page_count": 30,
            "failed_page_count": 0,
            "flaky_page_count": 0,
            "slow_page_count": 0,
            "parse_error_count": 0,
            "budget_violation_count": 0,
            "total_duration_seconds": 411.6,
            "mean_page_duration_seconds": 13.72,
        },
    }


def _write_artifact_payloads(root: Path, *, trend_report: dict[str, object] | None = None) -> Path:
    artifact_root = root / "ui-robot-matrix-1" / "test-results" / "ui-robot-matrix"
    artifact_root.mkdir(parents=True)
    (artifact_root / "summary.json").write_text(json.dumps(_matrix_summary()), encoding="utf-8")
    (artifact_root / "isolated-core-pages.json").write_text(
        json.dumps(_scenario_summary()),
        encoding="utf-8",
    )
    (artifact_root / "isolated-core-pages.ndjson").write_text("{}\n", encoding="utf-8")
    (artifact_root / "trend-report.json").write_text(
        json.dumps(_trend_report() if trend_report is None else trend_report),
        encoding="utf-8",
    )
    (artifact_root / "exit-code.txt").write_text("0\n", encoding="utf-8")
    return artifact_root


def test_select_latest_successful_run_skips_failed_runs() -> None:
    module = _load_module()
    failed = {**_successful_run(), "databaseId": 1, "conclusion": "failure"}
    success = _successful_run()

    selected = module.select_latest_successful_run([failed, success])

    assert selected["databaseId"] == "25577485125"
    assert selected["workflowName"] == "ui-robot-matrix"


def test_github_cli_fetchers_and_artifact_metadata(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def _fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if argv[:3] == ["gh", "run", "list"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps([{**_successful_run(), "conclusion": "failure"}, _successful_run()]), stderr="")
        if argv[:3] == ["gh", "run", "view"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(_successful_run()), stderr="")
        if argv[:2] == ["gh", "api"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "artifacts": [
                            "ignored",
                            {"name": "other", "expired": False},
                            {
                                "name": "ui-robot-matrix-1",
                                "expired": False,
                                "size_in_bytes": 123,
                                "archive_download_url": "https://example.invalid/artifact.zip",
                            },
                        ]
                    }
                ),
                stderr="",
            )
        raise AssertionError(argv)

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    latest = module.fetch_latest_successful_run(repo="ThalesGroup/agilab", branch="main", limit=2, repo_root=tmp_path)
    viewed = module.fetch_run("25577485125", repo="ThalesGroup/agilab", repo_root=tmp_path)
    artifact = module.fetch_artifact_metadata("25577485125", repo="ThalesGroup/agilab", repo_root=tmp_path)

    assert latest["databaseId"] == "25577485125"
    assert viewed["workflowName"] == module.WORKFLOW_NAME
    assert artifact == {
        "name": "ui-robot-matrix-1",
        "expired": False,
        "size_bytes": 123,
        "archive_download_url": "https://example.invalid/artifact.zip",
    }
    assert "--branch" in calls[0]
    assert f"{module.WORKFLOW_NAME}.yml" in calls[0]
    assert "databaseId" in module._github_fields()


def test_github_cli_errors_and_bad_payloads(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(RuntimeError, match="no successful"):
        module.select_latest_successful_run([])

    monkeypatch.setattr(module, "_run_gh_json", lambda *_args, **_kwargs: {})
    with pytest.raises(RuntimeError, match="JSON list"):
        module.fetch_latest_successful_run(repo="repo", branch=None, limit=1, repo_root=tmp_path)

    monkeypatch.setattr(module, "_run_gh_json", lambda *_args, **_kwargs: [])
    with pytest.raises(RuntimeError, match="JSON object"):
        module.fetch_run("1", repo="repo", repo_root=tmp_path)

    monkeypatch.setattr(module, "_run_gh_json", lambda *_args, **_kwargs: {"artifacts": {}})
    with pytest.raises(RuntimeError, match="artifacts list"):
        module.fetch_artifact_metadata("1", repo="repo", repo_root=tmp_path)

    monkeypatch.setattr(module, "_run_gh_json", lambda *_args, **_kwargs: {"artifacts": [{"name": "other"}]})
    with pytest.raises(RuntimeError, match="no 'ui-robot-matrix' artifact"):
        module.fetch_artifact_metadata("1", repo="repo", repo_root=tmp_path)

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        module._load_json(bad_json)


def test_command_wrappers_report_errors_and_download_recreates_destination(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=2, stdout="", stderr="denied"),
    )
    with pytest.raises(RuntimeError, match="denied"):
        module._run_gh_json(["run", "list"], repo_root=tmp_path)
    with pytest.raises(RuntimeError, match="denied"):
        module._run_command(["gh", "version"], repo_root=tmp_path)

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        module._run_gh_json(["run", "list"], repo_root=tmp_path)

    destination = tmp_path / "artifact"
    destination.mkdir()
    (destination / "stale.txt").write_text("old", encoding="utf-8")
    commands: list[list[str]] = []

    def _fake_run_command(args, *, repo_root):
        commands.append(list(args))

    monkeypatch.setattr(module, "_run_command", _fake_run_command)

    result = module.download_artifact(
        "123",
        repo="ThalesGroup/agilab",
        artifact_name="ui-robot-matrix-1",
        destination=destination,
        repo_root=tmp_path,
    )

    assert result == destination
    assert destination.is_dir()
    assert not (destination / "stale.txt").exists()
    assert commands[0][:4] == ["gh", "run", "download", "123"]


def test_load_artifact_payloads_and_build_evidence_contract(tmp_path: Path) -> None:
    module = _load_module()
    _write_artifact_payloads(tmp_path)

    matrix_summary, scenario_summary, trend_report, artifact_checks = module.load_artifact_payloads(tmp_path)
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=matrix_summary,
        scenario_summary=scenario_summary,
        trend_report=trend_report,
        artifact_checks=artifact_checks,
        generated_at="2026-05-08T20:30:00Z",
    )
    report = module.build_report(evidence)

    assert evidence["schema"] == module.SCHEMA
    assert evidence["source"]["run_id"] == "25577485125"
    assert evidence["result"]["status"] == "pass"
    assert evidence["result"]["app_count"] == 10
    assert evidence["result"]["failed_count"] == 0
    assert evidence["result"]["trend"]["schema"] == module.TREND_REPORT_SCHEMA
    assert evidence["result"]["trend"]["failed_page_count"] == 0
    assert evidence["artifact"]["trend_report_file"].endswith("trend-report.json")
    assert evidence["artifact"]["required_files_present"] is True
    assert report["status"] == "pass"


def test_load_artifact_payloads_requires_trend_report(tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = _write_artifact_payloads(tmp_path)
    (artifact_root / "trend-report.json").unlink()

    with pytest.raises(FileNotFoundError, match="trend_report"):
        module.load_artifact_payloads(tmp_path)


def test_load_artifact_payloads_rejects_bad_trend_schema(tmp_path: Path) -> None:
    module = _load_module()
    _write_artifact_payloads(tmp_path, trend_report={"schema": "wrong.schema", "success": True, "summary": {}})

    with pytest.raises(ValueError, match=module.TREND_REPORT_SCHEMA):
        module.load_artifact_payloads(tmp_path)


def test_validate_evidence_rejects_failed_robot_result() -> None:
    module = _load_module()
    scenario = {**_scenario_summary(), "success": False, "failed_count": 1}
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary={**_matrix_summary(), "success": False, "failed_count": 1},
        scenario_summary=scenario,
        trend_report=_trend_report(),
        artifact_checks={"required_files_present": True, "exit_code": "1"},
        generated_at="2026-05-08T20:30:00Z",
    )

    report = module.build_report(evidence)

    assert report["status"] == "fail"
    failed_ids = {check["id"] for check in report["checks"] if check["status"] == "fail"}
    assert failed_ids == {"artifact", "robot_result"}


def test_validate_evidence_rejects_missing_trend_report() -> None:
    module = _load_module()
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=_matrix_summary(),
        scenario_summary=_scenario_summary(),
        trend_report={"schema": "wrong.schema", "success": True, "summary": {}},
        artifact_checks={"required_files_present": True, "exit_code": "0", "progress_log_bytes": 3},
        generated_at="2026-05-08T20:30:00Z",
    )

    report = module.build_report(evidence)

    assert report["status"] == "fail"
    failed_ids = {check["id"] for check in report["checks"] if check["status"] == "fail"}
    assert failed_ids == {"artifact", "trend_report", "robot_result"}


@pytest.mark.parametrize(
    "field",
    ["failed_page_count", "flaky_page_count", "parse_error_count", "budget_violation_count"],
)
def test_validate_evidence_rejects_unhealthy_trend_report(field: str) -> None:
    module = _load_module()
    trend_report = _trend_report()
    trend_summary = dict(trend_report["summary"])
    trend_summary[field] = 1
    trend_report["summary"] = trend_summary
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=_matrix_summary(),
        scenario_summary=_scenario_summary(),
        trend_report=trend_report,
        artifact_checks={
            "required_files_present": True,
            "exit_code": "0",
            "progress_log_bytes": 3,
            "trend_report_schema": "agilab.ui_robot_trend_report.v1",
        },
        generated_at="2026-05-08T20:30:00Z",
    )

    report = module.build_report(evidence)

    assert report["status"] == "fail"
    failed_ids = {check["id"] for check in report["checks"] if check["status"] == "fail"}
    assert failed_ids == {"trend_report", "robot_result"}


def test_main_check_validates_existing_evidence_file(tmp_path: Path, capsys) -> None:
    module = _load_module()
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=_matrix_summary(),
        scenario_summary=_scenario_summary(),
        trend_report=_trend_report(),
        artifact_checks={
            "required_files_present": True,
            "exit_code": "0",
            "progress_log_bytes": 3,
            "trend_report_schema": "agilab.ui_robot_trend_report.v1",
        },
        generated_at="2026-05-08T20:30:00Z",
    )
    output = tmp_path / "ui_robot_evidence.json"
    module.write_evidence(output, evidence)

    exit_code = module.main(["--check", "--output", str(output), "--compact"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["schema"] == module.SCHEMA
    assert payload["status"] == "pass"


def test_refresh_evidence_uses_artifact_dir_and_download_paths(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = _write_artifact_payloads(tmp_path / "existing-artifact")
    monkeypatch.setattr(module, "fetch_run", lambda run_id, *, repo, repo_root: _successful_run())
    monkeypatch.setattr(module, "fetch_latest_successful_run", lambda *, repo, branch, limit, repo_root: _successful_run())
    monkeypatch.setattr(module, "fetch_artifact_metadata", lambda run_id, *, repo, repo_root: _artifact())

    evidence = module.refresh_evidence(
        repo="ThalesGroup/agilab",
        branch=None,
        run_id="25577485125",
        run_limit=1,
        artifact_dir=artifact_root,
        repo_root=tmp_path,
    )

    assert evidence["result"]["status"] == "pass"

    def _fake_download_artifact(_run_id, *, repo, artifact_name, destination, repo_root):
        _write_artifact_payloads(destination)
        return destination

    monkeypatch.setattr(module, "download_artifact", _fake_download_artifact)
    evidence = module.refresh_evidence(
        repo="ThalesGroup/agilab",
        branch="main",
        run_id=None,
        run_limit=1,
        artifact_dir=None,
        repo_root=tmp_path,
    )

    assert evidence["result"]["trend"]["schema"] == module.TREND_REPORT_SCHEMA


def test_refresh_evidence_rejects_expired_artifact(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "fetch_run", lambda run_id, *, repo, repo_root: _successful_run())
    monkeypatch.setattr(module, "fetch_artifact_metadata", lambda run_id, *, repo, repo_root: {**_artifact(), "expired": True})

    with pytest.raises(RuntimeError, match="expired"):
        module.refresh_evidence(
            repo="ThalesGroup/agilab",
            branch=None,
            run_id="25577485125",
            run_limit=1,
            artifact_dir=tmp_path,
            repo_root=tmp_path,
        )


def test_main_refresh_quiet_writes_evidence(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    artifact_root = _write_artifact_payloads(tmp_path / "artifact")
    output = tmp_path / "ui_robot_evidence.json"
    monkeypatch.setattr(module, "fetch_latest_successful_run", lambda *, repo, branch, limit, repo_root: _successful_run())
    monkeypatch.setattr(module, "fetch_artifact_metadata", lambda run_id, *, repo, repo_root: _artifact())

    exit_code = module.main(["--artifact-dir", str(artifact_root), "--output", str(output), "--quiet"])

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == module.SCHEMA


def test_load_artifact_payloads_reports_external_files_by_name(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_dir = tmp_path / "selected-artifact"
    artifact_dir.mkdir()
    external_artifact = _write_artifact_payloads(tmp_path / "external-artifact")

    def _fake_find_artifact_file(_root: Path, filename: str) -> Path:
        matches = list(external_artifact.rglob(filename))
        assert matches
        return matches[0]

    monkeypatch.setattr(module, "_find_artifact_file", _fake_find_artifact_file)

    _, _, _, artifact_checks = module.load_artifact_payloads(artifact_dir)

    assert artifact_checks["matrix_summary_file"] == "summary.json"
    assert artifact_checks["progress_log_file"] == "isolated-core-pages.ndjson"


def test_main_check_pretty_prints_and_status_helper(tmp_path: Path, capsys) -> None:
    module = _load_module()
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=_matrix_summary(),
        scenario_summary=_scenario_summary(),
        trend_report=_trend_report(),
        artifact_checks={
            "required_files_present": True,
            "exit_code": "0",
            "progress_log_bytes": 3,
            "trend_report_schema": "agilab.ui_robot_trend_report.v1",
        },
        generated_at="2026-05-08T20:30:00Z",
    )
    output = tmp_path / "ui_robot_evidence.json"
    module.write_evidence(output, evidence)

    assert module.evidence_status(evidence) == "pass"
    assert module.main(["--check", "--output", str(output)]) == 0

    stdout = capsys.readouterr().out
    assert '"status": "pass"' in stdout
    failed_evidence = {
        **evidence,
        "artifact": {**evidence["artifact"], "required_files_present": False},
    }
    assert module.evidence_status(failed_evidence) == "fail"


def test_script_entrypoint_exits_with_main_status(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    evidence = module.build_evidence(
        run=_successful_run(),
        artifact=_artifact(),
        matrix_summary=_matrix_summary(),
        scenario_summary=_scenario_summary(),
        trend_report=_trend_report(),
        artifact_checks={
            "required_files_present": True,
            "exit_code": "0",
            "progress_log_bytes": 3,
            "trend_report_schema": "agilab.ui_robot_trend_report.v1",
        },
        generated_at="2026-05-08T20:30:00Z",
    )
    output = tmp_path / "ui_robot_evidence.json"
    module.write_evidence(output, evidence)
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "--check", "--output", str(output), "--quiet"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")

    assert exc_info.value.code == 0
