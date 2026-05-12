from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/release_proof_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "release_proof_report_test_module",
        MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_proof_manifest_renders_checked_in_page() -> None:
    module = _load_module()

    report = module.build_report(
        manifest_path=Path("docs/source/data/release_proof.toml"),
        output_path=Path("docs/source/release-proof.rst"),
    )

    assert report["status"] == "pass"
    assert report["summary"]["failed"] == 0
    assert {check["id"] for check in report["checks"]} >= {
        "pyproject_version",
        "pypi_badge_version",
        "changelog_release",
        "readme_release_proof_link",
        "ui_robot_evidence",
        "rendered_page",
    }


def test_release_proof_cli_check_emits_machine_readable_report(capsys) -> None:
    module = _load_module()

    assert module.main(["--check", "--compact"]) == 0

    payload = json.loads(capsys.readouterr().out)
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    assert payload["schema"] == module.SCHEMA
    assert payload["status"] == "pass"
    assert payload["release"]["package_version"] == manifest["release"]["package_version"]


def test_release_proof_refresh_from_local_updates_manifest_and_page(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    module = _load_module()
    original_text_contains = module._text_contains

    def _text_contains(path: Path, expected: str):
        if path.as_posix().endswith("badges/pypi-version-agilab.svg"):
            return True
        return original_text_contains(path, expected)

    monkeypatch.setattr(module, "_text_contains", _text_contains)
    docs_source = tmp_path / "docs" / "source"
    data_dir = docs_source / "data"
    data_dir.mkdir(parents=True)
    shutil.copyfile(Path("docs/source/data/release_proof.toml"), data_dir / "release_proof.toml")
    shutil.copyfile(Path("docs/source/data/ui_robot_evidence.json"), data_dir / "ui_robot_evidence.json")

    exit_code = module.main(
        [
            "--docs-source",
            str(docs_source),
            "--refresh-from-local",
            "--github-release-tag",
            "v2026.05.01-2",
            "--hf-space-commit",
            "test-hf-commit",
            "--render",
            "--compact",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    refreshed = module.load_manifest(data_dir / "release_proof.toml")
    assert exit_code == 0
    assert payload["release"]["package_version"] == module._load_project_version(Path.cwd())
    assert refreshed["release"]["package_version"] == module._load_project_version(Path.cwd())
    assert refreshed["release"]["github_release_tag"] == "v2026.05.01-2"
    assert refreshed["release"]["github_release_url"].endswith("/releases/tag/v2026.05.01-2")
    assert refreshed["release"]["hf_space_commit"] == "test-hf-commit"
    assert (docs_source / "release-proof.rst").read_text(encoding="utf-8") == module.render_release_proof(
        refreshed
    )


def test_release_proof_refresh_from_github_updates_ci_runs(monkeypatch) -> None:
    module = _load_module()
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))

    rows = [
        {
            "databaseId": 101,
            "workflowName": "repo-guardrails",
            "headSha": "abc123",
            "status": "completed",
            "conclusion": "failure",
            "url": "https://github.com/ThalesGroup/agilab/actions/runs/101",
            "createdAt": "2026-05-01T10:00:00Z",
            "event": "push",
        },
        {
            "databaseId": 102,
            "workflowName": "repo-guardrails",
            "headSha": "abc123",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/ThalesGroup/agilab/actions/runs/102",
            "createdAt": "2026-05-01T10:01:00Z",
            "event": "push",
        },
        {
            "databaseId": 103,
            "workflowName": "docs-source-guard",
            "headSha": "abc123",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/ThalesGroup/agilab/actions/runs/103",
            "createdAt": "2026-05-01T10:02:00Z",
            "event": "push",
        },
        {
            "databaseId": 104,
            "workflowName": "docs-publish",
            "headSha": "abc123",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/ThalesGroup/agilab/actions/runs/104",
            "createdAt": "2026-05-01T10:03:00Z",
            "event": "push",
        },
        {
            "databaseId": 105,
            "workflowName": "coverage",
            "headSha": "abc123",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/ThalesGroup/agilab/actions/runs/105",
            "createdAt": "2026-05-01T10:04:00Z",
            "event": "push",
        },
    ]

    def fake_gh_json(args):
        assert args[:2] == ["run", "list"]
        assert "--branch" in args
        return rows

    monkeypatch.setattr(module, "_run_gh_json", fake_gh_json)

    refreshed = module.refresh_manifest_from_github(
        manifest,
        github_repo="ThalesGroup/agilab",
        github_branch="main",
        github_head_sha="abc123",
    )

    by_workflow = {run["workflow"]: run for run in refreshed["ci_runs"]}
    assert by_workflow["repo-guardrails"]["id"] == "release-guardrails"
    assert by_workflow["repo-guardrails"]["run_id"] == "102"
    assert by_workflow["docs-source-guard"]["run_id"] == "103"
    assert by_workflow["docs-publish"]["run_id"] == "104"
    assert by_workflow["coverage"]["run_id"] == "105"
    assert [run["workflow"] for run in refreshed["ci_runs"]].count("repo-guardrails") == 1


def test_release_proof_github_run_check_detects_failed_or_stale_runs(monkeypatch) -> None:
    module = _load_module()

    def fake_gh_json(args):
        assert args[:2] == ["run", "view"]
        return {
            "databaseId": args[2],
            "workflowName": "repo-guardrails",
            "headSha": "abc123",
            "status": "completed",
            "conclusion": "failure",
            "url": f"https://github.com/ThalesGroup/agilab/actions/runs/{args[2]}",
            "createdAt": "2020-01-01T00:00:00Z",
            "event": "push",
        }

    monkeypatch.setattr(module, "_run_gh_json", fake_gh_json)

    check = module._github_ci_runs_check(
        [
            {
                "workflow": "repo-guardrails",
                "run_id": "42",
                "url": "https://github.com/ThalesGroup/agilab/actions/runs/42",
            }
        ],
        repo_root=Path.cwd(),
        github_repo="ThalesGroup/agilab",
        max_age_days=1,
    )

    assert check["status"] == "fail"
    assert "not successful" in " ".join(check["details"]["failures"])
    assert "stale" in " ".join(check["details"]["failures"])


def test_release_proof_ui_robot_evidence_check_validates_github_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    ui_robot_evidence = module._load_ui_robot_evidence_module()
    run = {
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
    evidence = ui_robot_evidence.build_evidence(
        run=run,
        artifact={
            "name": "ui-robot-matrix-1",
            "expired": False,
            "size_bytes": 4902,
            "archive_download_url": "https://api.github.com/repos/ThalesGroup/agilab/actions/artifacts/1/zip",
        },
        matrix_summary={
            "success": True,
            "failed_count": 0,
            "failed_scenarios": [],
            "failure_samples": [],
        },
        scenario_summary={
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
        },
        artifact_checks={
            "required_files_present": True,
            "exit_code": "0",
            "progress_log_bytes": 3,
        },
        generated_at="2026-05-08T20:30:00Z",
    )
    evidence_path = tmp_path / "ui_robot_evidence.json"
    ui_robot_evidence.write_evidence(evidence_path, evidence)

    def fake_gh_json(args):
        assert args[:2] == ["run", "view"]
        return run

    monkeypatch.setattr(module, "_run_gh_json", fake_gh_json)

    check = module._ui_robot_evidence_check(
        evidence_path,
        repo_root=Path.cwd(),
        github_repo="ThalesGroup/agilab",
        check_github_runs=True,
    )

    assert check["status"] == "pass"
    assert check["details"]["run_id"] == "25577485125"
    assert check["details"]["failed_count"] == 0


def test_release_proof_renderer_fails_unknown_template_key(tmp_path: Path) -> None:
    module = _load_module()
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    manifest["proof_command"]["commands"] = ["python -m pip install {missing_key}"]

    try:
        module.render_release_proof(manifest)
    except KeyError as exc:
        assert "missing_key" in str(exc)
    else:
        raise AssertionError("unknown template key should fail rendering")


def test_release_proof_manifest_and_toml_helpers_fail_clearly(tmp_path: Path) -> None:
    module = _load_module()
    invalid_manifest = tmp_path / "release_proof.toml"
    invalid_manifest.write_text('schema = "wrong.schema"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="agilab.release_proof.v1"):
        module.load_manifest(invalid_manifest)
    with pytest.raises(KeyError, match="unknown release proof template key"):
        module._SafeFormatDict().__missing__("missing")
    with pytest.raises(TypeError, match="unsupported TOML scalar"):
        module._format_toml_scalar(object())
    with pytest.raises(TypeError, match="mapping values"):
        module._format_toml_list_item({"key": "value"})
    with pytest.raises(TypeError, match="array table"):
        module._dump_toml_key_value([], "items", [{"key": "value"}])
    with pytest.raises(TypeError, match="must be emitted as a table"):
        module._dump_toml_key_value([], "table", {"key": "value"})


def test_release_proof_version_comparison_accepts_package_lag() -> None:
    module = _load_module()

    assert module._version_key("2026.05.11-2") == (2026, 5, 11, 2)
    assert module._version_key("no-version") is None
    assert module._version_not_newer("2026.05.11", "2026.05.11")
    assert module._version_not_newer("2026.05.11", "2026.05.12")
    assert module._version_not_newer("2026.05", "2026.05.0")
    assert not module._version_not_newer("2026.05.12", "2026.05.11")
    assert module._version_not_newer("snapshot", "snapshot")
    assert not module._version_not_newer("snapshot", "release")


def test_release_proof_load_project_version_handles_missing_or_invalid_pyproject(
    tmp_path: Path,
) -> None:
    module = _load_module()

    assert module._load_project_version(tmp_path) is None
    (tmp_path / "pyproject.toml").write_text("project = []\n", encoding="utf-8")
    assert module._load_project_version(tmp_path) is None
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    assert module._load_project_version(tmp_path) is None
