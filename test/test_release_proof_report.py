from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime
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


def test_release_proof_manifest_renders_checked_in_page(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_local_release_app_count",
        lambda _repo_root, _release_ref: 15,
    )

    report = module.build_report(
        manifest_path=Path("docs/source/data/release_proof.toml"),
        output_path=Path("docs/source/release-proof.rst"),
    )

    assert report["status"] == "pass"
    assert report["summary"]["failed"] == 0
    assert {check["id"] for check in report["checks"]} >= {
        "pyproject_version",
        "pypi_badge_version",
        "release_app_inventory",
        "dataset_manifest",
        "changelog_release",
        "readme_release_proof_link",
        "ui_robot_evidence",
        "rendered_page",
    }
    release_apps = next(
        check for check in report["checks"] if check["id"] == "release_app_inventory"
    )
    assert release_apps["details"] == {
        "expected_app_count": 15,
        "local_release_app_count": 15,
    }


def test_release_proof_allows_unavailable_local_tag_tree(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_local_release_app_count",
        lambda _repo_root, _release_ref: None,
    )

    report = module.build_report(
        manifest_path=Path("docs/source/data/release_proof.toml"),
        output_path=Path("docs/source/release-proof.rst"),
    )

    release_apps = next(
        check for check in report["checks"] if check["id"] == "release_app_inventory"
    )
    assert report["status"] == "pass"
    assert release_apps["status"] == "pass"
    assert release_apps["summary"] == (
        "manifest records the release app count; local tag tree is unavailable"
    )
    assert release_apps["details"] == {
        "expected_app_count": 15,
        "local_release_app_count": None,
    }


def test_release_proof_renders_ui_robot_run_provenance(tmp_path: Path) -> None:
    module = _load_module()
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    evidence_path = tmp_path / "ui_robot_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-08T20:34:30Z",
                "source": {
                    "run_id": "25577485125",
                    "head_sha": "2a36df530b48ce992fdd1c388d47ab0f46b5239a",
                },
                "result": {"app_count": 10},
            }
        ),
        encoding="utf-8",
    )

    # Collapse line-wrapping so the assertions are whitespace-insensitive.
    with_prov = " ".join(module.render_release_proof(manifest, ui_robot_evidence_path=evidence_path).split())
    without_prov = module.render_release_proof(manifest)

    # Historical evidence is surfaced without claiming it proves this release.
    assert "Historical UI robot baseline: run ``25577485125``" in with_prov
    assert "commit ``2a36df530b48``" in with_prov
    assert "generated ``2026-05-08T20:34:30Z``" in with_prov
    assert "records ``10`` apps" in with_prov
    assert "not UI proof for this release" in with_prov
    # Provenance is absent when no evidence file is available.
    assert "Historical UI robot baseline" not in without_prov


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
    monkeypatch.setattr(module, "_local_tag_exists", lambda _repo_root, _tag: True)
    monkeypatch.setattr(
        module,
        "_local_tag_commit",
        lambda _repo_root, _tag: "test-release-commit",
    )
    monkeypatch.setattr(
        module,
        "_local_release_app_count",
        lambda _repo_root, _tag: 14,
    )
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
    assert refreshed["release"]["source_version_relation"] == "exact"
    assert refreshed["release"]["github_release_tag"] == "v2026.05.01-2"
    assert refreshed["release"]["github_release_url"].endswith("/releases/tag/v2026.05.01-2")
    assert refreshed["release"]["github_release_commit"] == "test-release-commit"
    assert refreshed["ui_robot"]["expected_app_count"] == 14
    dataset_release_tag = refreshed["release"]["dataset_release_tag"]
    assert dataset_release_tag.startswith("datasets-")
    assert refreshed["release"]["dataset_release_url"].endswith(
        f"/releases/tag/{dataset_release_tag}"
    )
    assert refreshed["release"]["dataset_count"] > 0
    assert refreshed["release"]["hf_space_commit"] == "test-hf-commit"
    rendered = (docs_source / "release-proof.rst").read_text(encoding="utf-8")
    assert "14-app release inventory" in " ".join(rendered.split())
    assert rendered == module.render_release_proof(
        refreshed,
        ui_robot_evidence_path=data_dir / "ui_robot_evidence.json",
    )


