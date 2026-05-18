#!/usr/bin/env python3
"""Run local equivalents of key AGILAB workflow checks."""

from __future__ import annotations

import argparse
import hashlib
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
RESULT_CACHE_SCHEMA = "agilab-workflow-parity-result-cache-v1"
DEFAULT_RESULT_CACHE_PATH = REPO_ROOT / ".pytest_cache" / "agilab" / "workflow_parity_results.json"
RESULT_CACHE_MAX_ENTRIES = 256
RESULT_CACHE_HASH_LIMIT_BYTES = 10 * 1024 * 1024
RESULT_CACHE_INPUT_GLOBS = (
    "pyproject.toml",
    "uv.lock",
    "tools/workflow_parity.py",
    "tools/agilab_dev.py",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
)
RESULT_CACHE_ENV_KEYS = (
    "AGILAB_DEFAULT_OPENAI_MODEL",
    "AGILAB_FORCE_APP_PAGE_SOURCE",
    "APPS_REPOSITORY",
    "CI",
    "PYTHONPATH",
    "UV_PROJECT_ENVIRONMENT",
    "UV_RUN_RECURSION_DEPTH",
    "VIRTUAL_ENV",
)
AGI_GUI_COVERAGE_CHUNKS = (
    "support",
    "pipeline",
    "robots",
    "pages-flow",
    "pages-rest",
    "views",
    "reports",
)
AGI_GUI_COVERAGE_MANIFEST_SCHEMA = "agilab.workflow_parity.agi_gui_coverage_chunk.v1"
AGI_GUI_COVERAGE_MANIFEST_WAIT_SECONDS = 10.0


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
            "production-readiness",
            "cloud-emulators",
            "ui-robot-contract",
            "ui-robot-canary",
            "ui-robot-matrix",
            "ui-artifact-capture-robot",
            "ui-history-robot",
            "ui-mobile-robot",
            "ui-release-evidence-robot",
            "ui-first-proof-robot",
            "ui-keyboard-robot",
            "ui-layout-robot",
            "ui-accessibility-robot",
            "ui-browser-error-robot",
            "ui-above-fold-robot",
            "ui-visual-baseline-robot",
            "ui-trend-robot",
            "ui-cross-browser-robot",
            "hf-install-robot",
            "hf-visual-smoke-robot",
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
    parser.add_argument(
        "--result-cache",
        action="store_true",
        help=(
            "Opt in to reusing successful local workflow parity results. Keep this "
            "disabled for artifact-generating profiles such as docs, badges, skills, "
            "and release checks."
        ),
    )
    parser.add_argument(
        "--result-cache-path",
        default=str(DEFAULT_RESULT_CACHE_PATH),
        help=(
            "Path for the local successful-result cache. The cache is keyed by "
            "selected profiles, command specs, workflow/tool fingerprints, and the dirty tree."
        ),
    )
    parser.add_argument(
        "--no-result-cache",
        action="store_true",
        help="Disable reuse and storage of successful workflow parity results.",
    )
    parser.add_argument(
        "--select-ui-robot-profiles",
        action="store_true",
        help="Select UI robot profiles from changed files instead of using the default profile set.",
    )
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Changed file to classify for --select-ui-robot-profiles. May be passed multiple times.",
    )
    parser.add_argument(
        "--changed-base",
        default="",
        help="Optional git base ref for --select-ui-robot-profiles. Defaults to the current dirty tree.",
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
        "production-readiness": (
            "Run the controlled-pilot readiness gate, including production-readiness "
            "evidence, hardening guardrails, and docs parity."
        ),
        "cloud-emulators": "Run account-free data connector emulator compatibility checks.",
        "ui-robot-contract": "Validate deterministic UI robot coverage contracts.",
        "ui-robot-canary": "Run deliberate UI robot fault-injection canaries.",
        "ui-robot-matrix": "Run the opt-in full widget robot scenario matrix across public built-in apps.",
        "ui-artifact-capture-robot": "Run a small widget robot smoke with trace, HAR, and video artifact capture enabled.",
        "ui-history-robot": "Run the opt-in browser-history, dark-theme, and session routing widget robot scenario.",
        "ui-mobile-robot": "Run the opt-in mobile viewport widget robot scenario.",
        "ui-release-evidence-robot": "Run opt-in success-screenshot, fresh-session, and performance-budget widget robot scenarios.",
        "ui-first-proof-robot": "Run the opt-in local first-proof golden-path widget robot for flight telemetry.",
        "ui-keyboard-robot": "Run the opt-in keyboard focus widget robot scenario.",
        "ui-layout-robot": "Run the opt-in desktop and mobile layout-integrity widget robot scenarios.",
        "ui-accessibility-robot": "Run the opt-in UI accessibility semantics widget robot scenario.",
        "ui-browser-error-robot": "Run the opt-in console, pageerror, requestfailed, and HTTP error widget robot scenario.",
        "ui-above-fold-robot": "Run the opt-in above-the-fold primary-target widget robot scenario.",
        "ui-visual-baseline-robot": "Capture masked UI screenshots and compare them with screenshot baselines.",
        "ui-trend-robot": "Summarize widget robot NDJSON progress logs for failures, flakes, and slow pages.",
        "ui-cross-browser-robot": "Run the opt-in Firefox and WebKit widget robot smoke scenarios.",
        "hf-install-robot": "Run the hosted Hugging Face flight telemetry INSTALL action robot.",
        "hf-visual-smoke-robot": "Capture hosted Hugging Face visual smoke screenshots without firing install actions.",
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
        "production-readiness": _production_readiness_profile(),
        "cloud-emulators": _cloud_emulators_profile(),
        "ui-robot-contract": _ui_robot_contract_profile(),
        "ui-robot-canary": _ui_robot_canary_profile(),
        "ui-robot-matrix": _ui_robot_matrix_profile(),
        "ui-artifact-capture-robot": _ui_artifact_capture_robot_profile(),
        "ui-history-robot": _ui_history_robot_profile(),
        "ui-mobile-robot": _ui_mobile_robot_profile(),
        "ui-release-evidence-robot": _ui_release_evidence_robot_profile(),
        "ui-first-proof-robot": _ui_first_proof_robot_profile(),
        "ui-keyboard-robot": _ui_keyboard_robot_profile(),
        "ui-layout-robot": _ui_layout_robot_profile(),
        "ui-accessibility-robot": _ui_accessibility_robot_profile(),
        "ui-browser-error-robot": _ui_browser_error_robot_profile(),
        "ui-above-fold-robot": _ui_above_fold_robot_profile(),
        "ui-visual-baseline-robot": _ui_visual_baseline_robot_profile(),
        "ui-trend-robot": _ui_trend_robot_profile(),
        "ui-cross-browser-robot": _ui_cross_browser_robot_profile(),
        "hf-install-robot": _hf_install_robot_profile(),
        "hf-visual-smoke-robot": _hf_visual_smoke_robot_profile(),
    }


