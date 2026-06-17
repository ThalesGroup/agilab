from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "agilab_dev.py"

spec = importlib.util.spec_from_file_location("agilab_dev", MODULE_PATH)
assert spec is not None and spec.loader is not None
agilab_dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agilab_dev)


def test_impact_shortcut_defaults_to_staged():
    assert agilab_dev.planned_commands(["impact"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/impact_validate.py",
            "--staged",
        ]
    ]


def test_bugfix_shortcut_runs_impact_then_fast_regression_by_default():
    assert agilab_dev.planned_commands(["bugfix"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/bugfix_validate.py",
            "--staged",
            "--run",
        ],
    ]


def test_bugfix_shortcut_keeps_changed_file_arguments():
    assert agilab_dev.planned_commands(
        ["bugfix", "--files", "src/agilab/main_page.py"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/bugfix_validate.py",
            "--files",
            "src/agilab/main_page.py",
            "--run",
        ],
    ]


def test_test_shortcut_keeps_pytest_arguments():
    assert agilab_dev.planned_commands(
        ["test", "test/test_cluster_lan_discovery.py", "-k", "windows"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "--import-mode=importlib",
            "test/test_cluster_lan_discovery.py",
            "-k",
            "windows",
        ]
    ]


def test_lint_shortcut_provisions_ruff_from_dev_extra_by_default():
    assert agilab_dev.planned_commands(["lint"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--extra",
            "dev",
            "ruff",
            "check",
            *agilab_dev.DEFAULT_LINT_TARGETS,
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--extra",
            "dev",
            "ruff",
            "check",
            "--select",
            "F821,E9",
            *agilab_dev.DEFAULT_UNDEFINED_NAME_LINT_TARGETS,
        ],
    ]


def test_lint_shortcut_keeps_explicit_paths():
    assert agilab_dev.planned_commands(["lint", "src/agilab/main_page.py"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--extra",
            "dev",
            "ruff",
            "check",
            "src/agilab/main_page.py",
        ]
    ]


def test_ruff_shortcut_keeps_ruff_arguments():
    assert agilab_dev.planned_commands(["ruff", "--version"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--extra",
            "dev",
            "ruff",
            "--version",
        ]
    ]


def test_regress_shortcut_defaults_to_staged_ga_run():
    assert agilab_dev.planned_commands(["regress"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/ga_regression_selector.py",
            "--staged",
            "--run",
        ]
    ]


def test_regress_shortcut_keeps_selector_arguments():
    assert agilab_dev.planned_commands(
        ["regress", "--files", "src/agilab/pipeline_ai.py", "--json"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/ga_regression_selector.py",
            "--files",
            "src/agilab/pipeline_ai.py",
            "--json",
        ]
    ]


def test_robust_shortcut_runs_p0_robustness_matrix_by_default():
    assert agilab_dev.planned_commands(["robust"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/robustness_matrix.py",
        ]
    ]


def test_robust_shortcut_keeps_matrix_arguments():
    assert agilab_dev.planned_commands(
        [
            "robustness",
            "--scenario",
            "public_streamlit_bind_without_controls_refused",
            "--compact",
        ]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/robustness_matrix.py",
            "--scenario",
            "public_streamlit_bind_without_controls_refused",
            "--compact",
        ]
    ]


def test_parallel_stage_shortcut_runs_parallel_stage_tool():
    assert agilab_dev.planned_commands(
        ["parallel-stage", "--check", "parallel_stage.toml"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/parallel_stage.py",
            "--check",
            "parallel_stage.toml",
        ]
    ]


def test_parallel_stage_shortcut_has_parallel_alias():
    assert agilab_dev.planned_commands(["parallel", "--name", "stage"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/parallel_stage.py",
            "--name",
            "stage",
        ]
    ]


def test_app_contracts_shortcut_runs_contract_matrix_by_default():
    assert agilab_dev.planned_commands(["app-contracts"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/app_contract_matrix.py",
        ]
    ]


def test_app_contracts_shortcut_keeps_matrix_arguments():
    assert agilab_dev.planned_commands(["apps-contracts", "--compact"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/app_contract_matrix.py",
            "--compact",
        ]
    ]


def test_builtin_app_tests_shortcut_runs_app_local_runner():
    assert agilab_dev.planned_commands(
        ["builtin-app-tests", "--app", "weather_forecast_project"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/builtin_app_tests.py",
            "--app",
            "weather_forecast_project",
        ]
    ]


def test_maintenance_shortcut_runs_dashboard():
    assert agilab_dev.planned_commands(["maintenance", "--json"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/maintenance_dashboard.py",
            "--json",
        ]
    ]


def test_maintenance_shortcut_has_maintain_alias():
    assert agilab_dev.planned_commands(["maintain", "--strict"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/maintenance_dashboard.py",
            "--strict",
        ]
    ]


