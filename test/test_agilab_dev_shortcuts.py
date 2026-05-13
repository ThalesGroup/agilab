from __future__ import annotations

import importlib.util
from pathlib import Path


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
            "tools/impact_validate.py",
            "--staged",
        ],
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
    ]


def test_bugfix_shortcut_keeps_changed_file_arguments():
    assert agilab_dev.planned_commands(["bugfix", "--files", "src/agilab/main_page.py"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/impact_validate.py",
            "--files",
            "src/agilab/main_page.py",
        ],
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/ga_regression_selector.py",
            "--files",
            "src/agilab/main_page.py",
            "--run",
        ],
    ]


def test_test_shortcut_keeps_pytest_arguments():
    assert agilab_dev.planned_commands(["test", "test/test_cluster_lan_discovery.py", "-k", "windows"]) == [
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "pytest",
            "-q",
            "test/test_cluster_lan_discovery.py",
            "-k",
            "windows",
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
    assert agilab_dev.planned_commands(["regress", "--files", "src/agilab/pipeline_ai.py", "--json"]) == [
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


def test_main_keeps_machine_readable_shortcut_stdout_clean(capsys, monkeypatch):
    calls = []

    class Completed:
        returncode = 0

    def fake_run(command, *, cwd):
        calls.append((command, cwd))
        return Completed()

    monkeypatch.setattr(agilab_dev.subprocess, "run", fake_run)

    exit_code = agilab_dev.main(["regress", "--files", "src/agilab/pipeline_ai.py", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert "tools/ga_regression_selector.py" in captured.err
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


def test_release_shortcut_runs_local_release_guards():
    assert agilab_dev.planned_commands(["release"]) == [
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
            "tools/pypi_trusted_publisher_contract.py",
            "--check-workflow",
            ".github/workflows/pypi-publish.yaml",
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
            "--profile",
            "badges",
        ],
    ]


def test_release_shortcut_keeps_impact_arguments():
    assert agilab_dev.planned_commands(["release", "--files", "pyproject.toml"])[0] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/impact_validate.py",
        "--files",
        "pyproject.toml",
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


def test_skills_shortcut_syncs_then_validates_and_generates():
    assert agilab_dev.planned_commands(["skills", "agilab-runbook"]) == [
        ["python3", "tools/sync_agent_skills.py", "--skills", "agilab-runbook"],
        ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "validate", "--strict"],
        ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "generate"],
    ]


def test_legacy_mnemonic_aliases_are_removed():
    for alias in ("iv", "pt", "wp", "bg", "ds", "sk", "ga"):
        try:
            agilab_dev.planned_commands([alias])
        except SystemExit as exc:
            assert str(exc) == f"unknown shortcut: {alias}"
        else:
            raise AssertionError(f"{alias} should not be accepted")