UI_ROBOT_PROFILE_ORDER = (
    "ui-robot-contract",
    "ui-robot-canary",
    "ui-robot-matrix",
    "ui-artifact-capture-robot",
    "ui-history-robot",
    "ui-mobile-robot",
    "ui-keyboard-robot",
    "ui-layout-robot",
    "ui-accessibility-robot",
    "ui-browser-error-robot",
    "ui-above-fold-robot",
    "ui-visual-baseline-robot",
    "ui-trend-robot",
    "ui-cross-browser-robot",
    "hf-install-robot",
    "hf-visual-smoke-robot",
)


def select_ui_robot_profiles_for_files(paths: Sequence[str]) -> list[str]:
    profiles: set[str] = set()
    normalized = [
        Path(path).as_posix().removeprefix("./")
        for path in paths
        if str(path).strip()
    ]
    for path in normalized:
        lower = path.lower()
        if lower.startswith(
            (
                "tools/agilab_widget_robot",
                "tools/ui_robot_",
                "test/test_agilab_widget_robot",
                "test/test_ui_robot_",
            )
        ):
            profiles.update(
                {
                    "ui-robot-contract",
                    "ui-robot-canary",
                    "ui-artifact-capture-robot",
                    "ui-trend-robot",
                }
            )
        if lower.startswith(("tools/ui_visual_baseline", "test/test_ui_visual_baseline")) or "page-shots" in lower or "screenshot" in lower:
            profiles.update({"ui-visual-baseline-robot", "ui-trend-robot"})
        if lower.startswith((".github/workflows/ui-robot", ".github/workflows/coverage.yml")):
            profiles.update({"ui-robot-contract", "ui-robot-canary", "ui-trend-robot"})
        if lower.startswith(("src/agilab/main_page.py", "src/agilab/pages/", "src/agilab/lib/agi-gui/", "src/agilab/apps-pages/")):
            profiles.update(
                {
                    "ui-robot-matrix",
                    "ui-history-robot",
                    "ui-mobile-robot",
                    "ui-keyboard-robot",
                    "ui-layout-robot",
                    "ui-accessibility-robot",
                    "ui-browser-error-robot",
                    "ui-above-fold-robot",
                    "ui-trend-robot",
                }
            )
        if "huggingface" in lower or lower.startswith(("docker/", "spaces/", ".github/workflows/huggingface")):
            profiles.update({"hf-visual-smoke-robot", "hf-install-robot"})
        if lower.startswith(("tools/workflow_parity.py", "test/test_workflow_parity.py")):
            profiles.update({"ui-robot-contract", "ui-robot-canary"})
    if not profiles:
        profiles.add("ui-robot-contract")
    return [profile for profile in UI_ROBOT_PROFILE_ORDER if profile in profiles]