def test_release_proof_refresh_drops_stale_commit_for_unresolved_new_tag(
    tmp_path: Path,
) -> None:
    module = _load_module()
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    manifest["release"]["github_release_commit"] = "stale-commit"

    refreshed = module.refresh_manifest_from_local(
        manifest,
        repo_root=tmp_path,
        github_release_tag="v2099.01.01",
    )

    assert refreshed["release"]["github_release_tag"] == "v2099.01.01"
    assert "github_release_commit" not in refreshed["release"]


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
    assert by_workflow["repo-guardrails"]["head_sha"] == "abc123"
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
                "head_sha": "abc123",
            }
        ],
        repo_root=Path.cwd(),
        github_repo="ThalesGroup/agilab",
        max_age_days=1,
    )

    assert check["status"] == "fail"
    assert "not successful" in " ".join(check["details"]["failures"])
    assert "stale" in " ".join(check["details"]["failures"])


def test_release_proof_github_run_check_accepts_workflow_file_fallback_name(monkeypatch) -> None:
    module = _load_module()

    def fake_gh_json(args):
        assert args[:2] == ["run", "view"]
        return {
            "databaseId": args[2],
            "workflowName": ".github/workflows/pypi-publish.yaml",
            "headSha": "abc123",
            "status": "completed",
            "conclusion": "success",
            "url": f"https://github.com/ThalesGroup/agilab/actions/runs/{args[2]}",
            "createdAt": "2026-06-04T00:00:00Z",
            "event": "workflow_dispatch",
        }

    monkeypatch.setattr(module, "_run_gh_json", fake_gh_json)

    check = module._github_ci_runs_check(
        [
            {
                "workflow": "pypi-publish",
                "run_id": "42",
                "url": "https://github.com/ThalesGroup/agilab/actions/runs/42",
                "head_sha": "abc123",
            }
        ],
        repo_root=Path.cwd(),
        github_repo="ThalesGroup/agilab",
        max_age_days=45,
        now=datetime(2026, 6, 5, tzinfo=UTC),
    )

    assert check["status"] == "pass"

    mismatch = module._github_ci_runs_check(
        [
            {
                "workflow": "pypi-publish",
                "run_id": "42",
                "url": "https://github.com/ThalesGroup/agilab/actions/runs/42",
                "head_sha": "different",
            }
        ],
        repo_root=Path.cwd(),
        github_repo="ThalesGroup/agilab",
        max_age_days=45,
        now=datetime(2026, 6, 5, tzinfo=UTC),
    )
    assert mismatch["status"] == "fail"
    assert "head_sha differs" in " ".join(mismatch["details"]["failures"])


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
        trend_report={
            "schema": ui_robot_evidence.TREND_REPORT_SCHEMA,
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
        },
        artifact_checks={
            "required_files_present": True,
            "exit_code": "0",
            "progress_log_bytes": 3,
            "trend_report_schema": ui_robot_evidence.TREND_REPORT_SCHEMA,
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
        release={"github_release_commit": "abc123"},
        ui_robot={"mode": "release", "expected_app_count": 10},
        repo_root=Path.cwd(),
        github_repo="ThalesGroup/agilab",
        check_github_runs=True,
    )

    assert check["status"] == "pass"
    assert check["details"]["run_id"] == "25577485125"
    assert check["details"]["failed_count"] == 0


