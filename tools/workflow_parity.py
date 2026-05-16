#!/usr/bin/env python3
"""Run local equivalents of key AGILAB workflow checks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
AGI_GUI_COVERAGE_CHUNKS = ("support", "pipeline", "robots", "pages", "views", "reports")


@dataclass
class CommandSpec:
    label: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int | None = None
    cwd: str | None = None
    ensure_dirs: list[str] = field(default_factory=list)
    remove_paths: list[str] = field(default_factory=list)


@dataclass
class CommandResult:
    label: str
    argv: list[str]
    returncode: int
    duration_seconds: float
    cwd: str
    env: dict[str, str]


@dataclass
class ProfileResult:
    profile: str
    description: str
    success: bool
    commands: list[CommandResult]


def _expand_repo_globs(paths: Sequence[str]) -> list[str]:
    expanded: list[str] = []
    for path in paths:
        if any(token in path for token in "*?["):
            matches = sorted(REPO_ROOT.glob(path))
            if matches:
                expanded.extend(match.relative_to(REPO_ROOT).as_posix() for match in matches)
                continue
        expanded.append(path)
    return expanded


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run local equivalents of key AGILAB workflow checks so local validation "
            "matches the real repo workflows more closely."
        )
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=[
            "agi-env",
            "agi-core-combined",
            "agi-node",
            "agi-cluster",
            "agi-gui",
            "docs",
            "badges",
            "skills",
            "installer",
            "shared-core-typing",
            "dependency-policy",
            "release-proof",
            "security-adoption",
            "cloud-emulators",
            "ui-robot-matrix",
        ],
        help="Parity profile to run. May be passed multiple times.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available profiles and exit.",
    )
    parser.add_argument(
        "--components",
        nargs="+",
        help="Optional component subset for the badges profile.",
    )
    parser.add_argument(
        "--skills",
        nargs="+",
        help="Optional shared skill names to sync before running the skills profile.",
    )
    parser.add_argument(
        "--app-path",
        help="Optional app project path for the installer profile contract check.",
    )
    parser.add_argument(
        "--worker-copy",
        help="Optional copied worker path for the installer profile contract check.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the commands for the selected profiles without executing them.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue running later profiles even if one command fails.",
    )
    return parser


def _profile_descriptions() -> dict[str, str]:
    return {
        "agi-env": "Run the local equivalent of the agi-env coverage workflow job.",
        "agi-core-combined": "Run the shared core test suite once and emit both agi-node and agi-cluster coverage XML files.",
        "agi-node": "Run the legacy standalone agi-node coverage slice.",
        "agi-cluster": "Run the legacy standalone agi-cluster coverage slice.",
        "agi-gui": "Run the local equivalent of the agi-gui coverage workflow job.",
        "docs": "Run the local equivalent of the docs-publish Sphinx build.",
        "badges": "Refresh component coverage badges from local coverage XML files.",
        "skills": "Validate and regenerate the repo Codex skill mirror outputs.",
        "installer": "Run local installer parity checks including shell syntax and contract checks.",
        "shared-core-typing": "Run the curated shared-core strict mypy slice.",
        "dependency-policy": "Run dependency hygiene checks for runtime and release manifests.",
        "release-proof": "Run expensive release-proof gates such as fresh-clone first-proof install validation.",
        "security-adoption": (
            "Write an advisory security-check JSON artifact; set "
            "AGILAB_SECURITY_CHECK_STRICT=1 to fail on warnings."
        ),
        "cloud-emulators": "Run account-free data connector emulator compatibility checks.",
        "ui-robot-matrix": "Run the opt-in full widget robot scenario matrix across public built-in apps.",
    }


def _profile_commands(args: argparse.Namespace) -> dict[str, list[CommandSpec]]:
    return {
        "agi-env": _agi_env_profile(),
        "agi-core-combined": _agi_core_combined_profile(),
        "agi-node": _agi_node_profile(),
        "agi-cluster": _agi_cluster_profile(),
        "agi-gui": _agi_gui_profile(),
        "docs": _docs_profile(),
        "badges": _badges_profile(args.components),
        "skills": _skills_profile(args.skills),
        "installer": _installer_profile(args.app_path, args.worker_copy),
        "shared-core-typing": _shared_core_typing_profile(),
        "dependency-policy": _dependency_policy_profile(),
        "release-proof": _release_proof_profile(),
        "security-adoption": _security_adoption_profile(),
        "cloud-emulators": _cloud_emulators_profile(),
        "ui-robot-matrix": _ui_robot_matrix_profile(),
    }


def _agi_gui_profile() -> list[CommandSpec]:
    commands = [
        _agi_gui_coverage_chunk(
            "support",
            [
                "src/agilab/test",
                "src/agilab/lib/agi-gui/test",
                "test/test_action_execution.py",
                "test/test_agent_run.py",
                "test/test_agent_tool_safety.py",
                "test/test_orchestrate_cluster.py",
                "test/test_orchestrate_distribution.py",
                "test/test_orchestrate_execute.py",
                "test/test_orchestrate_page_helpers.py",
                "test/test_orchestrate_page_state.py",
                "test/test_orchestrate_page_support.py",
                "test/test_orchestrate_services.py",
                "test/test_orchestrate_support.py",
                "test/test_analysis_page_helpers.py",
                "test/test_about_agilab_helpers.py",
                "test/test_app_template_registry.py",
                "test/test_code_editor_support.py",
                "test/test_cluster_flight_validation.py",
                "test/test_cluster_lan_discovery.py",
                "test/test_dag_distributed_submitter.py",
                "test/test_agilab_dev_shortcuts.py",
                "test/test_ga_regression_selector.py",
                "test/test_evidence_graph.py",
                "test/test_env_file_utils.py",
                "test/test_import_guard.py",
                "test/test_logging_utils.py",
                "test/test_page_bundle_registry.py",
                "test/test_pinned_expander.py",
                "test/test_security_check.py",
                "test/test_secret_uri.py",
                "test/test_snippet_registry.py",
                "test/test_runtime_diagnostics.py",
                "test/test_dag_execution_adapters.py",
                "test/test_dag_execution_registry.py",
                "test/test_dag_run_engine.py",
                "test/test_ui_public_bind_guard.py",
                "test/test_venv_linker.py",
                "test/test_workflow_run_manifest.py",
                "test/test_workflow_runtime_contract.py",
                "test/test_workflow_ui.py",
                "src/agilab/apps/builtin/uav_queue_project/test/test_uav_queue_project.py",
                "src/agilab/apps/builtin/uav_relay_queue_project/test/test_uav_relay_queue_project.py",
            ],
            clean=True,
        ),
        _agi_gui_coverage_chunk(
            "pipeline",
            [
                "test/test_first_proof_cli.py",
                "test/test_first_proof_wizard.py",
                "test/test_generated_actions.py",
                "test/test_notebook_colab_support.py",
                "test/test_notebook_import_doctor.py",
                "test/test_page_docs.py",
                "test/test_pipeline_ai.py",
                "test/test_pipeline_ai_support.py",
                "test/test_pipeline_editor.py",
                "test/test_pipeline_lab.py",
                "test/test_pipeline_mistral.py",
                "test/test_pipeline_openai.py",
                "test/test_pipeline_openai_compatible.py",
                "test/test_pipeline_page_state.py",
                "test/test_pipeline_recipe_memory.py",
                "test/test_pipeline_run_controls.py",
                "test/test_pipeline_runtime.py",
                "test/test_pipeline_service_guard.py",
                "test/test_pipeline_sidebar.py",
                "test/test_pipeline_stage_templates.py",
                "test/test_pipeline_stages.py",
                "test/test_pipeline_views.py",
                "test/test_multi_app_dag_draft.py",
                "test/test_multi_app_dag_templates.py",
                "test/test_tracking.py",
                "test/test_flight_telemetry_project_runtime_args.py",
            ],
        ),
        _agi_gui_coverage_chunk(
            "robots",
            [
                "test/test_agilab_web_robot.py",
                "test/test_agilab_widget_robot.py",
                "test/test_first_launch_robot.py",
                "test/test_screenshot_manifest.py",
            ],
        ),
        _agi_gui_coverage_chunk(
            "pages",
            [
                "test/test_ui_pages.py",
                "test/test_apps_pages_launcher.py",
                "test/test_app_args.py",
                "test/test_streamlit_args.py",
                "test/test_pagelib.py",
                "test/test_connector_registry.py",
                "test/test_page_project_selector.py",
                "test/test_run_manifest.py",
            ],
        ),
        _agi_gui_coverage_chunk("views", ["test/test_view*.py"]),
        _agi_gui_coverage_chunk(
            "reports",
            [
                "test/test_ci_provider_artifacts.py",
                "test/test_*_report.py",
            ],
        ),
        _agi_gui_coverage_combine(),
        CommandSpec(
            label="agi-gui coverage xml",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--group",
                "dev",
                "--extra",
                "ui",
                "--extra",
                "viz",
                "python",
                "-m",
                "coverage",
                "xml",
                "--rcfile=.coveragerc.agi-gui",
                "--data-file=.coverage.agi-gui",
                "-o",
                "coverage-agi-gui.xml",
            ],
            env={"AGILAB_DISABLE_BACKGROUND_SERVICES": "1"},
            timeout_seconds=5 * 60,
            ensure_dirs=["test-results"],
        ),
    ]
    return commands


def _agi_gui_coverage_combine() -> CommandSpec:
    chunk_bases = [
        f"test-results/coverage-agi-gui-{chunk}.db"
        for chunk in AGI_GUI_COVERAGE_CHUNKS
    ]
    combine_code = (
        "from pathlib import Path\n"
        "import subprocess, sys, time\n"
        f"chunk_bases = {chunk_bases!r}\n"
        "missing = []\n"
        "paths = []\n"
        "for _ in range(120):\n"
        "    missing = []\n"
        "    paths = []\n"
        "    for base in chunk_bases:\n"
        "        base_path = Path(base)\n"
        "        candidates = sorted(base_path.parent.glob(base_path.name + '*'))\n"
        "        candidates = [path for path in candidates if path.is_file() and path.stat().st_size > 0]\n"
        "        if not candidates:\n"
        "            missing.append(base)\n"
        "        paths.extend(str(path) for path in candidates)\n"
        "    if not missing:\n"
        "        break\n"
        "    time.sleep(0.5)\n"
        "if missing:\n"
        "    print('Missing agi-gui coverage chunks: ' + ', '.join(missing))\n"
        "    sys.exit(1)\n"
        "cmd = [sys.executable, '-m', 'coverage', 'combine', '--keep', "
        "'--data-file=.coverage.agi-gui', *paths]\n"
        "sys.exit(subprocess.run(cmd, check=False).returncode)\n"
    )
    return CommandSpec(
        label="agi-gui coverage combine",
        argv=[
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--group",
            "dev",
            "--extra",
            "ui",
            "--extra",
            "viz",
            "python",
            "-c",
            combine_code,
        ],
        env={"AGILAB_DISABLE_BACKGROUND_SERVICES": "1"},
        timeout_seconds=5 * 60,
        ensure_dirs=["test-results"],
    )


def _agi_gui_coverage_chunk(label: str, targets: Sequence[str], *, clean: bool = False) -> CommandSpec:
    expanded_targets = _expand_repo_globs(targets)
    junit_path = f"test-results/junit-agi-gui-{label}.xml"
    data_file = f"test-results/coverage-agi-gui-{label}.db"
    clean_paths = [
        ".coverage.agi-gui",
        "coverage-agi-gui.xml",
        *(f"test-results/coverage-agi-gui-{chunk}.db" for chunk in AGI_GUI_COVERAGE_CHUNKS),
        *(f"test-results/junit-agi-gui-{chunk}.xml" for chunk in AGI_GUI_COVERAGE_CHUNKS),
    ]
    return CommandSpec(
        label=f"agi-gui coverage ({label})",
        argv=[
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--group",
            "dev",
            "--extra",
            "ui",
            "--extra",
            "viz",
            "python",
            "-m",
            "coverage",
            "run",
            "--rcfile=.coveragerc.agi-gui",
            f"--data-file={data_file}",
            "--parallel-mode",
            "-m",
            "pytest",
            "-q",
            "--maxfail=1",
            "--disable-warnings",
            "-o",
            "addopts=",
            "-m",
            "not integration",
            f"--junitxml={junit_path}",
            "--ignore=src/agilab/test/test_model_returns_code.py",
            *expanded_targets,
        ],
        env={"AGILAB_DISABLE_BACKGROUND_SERVICES": "1"},
        timeout_seconds=8 * 60,
        ensure_dirs=["test-results"],
        remove_paths=(
            [*clean_paths, *(f"{path}.*" for path in clean_paths), junit_path]
            if clean
            else [data_file, f"{data_file}.*", junit_path]
        ),
    )


def _agi_env_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="agi-env coverage",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--no-project",
                "--with-editable",
                "./src/agilab/core/agi-env",
                "--with-editable",
                "./src/agilab/core/agi-node",
                "--with",
                "sqlalchemy",
                "--with",
                "streamlit",
                "--with",
                "pytest",
                "--with",
                "pytest-cov",
                "python",
                "-m",
                "pytest",
                "-q",
                "--maxfail=1",
                "--disable-warnings",
                "-o",
                "addopts=",
                "--cov=agi_env",
                "--cov-config=.coveragerc.agi-env",
                "--cov-report=xml:coverage-agi-env.xml",
                "src/agilab/core/agi-env/test",
            ],
            env={"COVERAGE_FILE": ".coverage.agi-env"},
            timeout_seconds=20 * 60,
            remove_paths=[".coverage.agi-env", "coverage-agi-env.xml"],
        )
    ]


def _agi_node_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="agi-node coverage",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--no-project",
                "--with-editable",
                "./src/agilab/core/agi-env",
                "--with-editable",
                "./src/agilab/core/agi-node",
                "--with-editable",
                "./src/agilab/core/agi-cluster",
                "--with-editable",
                "./src/agilab/core/agi-core",
                "--with",
                "sqlalchemy",
                "--with",
                "fastparquet",
                "--with",
                "pytest",
                "--with",
                "pytest-asyncio",
                "--with",
                "pytest-cov",
                "python",
                "-m",
                "pytest",
                "-q",
                "--maxfail=1",
                "--disable-warnings",
                "-o",
                "addopts=",
                "--cov=agi_node",
                "--cov-report=xml:coverage-agi-node.xml",
                "src/agilab/core/test",
            ],
            env={"COVERAGE_FILE": ".coverage.agi-node"},
            timeout_seconds=20 * 60,
            remove_paths=[".coverage.agi-node", "coverage-agi-node.xml"],
        )
    ]


def _agi_core_combined_profile() -> list[CommandSpec]:
    base_argv = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--no-project",
        "--with-editable",
        "./src/agilab/core/agi-env",
        "--with-editable",
        "./src/agilab/core/agi-node",
        "--with-editable",
        "./src/agilab/core/agi-cluster",
        "--with-editable",
        "./src/agilab/core/agi-core",
        "--with",
        "sqlalchemy",
        "--with",
        "fastparquet",
        "--with",
        "pytest",
        "--with",
        "pytest-asyncio",
        "--with",
        "coverage",
        "python",
        "-m",
        "coverage",
    ]
    return [
        CommandSpec(
            label="agi-node+agi-cluster combined coverage run",
            argv=[
                *base_argv,
                "run",
                "--data-file=.coverage.agi-core-combined",
                "--source=agi_node,agi_cluster",
                "-m",
                "pytest",
                "-q",
                "--maxfail=1",
                "--disable-warnings",
                "-o",
                "addopts=",
                "src/agilab/core/test",
            ],
            timeout_seconds=20 * 60,
            remove_paths=[
                ".coverage.agi-core-combined",
                "coverage-agi-node.xml",
                "coverage-agi-cluster.xml",
            ],
        ),
        CommandSpec(
            label="agi-node combined coverage xml",
            argv=[
                *base_argv,
                "xml",
                "--data-file=.coverage.agi-core-combined",
                "-o",
                "coverage-agi-node.xml",
                "--include=*/agi_node/*",
            ],
            timeout_seconds=5 * 60,
        ),
        CommandSpec(
            label="agi-cluster combined coverage xml",
            argv=[
                *base_argv,
                "xml",
                "--data-file=.coverage.agi-core-combined",
                "-o",
                "coverage-agi-cluster.xml",
                "--include=*/agi_cluster/*",
            ],
            timeout_seconds=5 * 60,
        ),
    ]


def _agi_cluster_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="agi-cluster coverage",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--no-project",
                "--with-editable",
                "./src/agilab/core/agi-env",
                "--with-editable",
                "./src/agilab/core/agi-node",
                "--with-editable",
                "./src/agilab/core/agi-cluster",
                "--with-editable",
                "./src/agilab/core/agi-core",
                "--with",
                "sqlalchemy",
                "--with",
                "fastparquet",
                "--with",
                "pytest",
                "--with",
                "pytest-asyncio",
                "--with",
                "pytest-cov",
                "python",
                "-m",
                "pytest",
                "-q",
                "--maxfail=1",
                "--disable-warnings",
                "-o",
                "addopts=",
                "--cov=agi_cluster",
                "--cov-report=xml:coverage-agi-cluster.xml",
                "src/agilab/core/test",
            ],
            env={"COVERAGE_FILE": ".coverage.agi-cluster"},
            timeout_seconds=20 * 60,
            remove_paths=[".coverage.agi-cluster", "coverage-agi-cluster.xml"],
        )
    ]


def _docs_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="release proof manifest check",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/release_proof_report.py",
                "--check",
                "--compact",
            ],
        ),
        CommandSpec(
            label="docs sphinx build",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "sphinx",
                "--with",
                "sphinx-rtd-theme",
                "--with",
                "myst-parser",
                "--with",
                "linkify-it-py",
                "--with",
                "sphinx-pyreverse",
                "--with",
                "sphinx-autodoc-typehints",
                "--with",
                "sphinx-design",
                "--with",
                "sphinx-tabs",
                "python",
                "-m",
                "sphinx",
                "-b",
                "html",
                "docs/source",
                "docs/html",
            ],
            remove_paths=["docs/html"],
        )
    ]


def _badges_profile(components: Sequence[str] | None) -> list[CommandSpec]:
    argv = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/generate_component_coverage_badges.py",
    ]
    if components:
        argv.extend(["--components", *components])
    return [
        CommandSpec(label="coverage badge refresh", argv=argv),
        CommandSpec(
            label="skill badge refresh",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/generate_skill_badges.py",
            ],
        ),
        CommandSpec(
            label="badge drift guard",
            argv=["git", "diff", "--exit-code", "--", "badges/"],
        ),
    ]


def _skills_profile(skills: Sequence[str] | None) -> list[CommandSpec]:
    commands: list[CommandSpec] = []
    if skills:
        commands.append(
            CommandSpec(
                label="sync shared skills",
                argv=["python3", "tools/sync_agent_skills.py", "--skills", *skills],
            )
        )
    commands.extend(
        [
            CommandSpec(
                label="validate codex skills",
                argv=["python3", "tools/codex_skills.py", "--root", ".codex/skills", "validate", "--strict"],
            ),
            CommandSpec(
                label="generate codex skills index",
                argv=["python3", "tools/codex_skills.py", "--root", ".codex/skills", "generate"],
            ),
        ]
    )
    return commands


def _installer_profile(app_path: str | None, worker_copy: str | None) -> list[CommandSpec]:
    commands = [
        CommandSpec(
            label="installer shell syntax",
            argv=["bash", "-n", "install.sh", "src/agilab/install_apps.sh"],
        ),
        CommandSpec(
            label="installer discovery tests",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "test/test_install_apps_discovery.py",
                "test/test_install_contract_check.py",
                "test/test_venv_linker.py",
            ],
        ),
    ]
    if app_path:
        argv = [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/install_contract_check.py",
            "--app-path",
            app_path,
        ]
        if worker_copy:
            argv.extend(["--worker-copy", worker_copy])
        commands.append(CommandSpec(label="installer contract check", argv=argv))
    return commands


def _shared_core_typing_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="shared-core strict typing",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "mypy",
                "python",
                "tools/shared_core_strict_typing.py",
            ],
        )
    ]


def _dependency_policy_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="dependency policy",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "test/test_pyproject_dependency_hygiene.py",
            ],
        )
    ]


def _release_proof_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="fresh source clone first-proof install",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "-m",
                "release_proof",
                "test/test_source_clone_regression.py::test_newcomer_first_proof_passes_from_fresh_source_clone",
            ],
            env={
                "AGILAB_RUN_RELEASE_PROOF_SLOW": "1",
                "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
                "OPENAI_API_KEY": "sk-test-release-proof-000000000000",
                "PYTHONUNBUFFERED": "1",
                "VIRTUAL_ENV": "",
            },
            timeout_seconds=15 * 60,
        )
    ]


def _security_adoption_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="security adoption check",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/security_adoption_check.py",
                "--output",
                "test-results/security-check.json",
            ],
            timeout_seconds=2 * 60,
            ensure_dirs=["test-results"],
            remove_paths=["test-results/security-check.json"],
        )
    ]


def _cloud_emulators_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="cloud emulator connector evidence",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/data_connector_cloud_emulator_report.py",
                "--compact",
            ],
        ),
        CommandSpec(
            label="cloud emulator connector tests",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "test/test_data_connector_cloud_emulator_report.py",
            ],
        ),
    ]


def _ui_robot_matrix_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui robot matrix",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-robot-matrix",
                "--screenshot-dir",
                "screenshots/ui-robot-matrix",
            ],
            timeout_seconds=60 * 60,
            remove_paths=["test-results/ui-robot-matrix", "screenshots/ui-robot-matrix"],
        )
    ]


def _selected_profiles(args: argparse.Namespace) -> list[str]:
    if args.profile:
        return args.profile
    opt_in_profiles = {"agi-node", "agi-cluster", "release-proof", "security-adoption", "ui-robot-matrix"}
    return [name for name in _profile_descriptions() if name not in opt_in_profiles]


def _prepare_command(spec: CommandSpec) -> None:
    for rel_dir in spec.ensure_dirs:
        (REPO_ROOT / rel_dir).mkdir(parents=True, exist_ok=True)
    for rel_path in spec.remove_paths:
        targets = (
            sorted(REPO_ROOT.glob(rel_path))
            if any(token in rel_path for token in "*?[")
            else [REPO_ROOT / rel_path]
        )
        for target in targets:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass


def _run_command(spec: CommandSpec) -> CommandResult:
    _prepare_command(spec)
    env = os.environ.copy()
    env.update(spec.env)
    cwd = REPO_ROOT / spec.cwd if spec.cwd else REPO_ROOT
    started = time.perf_counter()
    completed = subprocess.run(
        spec.argv,
        cwd=cwd,
        env=env,
        check=False,
        timeout=spec.timeout_seconds,
    )
    return CommandResult(
        label=spec.label,
        argv=spec.argv,
        returncode=completed.returncode,
        duration_seconds=time.perf_counter() - started,
        cwd=str(cwd),
        env=spec.env,
    )


def run_profiles(
    profile_names: Sequence[str],
    *,
    args: argparse.Namespace,
    runner: Callable[[CommandSpec], CommandResult] = _run_command,
) -> list[ProfileResult]:
    commands_by_profile = _profile_commands(args)
    descriptions = _profile_descriptions()
    results: list[ProfileResult] = []

    for profile in profile_names:
        command_results: list[CommandResult] = []
        success = True
        for spec in commands_by_profile[profile]:
            result = runner(spec)
            command_results.append(result)
            if result.returncode != 0:
                success = False
                break
        results.append(
            ProfileResult(
                profile=profile,
                description=descriptions[profile],
                success=success,
                commands=command_results,
            )
        )
        if not success and not args.keep_going:
            break
    return results


def _render_human(profile_names: Sequence[str], results: Sequence[ProfileResult], *, print_only: bool, args: argparse.Namespace) -> str:
    descriptions = _profile_descriptions()
    commands_by_profile = _profile_commands(args)
    lines: list[str] = []
    if print_only:
        lines.append("Selected profiles:")
        for profile in profile_names:
            lines.append(f"- {profile}: {descriptions[profile]}")
            for spec in commands_by_profile[profile]:
                rendered = " ".join(spec.argv)
                lines.append(f"  - {spec.label}: {rendered}")
        return "\n".join(lines)

    for result in results:
        status = "PASS" if result.success else "FAIL"
        lines.append(f"[{status}] {result.profile}: {result.description}")
        for command in result.commands:
            lines.append(
                f"- {command.label}: rc={command.returncode} in {command.duration_seconds:.2f}s"
            )
            lines.append(f"  - {' '.join(command.argv)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    descriptions = _profile_descriptions()

    if args.list_profiles:
        if args.json:
            print(json.dumps(descriptions, indent=2, sort_keys=True))
        else:
            for name, description in descriptions.items():
                print(f"{name}: {description}")
        return 0

    selected = _selected_profiles(args)
    if args.print_only:
        text = _render_human(selected, [], print_only=True, args=args)
        if args.json:
            payload = {
                "profiles": selected,
                "commands": {
                    profile: [asdict(spec) for spec in _profile_commands(args)[profile]]
                    for profile in selected
                },
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(text)
        return 0

    results = run_profiles(selected, args=args)
    if args.json:
        payload = {
            "profiles": selected,
            "results": [
                {
                    "profile": result.profile,
                    "description": result.description,
                    "success": result.success,
                    "commands": [asdict(command) for command in result.commands],
                }
                for result in results
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render_human(selected, results, print_only=False, args=args))

    return 0 if all(result.success for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