def _git_changed_files(base: str = "") -> list[str]:
    commands = []
    if base:
        commands.append(["git", "diff", "--name-only", f"{base}...HEAD"])
    else:
        commands.extend(
            [
                ["git", "diff", "--name-only", "HEAD"],
                ["git", "diff", "--cached", "--name-only"],
                ["git", "ls-files", "--others", "--exclude-standard"],
            ]
        )
    paths: list[str] = []
    seen: set[str] = set()
    for argv in commands:
        completed = subprocess.run(argv, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if completed.returncode != 0:
            continue
        for line in completed.stdout.splitlines():
            path = line.strip()
            if path and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _selected_ui_robot_profiles(args: argparse.Namespace) -> list[str]:
    changed_files = list(getattr(args, "changed_file", []) or [])
    if not changed_files:
        changed_files = _git_changed_files(str(getattr(args, "changed_base", "") or ""))
    return select_ui_robot_profiles_for_files(changed_files)


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
                "test/test_agilab_widget_robot_matrix.py",
                "test/test_agilab_widget_robot.py",
                "test/test_first_launch_robot.py",
                "test/test_screenshot_manifest.py",
                "test/test_ui_robot_coverage_contract.py",
                "test/test_ui_robot_action_contract.py",
                "test/test_ui_robot_failure_replay.py",
                "test/test_ui_robot_canary.py",
                "test/test_ui_robot_trend_report.py",
                "test/test_ui_visual_baseline_report.py",
            ],
        ),
        _agi_gui_coverage_chunk(
            "pages-flow",
            [
                "test/test_ui_pages.py",
                "-k",
                "execute_page or experiment_page or pipeline_page_project_selectbox",
            ],
        ),
        _agi_gui_coverage_chunk(
            "pages-rest",
            [
                "test/test_ui_pages.py",
                "-k",
                "not (execute_page or experiment_page or pipeline_page_project_selectbox)",
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
        _agi_gui_timing_report(),
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


def _agi_gui_timing_report() -> CommandSpec:
    return CommandSpec(
        label="agi-gui timing report",
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
            "tools/coverage_timing_report.py",
            "test-results/junit-agi-gui-*.xml",
            "--markdown-output",
            "test-results/coverage-agi-gui-timing.md",
            "--json-output",
            "test-results/coverage-agi-gui-timing.json",
        ],
        env={"AGILAB_DISABLE_BACKGROUND_SERVICES": "1"},
        timeout_seconds=60,
        ensure_dirs=["test-results"],
        remove_paths=[
            "test-results/coverage-agi-gui-timing.md",
            "test-results/coverage-agi-gui-timing.json",
        ],
    )


def _agi_gui_coverage_manifest_path(label: str) -> str:
    return f"test-results/coverage-agi-gui-{label}.manifest.json"


def _agi_gui_coverage_manifest_paths() -> list[str]:
    return [_agi_gui_coverage_manifest_path(chunk) for chunk in AGI_GUI_COVERAGE_CHUNKS]


def _agi_gui_coverage_chunk_code(label: str, data_file: str, junit_path: str, manifest_path: str) -> str:
    return (
        "from pathlib import Path\n"
        "import json, subprocess, sys, time\n"
        f"schema = {AGI_GUI_COVERAGE_MANIFEST_SCHEMA!r}\n"
        f"label = {label!r}\n"
        f"data_file = {data_file!r}\n"
        f"junit_path = {junit_path!r}\n"
        f"manifest_path = Path({manifest_path!r})\n"
        "started = time.perf_counter()\n"
        "cmd = [sys.executable, *sys.argv[1:]]\n"
        "completed = subprocess.run(cmd, check=False)\n"
        "base_path = Path(data_file)\n"
        "coverage_db_paths = sorted(\n"
        "    path.as_posix()\n"
        "    for path in base_path.parent.glob(base_path.name + '*')\n"
        "    if path.is_file() and path.stat().st_size > 0\n"
        ")\n"
        "manifest = {\n"
        "    'schema': schema,\n"
        "    'chunk': label,\n"
        "    'returncode': completed.returncode,\n"
        "    'duration_seconds': time.perf_counter() - started,\n"
        "    'data_file': data_file,\n"
        "    'junit_path': junit_path,\n"
        "    'coverage_db_paths': coverage_db_paths,\n"
        "    'coverage_command': cmd[1:],\n"
        "}\n"
        "manifest_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n"
        "sys.exit(completed.returncode)\n"
    )


def _agi_gui_coverage_combine_code() -> str:
    manifest_paths = _agi_gui_coverage_manifest_paths()
    return (
        "from pathlib import Path\n"
        "import json, subprocess, sys, time\n"
        f"schema = {AGI_GUI_COVERAGE_MANIFEST_SCHEMA!r}\n"
        f"manifest_paths = {manifest_paths!r}\n"
        f"wait_seconds = {AGI_GUI_COVERAGE_MANIFEST_WAIT_SECONDS!r}\n"
        "deadline = time.monotonic() + wait_seconds\n"
        "missing_manifests = []\n"
        "while True:\n"
        "    missing_manifests = [path for path in manifest_paths if not Path(path).is_file()]\n"
        "    if not missing_manifests or time.monotonic() >= deadline:\n"
        "        break\n"
        "    time.sleep(0.25)\n"
        "if missing_manifests:\n"
        "    print('Missing agi-gui coverage manifests: ' + ', '.join(missing_manifests))\n"
        "    sys.exit(1)\n"
        "failed_chunks = []\n"
        "empty_chunks = []\n"
        "missing_dbs = []\n"
        "coverage_paths = []\n"
        "seen_paths = set()\n"
        "for manifest_path in manifest_paths:\n"
        "    manifest_file = Path(manifest_path)\n"
        "    try:\n"
        "        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))\n"
        "    except Exception as exc:\n"
        "        print(f'Invalid agi-gui coverage manifest {manifest_path}: {exc}')\n"
        "        sys.exit(1)\n"
        "    chunk = str(manifest.get('chunk') or manifest_path)\n"
        "    if manifest.get('schema') != schema:\n"
        "        print(f'Unexpected agi-gui coverage manifest schema for {chunk}: {manifest.get(\"schema\")!r}')\n"
        "        sys.exit(1)\n"
        "    returncode = int(manifest.get('returncode', 1))\n"
        "    if returncode != 0:\n"
        "        failed_chunks.append(f'{chunk}={returncode}')\n"
        "    raw_paths = manifest.get('coverage_db_paths')\n"
        "    chunk_paths = raw_paths if isinstance(raw_paths, list) else []\n"
        "    valid_chunk_paths = []\n"
        "    for raw_path in chunk_paths:\n"
        "        path = Path(str(raw_path))\n"
        "        if path.is_file() and path.stat().st_size > 0:\n"
        "            path_key = path.as_posix()\n"
        "            if path_key not in seen_paths:\n"
        "                valid_chunk_paths.append(path_key)\n"
        "                coverage_paths.append(path_key)\n"
        "                seen_paths.add(path_key)\n"
        "        else:\n"
        "            missing_dbs.append(f'{chunk}:{raw_path}')\n"
        "    if not valid_chunk_paths:\n"
        "        empty_chunks.append(chunk)\n"
        "if failed_chunks:\n"
        "    print('Failed agi-gui coverage chunks: ' + ', '.join(failed_chunks))\n"
        "    sys.exit(1)\n"
        "if empty_chunks:\n"
        "    print('No coverage DBs recorded for agi-gui chunks: ' + ', '.join(empty_chunks))\n"
        "    sys.exit(1)\n"
        "if missing_dbs:\n"
        "    print('Missing agi-gui coverage DB files: ' + ', '.join(missing_dbs))\n"
        "    sys.exit(1)\n"
        "cmd = [sys.executable, '-m', 'coverage', 'combine', '--keep', *coverage_paths]\n"
        "sys.exit(subprocess.run(cmd, check=False).returncode)\n"
    )


def _agi_gui_coverage_combine() -> CommandSpec:
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
            _agi_gui_coverage_combine_code(),
        ],
        env={
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "COVERAGE_FILE": ".coverage.agi-gui",
        },
        timeout_seconds=5 * 60,
        ensure_dirs=["test-results"],
    )