def test_release_proof_ui_robot_historical_mode_is_not_release_proof() -> None:
    module = _load_module()
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    release = manifest["release"]
    ui_robot = manifest["ui_robot"]
    evidence_path = Path("docs/source/data/ui_robot_evidence.json")

    historical_check = module._ui_robot_evidence_check(
        evidence_path,
        release=release,
        ui_robot=ui_robot,
        repo_root=Path.cwd(),
        github_repo=None,
        check_github_runs=False,
    )
    release_check = module._ui_robot_evidence_check(
        evidence_path,
        release=release,
        ui_robot={"mode": "release", "expected_app_count": 15},
        repo_root=Path.cwd(),
        github_repo=None,
        check_github_runs=False,
    )

    assert historical_check["status"] == "pass"
    assert historical_check["details"]["mode"] == "historical"
    assert historical_check["details"]["app_count"] == 10
    assert historical_check["details"]["expected_app_count"] == 15
    assert historical_check["details"]["represents_release"] is False
    assert "not proof for the current release" in historical_check["summary"]
    assert release_check["status"] == "fail"
    failures = " ".join(release_check["details"]["failures"])
    assert "head SHA" in failures
    assert "app_count" in failures


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

    assert module._format_toml_scalar(True) == "true"
    assert module._format_toml_scalar(7) == "7"
    empty_list_lines: list[str] = []
    module._dump_toml_key_value(empty_list_lines, "items", [])
    assert empty_list_lines == ["items = []"]
    manifest_text = module.dump_manifest(
        {
            "schema": module.SCHEMA,
            "release": {"package_name": "agilab", "package_version": "2026.05.11"},
            "ci_runs": [{"workflow": "coverage", "run_id": "1"}],
        }
    )
    assert "[release]" in manifest_text
    assert "[[ci_runs]]" in manifest_text

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
    with pytest.raises(TypeError, match="release.*table"):
        module._template_context({"release": []})
    with pytest.raises(TypeError, match="package_extras"):
        module._template_context({"release": {"package_name": "agilab", "package_extras": "ui"}})
    with pytest.raises(TypeError, match="\\[missing\\]"):
        module._required_table("missing", {})
    with pytest.raises(TypeError, match="items"):
        module._required_list("items", {"items": "not-a-list"})

    wrapped: list[str] = []
    module._append_wrapped(wrapped, "", initial_indent="- ")
    assert wrapped == ["-"]


def test_release_proof_version_comparison_helpers() -> None:
    module = _load_module()

    assert module._version_key("2026.05.11-2") == (2026, 5, 11, 2)
    assert module._version_key("no-version") is None
    assert module._version_not_newer("2026.05.11", "2026.05.11")
    assert module._version_not_newer("2026.05.11", "2026.05.12")
    assert module._version_not_newer("2026.05", "2026.05.0")
    assert not module._version_not_newer("2026.05.12", "2026.05.11")
    assert module._version_not_newer("snapshot", "snapshot")
    assert not module._version_not_newer("snapshot", "release")
    assert not module._version_is_newer("snapshot", "release")


def test_release_proof_requires_exact_version_unless_source_ahead_is_explicit() -> None:
    module = _load_module()

    exact_release = {
        "package_version": "2026.07.17",
        "source_version_relation": "exact",
    }
    source_ahead_release = {
        "package_version": "2026.07.17",
        "source_version_relation": "ahead",
    }

    exact_passed, _summary, exact_details = module._source_version_check(
        exact_release,
        "2026.07.17",
    )
    stale_passed, _summary, _details = module._source_version_check(
        exact_release,
        "2026.07.17.1",
    )
    ahead_passed, _summary, ahead_details = module._source_version_check(
        source_ahead_release,
        "2026.07.17.1",
    )
    ahead_same_passed, _summary, _details = module._source_version_check(
        source_ahead_release,
        "2026.07.17",
    )

    assert exact_passed
    assert exact_details["exact_match"] is True
    assert not stale_passed
    assert ahead_passed
    assert ahead_details["source_version_relation"] == "ahead"
    assert not ahead_same_passed


def test_release_proof_source_ahead_rendering_is_explicit() -> None:
    module = _load_module()
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    manifest["release"]["source_version_relation"] = "ahead"

    rendered = " ".join(module.render_release_proof(manifest).split())

    assert "source checkout is intentionally ahead" in rendered
    assert "still describe that exact published release" in rendered


def test_release_proof_badge_version_does_not_accept_substring_collision(
    tmp_path: Path,
) -> None:
    module = _load_module()
    badge = tmp_path / "badge.svg"
    badge.write_text(
        '<svg role="img" aria-label="pypi: v2026.07.17.11"></svg>',
        encoding="utf-8",
    )

    assert module._pypi_badge_version(badge) == "2026.07.17.11"
    assert module._pypi_badge_version(badge) != "2026.07.17.1"


