from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path


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
) -> None:
    module = _load_module()
    docs_source = tmp_path / "docs" / "source"
    data_dir = docs_source / "data"
    data_dir.mkdir(parents=True)
    shutil.copyfile(Path("docs/source/data/release_proof.toml"), data_dir / "release_proof.toml")

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
            "--check",
            "--compact",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    refreshed = module.load_manifest(data_dir / "release_proof.toml")
    assert exit_code == 0
    assert payload["status"] == "pass"
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