def _agi_gui_coverage_chunk(label: str, targets: Sequence[str], *, clean: bool = False) -> CommandSpec:
    expanded_targets = _expand_repo_globs(targets)
    junit_path = f"test-results/junit-agi-gui-{label}.xml"
    data_file = f"test-results/coverage-agi-gui-{label}.db"
    manifest_path = _agi_gui_coverage_manifest_path(label)
    clean_paths = [
        ".coverage.agi-gui",
        "coverage-agi-gui.xml",
        *(f"test-results/coverage-agi-gui-{chunk}.db" for chunk in AGI_GUI_COVERAGE_CHUNKS),
        *(f"test-results/junit-agi-gui-{chunk}.xml" for chunk in AGI_GUI_COVERAGE_CHUNKS),
        *(_agi_gui_coverage_manifest_path(chunk) for chunk in AGI_GUI_COVERAGE_CHUNKS),
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
            "-c",
            _agi_gui_coverage_chunk_code(label, data_file, junit_path, manifest_path),
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
            else [data_file, f"{data_file}.*", junit_path, manifest_path]
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
            label="docs diagram wording check",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/docs_diagram_wording_check.py",
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
            argv=["bash", "-n", "install.sh", "src/agilab/install_apps.sh", "src/agilab/core/install.sh"],
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


def _production_readiness_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="production readiness gate",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/production_readiness_report.py",
                "--run-docs-profile",
                "--output",
                "test-results/production-readiness.json",
                "--compact",
            ],
            timeout_seconds=5 * 60,
            ensure_dirs=["test-results"],
            remove_paths=["test-results/production-readiness.json"],
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
                "--scenario",
                "isolated-core-pages",
                "--scenario",
                "isolated-entry-and-app-pages",
                "--scenario",
                "isolated-project-page",
                "--scenario",
                "isolated-project-notebook-import",
                "--scenario",
                "isolated-project-import-sidebar",
                "--scenario",
                "isolated-project-rename-sidebar",
                "--scenario",
                "isolated-settings-page",
                "--scenario",
                "isolated-browser-error-core-pages",
                "--scenario",
                "isolated-above-fold-core-pages",
                "--scenario",
                "isolated-layout-integrity-desktop",
                "--scenario",
                "isolated-keyboard-focus-core-pages",
                "--scenario",
                "isolated-fresh-session-core-pages",
                "--scenario",
                "isolated-browser-history",
                "--scenario",
                "isolated-mobile-core-pages",
                "--apps",
                "all",
                "--timeout",
                "90",
                "--widget-timeout",
                "3",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-robot-matrix",
                "--screenshot-dir",
                "screenshots/ui-robot-matrix",
                "--failure-bundle-dir",
                "test-results/ui-robot-matrix/failure-bundles",
            ],
            timeout_seconds=60 * 60,
            remove_paths=["test-results/ui-robot-matrix", "screenshots/ui-robot-matrix"],
        )
    ]