def test_warnings_shortcut_runs_validation_warning_report():
    assert agilab_dev.planned_commands(["warnings", "--strict"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/validation_warning_report.py",
            "--strict",
        ]
    ]


def test_memory_shortcut_runs_maintenance_memory():
    assert agilab_dev.planned_commands(["memory", "check", "--all"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/maintenance_memory.py",
            "check",
            "--all",
        ]
    ]


def test_audit_shortcut_runs_agilab_audit():
    assert agilab_dev.planned_commands(["audit", "--no-network"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/agilab_audit.py",
            "--no-network",
        ]
    ]


def test_audit_quality_shortcut_scores_markdown_audit():
    assert agilab_dev.planned_commands(
        ["audit-quality", "CODE_REVIEW.md", "--min-score", "90"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/audit_quality_evaluator.py",
            "CODE_REVIEW.md",
            "--min-score",
            "90",
        ]
    ]


def test_audit_quality_shortcut_defaults_to_preflight_without_file():
    assert agilab_dev.planned_commands(["audit-quality"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/audit_quality_evaluator.py",
            "--preflight",
        ]
    ]


def test_audit_preflight_shortcut_prints_architecture_preflight():
    assert agilab_dev.planned_commands(["audit-preflight"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/audit_quality_evaluator.py",
            "--preflight",
        ]
    ]