def test_release_proof_changelog_requires_latest_release_section() -> None:
    module = _load_module()
    historical_url = "https://example.test/releases/tag/v2026.07.17"
    changelog = (
        "# Changelog\n\n"
        "## Unreleased\n\n"
        "## [2026.07.17.1] - 2026-07-23\n\n"
        "GitHub Release: https://example.test/releases/tag/v2026.07.17_1\n\n"
        "## [2026.07.17] - 2026-07-17\n\n"
        f"GitHub Release: {historical_url}\n"
    )

    version, section = module._latest_changelog_release(changelog)

    assert version == "2026.07.17.1"
    assert f"GitHub Release: {historical_url}" not in section.splitlines()
    assert not module._changelog_section_has_release_url(section, historical_url)
    assert module._changelog_section_has_release_url(
        section,
        "https://example.test/releases/tag/v2026.07.17_1",
    )


def test_release_proof_load_project_version_handles_missing_or_invalid_pyproject(
    tmp_path: Path,
) -> None:
    module = _load_module()

    assert module._load_project_version(tmp_path) is None
    (tmp_path / "pyproject.toml").write_text("project = []\n", encoding="utf-8")
    assert module._load_project_version(tmp_path) is None
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    assert module._load_project_version(tmp_path) is None


def test_release_proof_github_and_git_helpers_cover_failure_paths(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    assert module._run_git(tmp_path, ["remote", "get-url", "origin"]) is None
    assert module._release_tag_prefix("draft") is None
    assert module._latest_local_release_tag(tmp_path, "draft") is None
    assert module._github_repo_base_url(tmp_path) is None
    with pytest.raises(RuntimeError, match="unable to infer GitHub repository"):
        module._resolve_github_repo(tmp_path, None)
    assert module._github_created_at("") is None
    assert module._github_created_at("not-a-date") is None

    monkeypatch.setattr(module, "_run_git", lambda _root, _args: "git@github.com:ThalesGroup/agilab.git")
    assert module._github_repo_base_url(tmp_path) == "https://github.com/ThalesGroup/agilab"
    assert module._github_repo_name(tmp_path) == "ThalesGroup/agilab"
    assert module._resolve_github_repo(tmp_path, "Owner/repo") == "Owner/repo"

    monkeypatch.setattr(module, "_run_git", lambda _root, _args: "ssh://example.com/repo.git")
    assert module._github_repo_base_url(tmp_path) is None


def test_release_proof_latest_successful_github_runs_filters_rows(monkeypatch) -> None:
    module = _load_module()

    rows = [
        "not-a-row",
        {"workflowName": "coverage", "headSha": "other", "status": "completed", "conclusion": "success"},
        {"workflowName": "coverage", "headSha": "abc", "status": "completed", "conclusion": "failure"},
        {
            "databaseId": 42,
            "workflowName": "coverage",
            "headSha": "abc",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/ThalesGroup/agilab/actions/runs/42",
            "createdAt": "2026-05-11T00:00:00Z",
            "event": "push",
        },
    ]
    monkeypatch.setattr(module, "_run_gh_json", lambda _args: rows)

    found = module._latest_successful_github_runs(
        repo="ThalesGroup/agilab",
        workflows=("coverage",),
        branch="main",
        head_sha="abc",
        limit=10,
    )
    assert found["coverage"]["databaseId"] == "42"

    monkeypatch.setattr(module, "_run_gh_json", lambda _args: {"not": "a-list"})
    with pytest.raises(RuntimeError, match="JSON list"):
        module._latest_successful_github_runs(
            repo="ThalesGroup/agilab",
            workflows=("coverage",),
            branch=None,
            head_sha=None,
            limit=10,
        )

    monkeypatch.setattr(module, "_run_gh_json", lambda _args: [])
    with pytest.raises(RuntimeError, match="missing successful GitHub workflow runs"):
        module._latest_successful_github_runs(
            repo="ThalesGroup/agilab",
            workflows=("coverage",),
            branch=None,
            head_sha="abc",
            limit=10,
        )