def _ui_robot_contract_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui robot coverage contract",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/ui_robot_coverage_contract.py",
                "--json",
            ],
            timeout_seconds=2 * 60,
        ),
        CommandSpec(
            label="ui robot action contract",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/ui_robot_action_contract.py",
                "--json",
            ],
            timeout_seconds=2 * 60,
        ),
    ]


def _ui_robot_canary_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui robot fault-injection canary",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "--with",
                "pillow",
                "python",
                "tools/ui_robot_canary.py",
                "--output",
                "test-results/ui-robot-canary.json",
                "--json",
            ],
            timeout_seconds=5 * 60,
            ensure_dirs=["test-results"],
            remove_paths=["test-results/ui-robot-canary.json"],
        )
    ]


def _ui_artifact_capture_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui artifact capture robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-project-page",
                "--apps",
                "flight_telemetry_project",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-artifact-capture-robot",
                "--screenshot-dir",
                "screenshots/ui-artifact-capture-robot",
                "--failure-bundle-dir",
                "test-results/ui-artifact-capture-robot/failure-bundles",
                "--trace-dir",
                "test-results/ui-artifact-capture-robot/traces",
                "--har-dir",
                "test-results/ui-artifact-capture-robot/har",
                "--video-dir",
                "test-results/ui-artifact-capture-robot/video",
            ],
            timeout_seconds=15 * 60,
            remove_paths=["test-results/ui-artifact-capture-robot", "screenshots/ui-artifact-capture-robot"],
        )
    ]


def _hf_install_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="hf flight telemetry install robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "hf-flight-telemetry-install",
                "--apps",
                "flight_telemetry_project",
                "--url",
                "https://huggingface.co/spaces/jpmorard/agilab?active_app=flight_telemetry_project",
                "--active-app",
                "flight_telemetry_project",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/hf-install-robot",
                "--screenshot-dir",
                "screenshots/hf-install-robot",
                "--failure-bundle-dir",
                "test-results/hf-install-robot/failure-bundles",
            ],
            timeout_seconds=25 * 60,
            remove_paths=["test-results/hf-install-robot", "screenshots/hf-install-robot"],
        )
    ]


def _hf_visual_smoke_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="hf flight telemetry visual smoke robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "hf-flight-telemetry-visual-smoke",
                "--apps",
                "flight_telemetry_project",
                "--url",
                "https://huggingface.co/spaces/jpmorard/agilab?active_app=flight_telemetry_project",
                "--active-app",
                "flight_telemetry_project",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/hf-visual-smoke-robot",
                "--screenshot-dir",
                "screenshots/hf-visual-smoke-robot",
                "--failure-bundle-dir",
                "test-results/hf-visual-smoke-robot/failure-bundles",
            ],
            timeout_seconds=25 * 60,
            remove_paths=["test-results/hf-visual-smoke-robot", "screenshots/hf-visual-smoke-robot"],
        )
    ]


def _ui_keyboard_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui keyboard focus robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-keyboard-focus-core-pages",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-keyboard-robot",
                "--screenshot-dir",
                "screenshots/ui-keyboard-robot",
                "--failure-bundle-dir",
                "test-results/ui-keyboard-robot/failure-bundles",
            ],
            timeout_seconds=30 * 60,
            remove_paths=["test-results/ui-keyboard-robot", "screenshots/ui-keyboard-robot"],
        )
    ]


def _ui_layout_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui layout integrity robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-layout-integrity-desktop",
                "--scenario",
                "isolated-layout-integrity-mobile",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-layout-robot",
                "--screenshot-dir",
                "screenshots/ui-layout-robot",
                "--failure-bundle-dir",
                "test-results/ui-layout-robot/failure-bundles",
            ],
            timeout_seconds=45 * 60,
            remove_paths=["test-results/ui-layout-robot", "screenshots/ui-layout-robot"],
        )
    ]


def _ui_accessibility_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui accessibility semantics robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-accessibility-core-pages",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-accessibility-robot",
                "--screenshot-dir",
                "screenshots/ui-accessibility-robot",
                "--failure-bundle-dir",
                "test-results/ui-accessibility-robot/failure-bundles",
            ],
            timeout_seconds=30 * 60,
            remove_paths=["test-results/ui-accessibility-robot", "screenshots/ui-accessibility-robot"],
        )
    ]