def test_dev_shortcuts_run_in_isolated_uv_environment(monkeypatch):
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    monkeypatch.delenv("UV_RUN_RECURSION_DEPTH", raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/stale-ui-venv")

    env = agilab_dev._subprocess_env()

    assert env["UV_PROJECT_ENVIRONMENT"] == str(
        agilab_dev.DEFAULT_DEV_UV_PROJECT_ENVIRONMENT
    )
    assert "VIRTUAL_ENV" not in env
    assert "UV_RUN_RECURSION_DEPTH" not in env


def test_dev_shortcuts_respect_explicit_uv_environment(monkeypatch):
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/tmp/custom-dev-venv")
    monkeypatch.setenv("AGILAB_DEV_UV_PROJECT_ENVIRONMENT", "/tmp/ignored")

    env = agilab_dev._subprocess_env()

    assert env["UV_PROJECT_ENVIRONMENT"] == "/tmp/custom-dev-venv"


def test_dev_shortcuts_allow_named_isolated_uv_environment(monkeypatch):
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    monkeypatch.setenv("AGILAB_DEV_UV_PROJECT_ENVIRONMENT", "/tmp/agilab-dev")

    env = agilab_dev._subprocess_env()

    assert env["UV_PROJECT_ENVIRONMENT"] == "/tmp/agilab-dev"


def test_main_keeps_machine_readable_shortcut_stdout_clean(
    capsys, monkeypatch, tmp_path
):
    calls = []

    class Completed:
        returncode = 0
        stdout = "ok\n"

    def fake_run(command, *, cwd, env, stdout, stderr, text, errors):
        calls.append(
            (
                command,
                cwd,
                env["UV_PROJECT_ENVIRONMENT"],
                "VIRTUAL_ENV" in env,
                "UV_RUN_RECURSION_DEPTH" in env,
            )
        )
        assert stdout is agilab_dev.subprocess.PIPE
        assert stderr is agilab_dev.subprocess.STDOUT
        assert text is True
        assert errors == "replace"
        return Completed()

    monkeypatch.setattr(agilab_dev.subprocess, "run", fake_run)
    monkeypatch.setattr(agilab_dev, "DEV_LOG_DIR", tmp_path)
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)

    exit_code = agilab_dev.main(
        ["regress", "--files", "src/agilab/pipeline_ai.py", "--json"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert "tools/ga_regression_selector.py" in captured.err
    assert "./dev compact-output: ok exit=0" in captured.err
    assert "ok\n" not in captured.err
    assert f"log={tmp_path}" in captured.err
    assert calls == [
        (
            [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/ga_regression_selector.py",
                "--files",
                "src/agilab/pipeline_ai.py",
                "--json",
            ],
            agilab_dev.ROOT,
            str(agilab_dev.DEFAULT_DEV_UV_PROJECT_ENVIRONMENT),
            False,
            False,
        )
    ]


def test_main_compact_output_prints_signal_summary_and_writes_full_log(
    capsys, monkeypatch, tmp_path
):
    class Completed:
        returncode = 1
        stdout = "\n".join(
            [
                "collecting tests",
                "line that should stay only in the artifact",
                "ERROR first failure",
                "Traceback (most recent call last)",
                "FAILED test_demo.py::test_demo",
                "short tail",
            ]
        )

    def fake_run(command, *, cwd, env, stdout, stderr, text, errors):
        assert env["UV_PROJECT_ENVIRONMENT"] == str(
            agilab_dev.DEFAULT_DEV_UV_PROJECT_ENVIRONMENT
        )
        return Completed()

    monkeypatch.setattr(agilab_dev.subprocess, "run", fake_run)
    monkeypatch.setattr(agilab_dev, "DEV_LOG_DIR", tmp_path)
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)

    exit_code = agilab_dev.main(["--summary-lines", "3", "test", "test_demo.py"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "ERROR first failure" in captured.err
    assert "FAILED test_demo.py::test_demo" in captured.err
    assert "omitted" in captured.err
    logs = list(tmp_path.glob("*.log"))
    assert len(logs) == 1
    assert "line that should stay only in the artifact" in logs[0].read_text(
        encoding="utf-8"
    )


def test_main_raw_output_keeps_streaming_subprocess_call(capsys, monkeypatch):
    calls = []

    class Completed:
        returncode = 0

    def fake_run(command, *, cwd, env):
        calls.append(
            (
                command,
                cwd,
                env["UV_PROJECT_ENVIRONMENT"],
                "VIRTUAL_ENV" in env,
                "UV_RUN_RECURSION_DEPTH" in env,
            )
        )
        return Completed()

    monkeypatch.setattr(agilab_dev.subprocess, "run", fake_run)
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)

    exit_code = agilab_dev.main(["--raw-output", "regress"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert "tools/ga_regression_selector.py --staged --run" in captured.err
    assert "./dev compact-output" not in captured.err
    assert calls == [
        (
            [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/ga_regression_selector.py",
                "--staged",
                "--run",
            ],
            agilab_dev.ROOT,
            str(agilab_dev.DEFAULT_DEV_UV_PROJECT_ENVIRONMENT),
            False,
            False,
        )
    ]


def test_main_print_only_keeps_command_on_stdout(capsys):
    exit_code = agilab_dev.main(["--print-only", "regress"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "tools/ga_regression_selector.py --staged --run" in captured.out


def test_workflow_profile_shortcut_repeats_profile_flags_and_keeps_options():
    assert agilab_dev.planned_commands(["flow", "agi-gui", "docs", "--keep-going"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/workflow_parity.py",
            "--profile",
            "agi-gui",
            "--profile",
            "docs",
            "--keep-going",
        ]
    ]


def test_ui_flow_shortcut_selects_ui_robot_profiles_from_changed_files():
    assert agilab_dev.planned_commands(
        ["ui-flow", "--changed-file", "src/agilab/pages/project.py"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/workflow_parity.py",
            "--select-ui-robot-profiles",
            "--changed-file",
            "src/agilab/pages/project.py",
        ]
    ]


def test_perf_startup_shortcut_uses_quick_startup_import_scenarios():
    command = agilab_dev.planned_commands(["perf-startup"])[0]

    assert command[:6] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/perf_smoke.py",
    ]
    assert command.count("--scenario") == 4
    assert "orchestrate-execute-import" in command
    assert command[-4:] == ["--repeats", "1", "--warmups", "0"]


def test_worker_reuse_shortcut_runs_worker_env_reuse_tool():
    assert agilab_dev.planned_commands(
        [
            "worker-reuse",
            "--worker-pyproject",
            "worker/pyproject.toml",
            "--worker-copy",
            "~/wenv/app_worker",
        ]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/worker_env_reuse.py",
            "--worker-pyproject",
            "worker/pyproject.toml",
            "--worker-copy",
            "~/wenv/app_worker",
        ]
    ]


def test_typing_shortcut_invokes_ty_typing_profile():
    assert agilab_dev.planned_commands(["typing"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/workflow_parity.py",
            "--profile",
            "ty-typing",
        ]
    ]


def test_release_shortcut_runs_local_release_guards():
    assert agilab_dev.planned_commands(["release"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/agilab_audit.py",
            "--strict",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/impact_validate.py",
            "--staged",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/release_plan.py",
            "--check-workflow",
            ".github/workflows/pypi-publish.yaml",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/pypi_release_version_policy.py",
            "--skip-existing-pypi",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/pypi_project_preflight.py",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/pypi_trusted_publisher_contract.py",
            "--check-workflow",
            ".github/workflows/pypi-publish.yaml",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--extra",
            "dev",
            "ruff",
            "--version",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/app_contract_matrix.py",
            "--quiet",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/workflow_parity.py",
            "--profile",
            "dependency-policy",
            "--profile",
            "shared-core-typing",
            "--profile",
            "docs",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/coverage_badge_guard.py",
            "--changed-only",
            "--require-fresh-xml",
        ],
    ]


def test_publish_testpypi_shortcut_runs_local_rehearsal_path():
    assert agilab_dev.planned_commands(["publish-testpypi"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/pypi_publish.py",
            "--repo",
            "testpypi",
            "--dist",
            "both",
            "--verbose",
            "--git-reset-on-failure",
            "--no-pypirc-check",
        ]
    ]


def test_publish_testpypi_shortcut_keeps_explicit_arguments():
    assert agilab_dev.planned_commands(
        ["publish-testpypi", "--dry-run", "--version", "2026.05.12"]
    ) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/pypi_publish.py",
            "--repo",
            "testpypi",
            "--dist",
            "both",
            "--verbose",
            "--git-reset-on-failure",
            "--no-pypirc-check",
            "--dry-run",
            "--version",
            "2026.05.12",
        ]
    ]


def test_publish_testpypi_shortcut_rejects_repo_override():
    with pytest.raises(SystemExit):
        agilab_dev.planned_commands(["publish-testpypi", "--repo", "pypi"])


def test_release_shortcut_keeps_impact_arguments():
    commands = agilab_dev.planned_commands(["release", "--files", "pyproject.toml"])

    assert commands[0] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/agilab_audit.py",
        "--strict",
    ]
    assert commands[1] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/impact_validate.py",
        "--files",
        "pyproject.toml",
    ]