def _ui_browser_error_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui browser error robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-browser-error-core-pages",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-browser-error-robot",
                "--screenshot-dir",
                "screenshots/ui-browser-error-robot",
                "--failure-bundle-dir",
                "test-results/ui-browser-error-robot/failure-bundles",
            ],
            timeout_seconds=30 * 60,
            remove_paths=["test-results/ui-browser-error-robot", "screenshots/ui-browser-error-robot"],
        )
    ]


def _ui_above_fold_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui above-fold primary targets robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-above-fold-core-pages",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-above-fold-robot",
                "--screenshot-dir",
                "screenshots/ui-above-fold-robot",
                "--failure-bundle-dir",
                "test-results/ui-above-fold-robot/failure-bundles",
            ],
            timeout_seconds=30 * 60,
            remove_paths=["test-results/ui-above-fold-robot", "screenshots/ui-above-fold-robot"],
        )
    ]


def _ui_visual_baseline_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui visual baseline screenshot capture",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-visual-baseline-core-pages",
                "--apps",
                "flight_telemetry_project",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-visual-baseline-robot/current",
                "--screenshot-dir",
                "screenshots/ui-visual-baseline-robot/current",
                "--failure-bundle-dir",
                "test-results/ui-visual-baseline-robot/failure-bundles",
            ],
            timeout_seconds=30 * 60,
            remove_paths=["test-results/ui-visual-baseline-robot", "screenshots/ui-visual-baseline-robot"],
        ),
        CommandSpec(
            label="ui visual baseline report",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "pillow",
                "python",
                "tools/ui_visual_baseline_report.py",
                "--current",
                "screenshots/ui-visual-baseline-robot/current/isolated-visual-baseline-core-pages",
                "--baseline",
                "docs/source/_static/page-shots",
                "--allow-missing-baseline",
                "--advisory",
                "--output",
                "test-results/ui-visual-baseline-robot/visual-baseline.json",
                "--json",
            ],
            timeout_seconds=5 * 60,
        ),
    ]


def _ui_trend_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui robot trend report",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "python",
                "tools/ui_robot_trend_report.py",
                "--glob",
                "test-results/**/*.ndjson",
                "--max-total-seconds",
                "5400",
                "--max-mean-page-seconds",
                "180",
                "--output",
                "test-results/ui-robot-trend-report.json",
                "--json",
            ],
            timeout_seconds=2 * 60,
        )
    ]


def _ui_cross_browser_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui cross-browser playwright browsers",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "-m",
                "playwright",
                "install",
                "firefox",
                "webkit",
            ],
            timeout_seconds=10 * 60,
            remove_paths=["test-results/ui-cross-browser-robot", "screenshots/ui-cross-browser-robot"],
        ),
        CommandSpec(
            label="ui cross-browser robot (firefox)",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-cross-browser-core-pages",
                "--browser",
                "firefox",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-cross-browser-robot/firefox",
                "--screenshot-dir",
                "screenshots/ui-cross-browser-robot/firefox",
                "--failure-bundle-dir",
                "test-results/ui-cross-browser-robot/firefox/failure-bundles",
            ],
            timeout_seconds=30 * 60,
        ),
        CommandSpec(
            label="ui cross-browser robot (webkit)",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-cross-browser-core-pages",
                "--browser",
                "webkit",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-cross-browser-robot/webkit",
                "--screenshot-dir",
                "screenshots/ui-cross-browser-robot/webkit",
                "--failure-bundle-dir",
                "test-results/ui-cross-browser-robot/webkit/failure-bundles",
            ],
            timeout_seconds=30 * 60,
        ),
    ]


def _ui_history_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui browser history robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-browser-history",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-history-robot",
                "--screenshot-dir",
                "screenshots/ui-history-robot",
                "--failure-bundle-dir",
                "test-results/ui-history-robot/failure-bundles",
            ],
            timeout_seconds=30 * 60,
            remove_paths=["test-results/ui-history-robot", "screenshots/ui-history-robot"],
        )
    ]


def _ui_mobile_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui mobile viewport robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-mobile-core-pages",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-mobile-robot",
                "--screenshot-dir",
                "screenshots/ui-mobile-robot",
                "--failure-bundle-dir",
                "test-results/ui-mobile-robot/failure-bundles",
            ],
            timeout_seconds=30 * 60,
            remove_paths=["test-results/ui-mobile-robot", "screenshots/ui-mobile-robot"],
        )
    ]


def _ui_release_evidence_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui release evidence robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "isolated-release-evidence",
                "--scenario",
                "isolated-fresh-session-core-pages",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-release-evidence-robot",
                "--screenshot-dir",
                "screenshots/ui-release-evidence-robot",
                "--failure-bundle-dir",
                "test-results/ui-release-evidence-robot/failure-bundles",
            ],
            timeout_seconds=45 * 60,
            remove_paths=["test-results/ui-release-evidence-robot", "screenshots/ui-release-evidence-robot"],
        )
    ]


def _ui_first_proof_robot_profile() -> list[CommandSpec]:
    return [
        CommandSpec(
            label="ui first-proof golden path robot",
            argv=[
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--with",
                "playwright",
                "python",
                "tools/agilab_widget_robot_matrix.py",
                "--scenario",
                "current-home-first-proof-golden-path",
                "--apps",
                "flight_telemetry_project",
                "--json",
                "--quiet-progress",
                "--output-dir",
                "test-results/ui-first-proof-robot",
                "--screenshot-dir",
                "screenshots/ui-first-proof-robot",
                "--failure-bundle-dir",
                "test-results/ui-first-proof-robot/failure-bundles",
            ],
            timeout_seconds=45 * 60,
            remove_paths=["test-results/ui-first-proof-robot", "screenshots/ui-first-proof-robot"],
        )
    ]


def _selected_profiles(args: argparse.Namespace) -> list[str]:
    if args.profile:
        return args.profile
    if getattr(args, "select_ui_robot_profiles", False):
        return _selected_ui_robot_profiles(args)
    opt_in_profiles = {
        "agi-node",
        "agi-cluster",
        "release-proof",
        "security-adoption",
        "production-readiness",
        "ui-robot-matrix",
        "ui-robot-contract",
        "ui-robot-canary",
        "ui-artifact-capture-robot",
        "ui-history-robot",
        "ui-mobile-robot",
        "ui-release-evidence-robot",
        "ui-first-proof-robot",
        "ui-keyboard-robot",
        "ui-layout-robot",
        "ui-accessibility-robot",
        "ui-browser-error-robot",
        "ui-above-fold-robot",
        "ui-visual-baseline-robot",
        "ui-trend-robot",
        "ui-cross-browser-robot",
        "hf-install-robot",
        "hf-visual-smoke-robot",
    }
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


def _result_cache_enabled(args: argparse.Namespace, runner: Callable[[CommandSpec], CommandResult]) -> bool:
    return (
        runner is _run_command
        and bool(getattr(args, "result_cache", False))
        and not bool(getattr(args, "no_result_cache", False))
    )


def _result_cache_path(args: argparse.Namespace) -> Path:
    configured = getattr(args, "result_cache_path", None) or DEFAULT_RESULT_CACHE_PATH
    return Path(configured).expanduser()


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _result_cache_changed_files(args: argparse.Namespace) -> list[str]:
    explicit = list(getattr(args, "changed_file", []) or [])
    if explicit:
        return explicit
    base = str(getattr(args, "changed_base", "") or "") if getattr(args, "select_ui_robot_profiles", False) else ""
    return _git_changed_files(base)