def test_release_shortcut_routes_hotfix_options_to_release_policy():
    commands = agilab_dev.planned_commands(
        [
            "release",
            "--release-mode",
            "hotfix",
            "--impact-base-ref",
            "v2026.06.04",
            "--files",
            "pyproject.toml",
        ]
    )

    assert commands[1] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/impact_validate.py",
        "--files",
        "pyproject.toml",
    ]
    assert commands[2] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/release_plan.py",
        "--check-workflow",
        ".github/workflows/pypi-publish.yaml",
        "--skip-existing-pypi",
        "--impact-base-ref",
        "v2026.06.04",
    ]
    assert commands[3] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/pypi_release_version_policy.py",
        "--skip-existing-pypi",
        "--release-mode",
        "hotfix",
        "--impact-base-ref",
        "v2026.06.04",
    ]


def test_badge_guard_shortcut_uses_changed_only_fresh_xml_defaults():
    assert agilab_dev.planned_commands(["badge"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/coverage_badge_guard.py",
            "--changed-only",
            "--require-fresh-xml",
        ]
    ]


def test_docs_shortcut_syncs_and_verifies_mirror():
    assert agilab_dev.planned_commands(["docs"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/sync_docs_source.py",
            "--apply",
            "--delete",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/sync_docs_source.py",
            "--verify-stamp",
        ],
    ]


def test_clean_shortcut_runs_local_artifact_cleaner_dry_run_by_default():
    assert agilab_dev.planned_commands(["clean"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/clean_local_artifacts.py",
        ]
    ]


def test_clean_shortcut_keeps_apply_flag():
    assert agilab_dev.planned_commands(["clean", "--apply"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/clean_local_artifacts.py",
            "--apply",
        ]
    ]


def test_scope_shortcut_runs_worktree_scope_guard():
    assert agilab_dev.planned_commands(["scope", "--max-scopes", "1"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/worktree_scope_guard.py",
            "--max-scopes",
            "1",
        ]
    ]


def test_task_worktree_shortcut_requires_branch_and_keeps_arguments():
    try:
        agilab_dev.planned_commands(["task-worktree"])
    except SystemExit as exc:
        assert str(exc) == "task-worktree: branch name is required"
    else:
        raise AssertionError("task-worktree should require a branch")

    assert agilab_dev.planned_commands(["worktree", "fix/demo", "--print-only"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/task_worktree.py",
            "fix/demo",
            "--print-only",
        ]
    ]


def test_skills_shortcut_syncs_then_validates_and_generates():
    assert agilab_dev.planned_commands(["skills", "agilab-runbook"]) == [
        ["python3", "tools/sync_agent_skills.py", "--skills", "agilab-runbook"],
        [
            "python3",
            "tools/codex_skills.py",
            "--root",
            ".codex/skills",
            "validate",
            "--strict",
        ],
        ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "generate"],
        ["python3", "tools/agent_skill_catalog.py", "--apply"],
        ["python3", "tools/generate_skill_badges.py"],
        [
            "python3",
            "tools/agent_skill_quality_guard.py",
            "--roots",
            ".claude/skills",
            ".codex/skills",
            "--fail-on",
            "high",
        ],
        [
            "python3",
            "tools/skill_security_scan.py",
            "--roots",
            ".claude/skills",
            ".codex/skills",
            "--fail-on",
            "critical",
        ],
    ]


def test_legacy_mnemonic_aliases_are_removed():
    for alias in ("iv", "pt", "wp", "bg", "ds", "sk", "ga"):
        try:
            agilab_dev.planned_commands([alias])
        except SystemExit as exc:
            assert str(exc) == f"unknown shortcut: {alias}"
        else:
            raise AssertionError(f"{alias} should not be accepted")