def _repo_relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _result_cache_input_paths(changed_files: Sequence[str], cache_path: Path) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    cache_marker = _repo_relative_or_absolute(cache_path)
    for pattern in RESULT_CACHE_INPUT_GLOBS:
        if any(token in pattern for token in "*?["):
            expanded = [path.relative_to(REPO_ROOT).as_posix() for path in sorted(REPO_ROOT.glob(pattern))]
            candidates = expanded or [pattern]
        else:
            candidates = [pattern]
        for candidate in candidates:
            if candidate not in seen:
                paths.append(candidate)
                seen.add(candidate)
    for changed_file in sorted(changed_files):
        path = Path(changed_file)
        candidate = _repo_relative_or_absolute(path) if path.is_absolute() else path.as_posix()
        if candidate == cache_marker or candidate in seen:
            continue
        paths.append(candidate)
        seen.add(candidate)
    return paths


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_signature(path_name: str) -> dict[str, object]:
    path = Path(path_name)
    target = path if path.is_absolute() else REPO_ROOT / path
    label = _repo_relative_or_absolute(target) if target.is_absolute() else path.as_posix()
    try:
        stat = target.stat()
    except OSError as exc:
        return {"path": label, "state": "missing", "error": exc.__class__.__name__}
    signature: dict[str, object] = {
        "path": label,
        "state": "directory" if target.is_dir() else "file",
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if target.is_file() and stat.st_size <= RESULT_CACHE_HASH_LIMIT_BYTES:
        try:
            signature["sha256"] = _file_sha256(target)
        except OSError as exc:
            signature["sha256_error"] = exc.__class__.__name__
    return signature


def _result_cache_fingerprints(changed_files: Sequence[str], cache_path: Path) -> list[dict[str, object]]:
    return [_file_signature(path) for path in _result_cache_input_paths(changed_files, cache_path)]


def _run_result_cache_key(
    profile_names: Sequence[str],
    commands_by_profile: dict[str, list[CommandSpec]],
    descriptions: dict[str, str],
    *,
    changed_files: Sequence[str],
    cache_path: Path,
) -> str:
    selected = list(profile_names)
    payload = {
        "schema": RESULT_CACHE_SCHEMA,
        "git_head": _git_head(),
        "profiles": selected,
        "descriptions": {profile: descriptions[profile] for profile in selected},
        "commands": {
            profile: [asdict(spec) for spec in commands_by_profile[profile]]
            for profile in selected
        },
        "inputs": _result_cache_fingerprints(changed_files, cache_path),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
        },
        "env": {key: os.environ[key] for key in RESULT_CACHE_ENV_KEYS if key in os.environ},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_result_cache() -> dict[str, object]:
    return {"schema": RESULT_CACHE_SCHEMA, "entries": {}}


def _load_result_cache(cache_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_result_cache()
    if not isinstance(payload, dict) or payload.get("schema") != RESULT_CACHE_SCHEMA:
        return _empty_result_cache()
    if not isinstance(payload.get("entries"), dict):
        return _empty_result_cache()
    return payload


def _command_result_from_cache(payload: object) -> CommandResult | None:
    if not isinstance(payload, dict):
        return None
    argv = payload.get("argv")
    env = payload.get("env")
    if not isinstance(payload.get("label"), str) or not isinstance(argv, list) or not isinstance(env, dict):
        return None
    if not all(isinstance(arg, str) for arg in argv) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        return None
    returncode = payload.get("returncode")
    cwd = payload.get("cwd")
    if not isinstance(returncode, int) or not isinstance(cwd, str):
        return None
    return CommandResult(
        label=payload["label"],
        argv=list(argv),
        returncode=returncode,
        duration_seconds=0.0,
        cwd=cwd,
        env=dict(env),
    )


def _profile_result_from_cache(payload: object) -> ProfileResult | None:
    if not isinstance(payload, dict):
        return None
    profile = payload.get("profile")
    description = payload.get("description")
    success = payload.get("success")
    commands_payload = payload.get("commands")
    if not isinstance(profile, str) or not isinstance(description, str) or not isinstance(success, bool):
        return None
    if not isinstance(commands_payload, list):
        return None
    commands: list[CommandResult] = []
    for command_payload in commands_payload:
        command = _command_result_from_cache(command_payload)
        if command is None:
            return None
        commands.append(command)
    return ProfileResult(profile=profile, description=description, success=success, commands=commands)


def _cached_run_results(
    cache_state: dict[str, object],
    cache_key: str,
    profile_names: Sequence[str],
) -> list[ProfileResult] | None:
    entries = cache_state.get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(cache_key)
    if not isinstance(entry, dict) or entry.get("profiles") != list(profile_names):
        return None
    results_payload = entry.get("results")
    if not isinstance(results_payload, list):
        return None
    results: list[ProfileResult] = []
    for result_payload in results_payload:
        result = _profile_result_from_cache(result_payload)
        if result is None:
            return None
        results.append(result)
    return results


def _prune_result_cache(entries: dict[str, object]) -> None:
    if len(entries) <= RESULT_CACHE_MAX_ENTRIES:
        return

    def _stored_at(item: tuple[str, object]) -> float:
        value = item[1]
        if not isinstance(value, dict):
            return 0.0
        stored_at = value.get("stored_at", 0.0)
        return float(stored_at) if isinstance(stored_at, (int, float)) else 0.0

    keep = {
        key
        for key, _value in sorted(entries.items(), key=_stored_at, reverse=True)[:RESULT_CACHE_MAX_ENTRIES]
    }
    for key in list(entries):
        if key not in keep:
            entries.pop(key, None)


def _write_result_cache(cache_path: Path, cache_state: dict[str, object]) -> None:
    entries = cache_state.get("entries")
    if not isinstance(entries, dict):
        return
    _prune_result_cache(entries)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
    temp_path.write_text(json.dumps(cache_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(cache_path)


def _store_run_results(
    cache_path: Path,
    cache_state: dict[str, object],
    cache_key: str,
    profile_names: Sequence[str],
    results: Sequence[ProfileResult],
) -> None:
    entries = cache_state.get("entries")
    if not isinstance(entries, dict):
        return
    entries[cache_key] = {
        "profiles": list(profile_names),
        "stored_at": time.time(),
        "results": [asdict(result) for result in results],
    }
    _write_result_cache(cache_path, cache_state)


def run_profiles(
    profile_names: Sequence[str],
    *,
    args: argparse.Namespace,
    runner: Callable[[CommandSpec], CommandResult] = _run_command,
) -> list[ProfileResult]:
    commands_by_profile = _profile_commands(args)
    descriptions = _profile_descriptions()
    cache_path: Path | None = None
    cache_state: dict[str, object] | None = None
    cache_key = ""
    cache_enabled = _result_cache_enabled(args, runner)
    if cache_enabled:
        cache_path = _result_cache_path(args)
        cache_state = _load_result_cache(cache_path)
        cache_key = _run_result_cache_key(
            profile_names,
            commands_by_profile,
            descriptions,
            changed_files=_result_cache_changed_files(args),
            cache_path=cache_path,
        )
        cached_results = _cached_run_results(cache_state, cache_key, profile_names)
        if cached_results is not None:
            print(
                f"[workflow-parity] reused cached successful result for: {', '.join(profile_names)}",
                file=sys.stderr,
            )
            return cached_results

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
    if cache_enabled and cache_path is not None and cache_state is not None and all(result.success for result in results):
        _store_run_results(cache_path, cache_state, cache_key, profile_names, results)
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
