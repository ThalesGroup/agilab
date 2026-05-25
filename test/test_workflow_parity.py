from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("tools/workflow_parity.py").resolve()
WORKFLOW_PATH = Path(".github/workflows/coverage.yml")
SHARD_PLAN_PATH = Path("tools/coverage_shard_plan.py").resolve()


def _has_with_dependency(argv: list[str], dependency: str) -> bool:
    return any(
        arg == "--with" and index + 1 < len(argv) and argv[index + 1] == dependency
        for index, arg in enumerate(argv)
    )


def _has_extra(argv: list[str], extra: str) -> bool:
    return any(
        arg == "--extra" and index + 1 < len(argv) and argv[index + 1] == extra
        for index, arg in enumerate(argv)
    )


def _option_values(argv: list[str], option: str) -> list[str]:
    return [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == option]


def _load_module():
    spec = importlib.util.spec_from_file_location("workflow_parity_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cache_args(cache_path: Path, *, no_result_cache: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        profile=["skills"],
        components=None,
        skills=None,
        app_path=None,
        worker_copy=None,
        keep_going=False,
        result_cache=True,
        result_cache_path=str(cache_path),
        no_result_cache=no_result_cache,
        select_ui_robot_profiles=False,
        changed_file=[],
        changed_base="",
    )


def _coverage_workflow_agi_gui_targets() -> dict[str, list[str]]:
    spec = importlib.util.spec_from_file_location("coverage_shard_plan_workflow_parity_test_module", SHARD_PLAN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.static_chunk_args()


def _parity_agi_gui_targets(module) -> dict[str, list[str]]:
    args = SimpleNamespace(components=None, skills=None, app_path=None, worker_copy=None)
    commands = module._profile_commands(args)["agi-gui"][: len(module.AGI_GUI_COVERAGE_CHUNKS)]
    targets_by_chunk: dict[str, list[str]] = {}
    for command in commands:
        match = re.fullmatch(r"agi-gui coverage \(([a-z-]+)\)", command.label)
        assert match is not None
        ignore_index = command.argv.index("--ignore=src/agilab/test/test_model_returns_code.py")
        targets_by_chunk[match.group(1)] = command.argv[ignore_index + 1 :]
    return targets_by_chunk


def test_agi_gui_workflow_parity_matches_coverage_workflow_targets() -> None:
    module = _load_module()
    expected = {
        chunk: module._expand_repo_globs(paths)
        for chunk, paths in _coverage_workflow_agi_gui_targets().items()
    }
    actual = _parity_agi_gui_targets(module)

    assert set(actual) == set(expected)
    for chunk in sorted(expected):
        missing = sorted(set(expected[chunk]) - set(actual[chunk]))
        extra = sorted(set(actual[chunk]) - set(expected[chunk]))
        assert not missing and not extra, (
            f"workflow_parity agi-gui chunk {chunk!r} drifted from coverage.yml; "
            f"missing={missing}, extra={extra}"
        )


def test_profile_commands_cover_expected_coverage_and_docs_contracts() -> None:
    module = _load_module()
    args = SimpleNamespace(components=None, skills=None, app_path=None, worker_copy=None)

    profiles = module._profile_commands(args)
    agi_env = profiles["agi-env"][0]
    agi_core_combined = profiles["agi-core-combined"]
    agi_node = profiles["agi-node"][0]
    agi_cluster = profiles["agi-cluster"][0]
    agi_gui_commands = profiles["agi-gui"]
    agi_gui_chunk_count = len(module.AGI_GUI_COVERAGE_CHUNKS)
    agi_gui_chunks = agi_gui_commands[:agi_gui_chunk_count]
    agi_gui_combine = agi_gui_commands[-3]
    agi_gui_timing = agi_gui_commands[-2]
    agi_gui_xml = agi_gui_commands[-1]
    agi_gui_argv = [arg for command in agi_gui_commands for arg in command.argv]
    docs_commands = profiles["docs"]
    release_proof_docs = docs_commands[0]
    diagram_wording_docs = docs_commands[1]
    docs = docs_commands[2]
    badges = profiles["badges"]
    strict_typing = profiles["shared-core-typing"][0]
    dependency_policy = profiles["dependency-policy"][0]
    release_proof = profiles["release-proof"][0]
    security_adoption = profiles["security-adoption"][0]
    production_readiness = profiles["production-readiness"][0]
    cloud_emulators = profiles["cloud-emulators"]
    ui_robot_contract = profiles["ui-robot-contract"]
    ui_robot_coverage_contract = ui_robot_contract[0]
    ui_robot_action_contract = ui_robot_contract[1]
    ui_robot_canary = profiles["ui-robot-canary"][0]
    ui_frontend_smoke = profiles["ui-frontend-smoke"][0]
    ui_robot_matrix_commands = profiles["ui-robot-matrix"]
    ui_robot_matrix = {
        command.label.removeprefix("ui robot matrix (").removesuffix(")"): command
        for command in ui_robot_matrix_commands
    }
    ui_artifact_capture_robot = profiles["ui-artifact-capture-robot"][0]
    ui_history_robot = profiles["ui-history-robot"][0]
    ui_mobile_robot = profiles["ui-mobile-robot"][0]
    ui_release_evidence_robot = profiles["ui-release-evidence-robot"][0]
    ui_first_proof_robot = profiles["ui-first-proof-robot"][0]
    ui_keyboard_robot = profiles["ui-keyboard-robot"][0]
    ui_layout_robot = profiles["ui-layout-robot"][0]
    ui_accessibility_robot = profiles["ui-accessibility-robot"][0]
    ui_browser_error_robot = profiles["ui-browser-error-robot"][0]
    ui_above_fold_robot = profiles["ui-above-fold-robot"][0]
    ui_visual_baseline_robot = profiles["ui-visual-baseline-robot"]
    ui_trend_robot = profiles["ui-trend-robot"][0]
    ui_cross_browser_robot = profiles["ui-cross-browser-robot"]
    hf_install_robot = profiles["hf-install-robot"][0]
    hf_visual_smoke_robot = profiles["hf-visual-smoke-robot"][0]

    assert agi_env.timeout_seconds == 20 * 60
    assert agi_env.env["COVERAGE_FILE"] == ".coverage.agi-env"
    assert "--cov=agi_env" in agi_env.argv
    assert "coverage-agi-env.xml" in " ".join(agi_env.argv)
    assert _has_with_dependency(agi_env.argv, "streamlit")
    assert agi_env.argv[-1] == "src/agilab/core/agi-env/test"

    assert len(agi_core_combined) == 3
    combined_run = agi_core_combined[0]
    combined_node_xml = agi_core_combined[1]
    combined_cluster_xml = agi_core_combined[2]
    assert combined_run.timeout_seconds == 20 * 60
    assert combined_run.argv[-1] == "src/agilab/core/test"
    assert "--data-file=.coverage.agi-core-combined" in combined_run.argv
    assert "--source=agi_node,agi_cluster" in combined_run.argv
    assert _has_with_dependency(combined_run.argv, "fastparquet")
    assert _has_with_dependency(combined_node_xml.argv, "fastparquet")
    assert _has_with_dependency(combined_cluster_xml.argv, "fastparquet")
    assert "pytest" in combined_run.argv
    assert combined_node_xml.timeout_seconds == 5 * 60
    assert "--data-file=.coverage.agi-core-combined" in combined_node_xml.argv
    assert "-o" in combined_node_xml.argv
    assert "coverage-agi-node.xml" in combined_node_xml.argv
    assert "--include=*/agi_node/*" in combined_node_xml.argv
    assert combined_cluster_xml.timeout_seconds == 5 * 60
    assert "--data-file=.coverage.agi-core-combined" in combined_cluster_xml.argv
    assert "-o" in combined_cluster_xml.argv
    assert "coverage-agi-cluster.xml" in combined_cluster_xml.argv
    assert "--include=*/agi_cluster/*" in combined_cluster_xml.argv

    assert agi_node.timeout_seconds == 20 * 60
    assert agi_node.env["COVERAGE_FILE"] == ".coverage.agi-node"
    assert "--cov=agi_node" in agi_node.argv
    assert "coverage-agi-node.xml" in " ".join(agi_node.argv)
    assert _has_with_dependency(agi_node.argv, "fastparquet")
    assert agi_node.argv[-1] == "src/agilab/core/test"

    assert agi_cluster.timeout_seconds == 20 * 60
    assert agi_cluster.env["COVERAGE_FILE"] == ".coverage.agi-cluster"
    assert "--cov=agi_cluster" in agi_cluster.argv
    assert "coverage-agi-cluster.xml" in " ".join(agi_cluster.argv)
    assert _has_with_dependency(agi_cluster.argv, "fastparquet")
    assert agi_cluster.argv[-1] == "src/agilab/core/test"

    assert [command.label for command in agi_gui_commands] == [
        "agi-gui coverage (support)",
        "agi-gui coverage (pipeline)",
        "agi-gui coverage (robots)",
        "agi-gui coverage (pages-flow)",
        "agi-gui coverage (pages-rest)",
        "agi-gui coverage (views)",
        "agi-gui coverage (reports)",
        "agi-gui coverage combine",
        "agi-gui timing report",
        "agi-gui coverage xml",
    ]
    assert all(command.timeout_seconds == 8 * 60 for command in agi_gui_chunks)
    assert all(command.env["AGILAB_DISABLE_BACKGROUND_SERVICES"] == "1" for command in agi_gui_commands)
    assert all(_has_extra(command.argv, "ui") for command in agi_gui_commands)
    assert all(_has_extra(command.argv, "viz") for command in agi_gui_commands)
    assert agi_gui_commands[0].remove_paths[:2] == [".coverage.agi-gui", "coverage-agi-gui.xml"]
    assert all("coverage" in command.argv for command in agi_gui_chunks)
    assert all("--append" not in command.argv for command in agi_gui_chunks)
    assert all("--parallel-mode" in command.argv for command in agi_gui_chunks)
    assert "test-results/coverage-agi-gui-support.db.*" in agi_gui_commands[0].remove_paths
    assert "test-results/coverage-agi-gui-support.manifest.json" in agi_gui_commands[0].remove_paths
    assert "test-results/coverage-agi-gui-pipeline.db.*" in agi_gui_commands[1].remove_paths
    assert "test-results/coverage-agi-gui-pipeline.manifest.json" in agi_gui_commands[1].remove_paths
    assert "--data-file=test-results/coverage-agi-gui-support.db" in agi_gui_commands[0].argv
    assert "coverage_db_paths" in " ".join(agi_gui_commands[0].argv)
    assert "test-results/coverage-agi-gui-support.manifest.json" in " ".join(agi_gui_commands[0].argv)
    agi_gui_combine_argv = " ".join(agi_gui_combine.argv)
    assert "'coverage', 'combine'" in agi_gui_combine_argv
    assert "--keep" in agi_gui_combine_argv
    assert agi_gui_combine.env["COVERAGE_FILE"] == ".coverage.agi-gui"
    assert "Missing agi-gui coverage manifests" in agi_gui_combine_argv
    assert "coverage_db_paths" in agi_gui_combine_argv
    assert "range(120)" not in agi_gui_combine_argv
    assert "stat().st_size > 0" in agi_gui_combine_argv
    assert "test-results/coverage-agi-gui-pipeline.manifest.json" in agi_gui_combine_argv
    assert agi_gui_timing.timeout_seconds == 60
    assert "tools/coverage_timing_report.py" in agi_gui_timing.argv
    assert "test-results/junit-agi-gui-*.xml" in agi_gui_timing.argv
    assert "test-results/coverage-agi-gui-timing.md" in agi_gui_timing.argv
    assert "test-results/coverage-agi-gui-timing.json" in agi_gui_timing.argv
    assert "coverage-agi-gui.xml" in agi_gui_xml.argv
    assert "src/agilab/lib/agi-gui/test" in agi_gui_argv
    assert "test/test_about_agilab_helpers.py" in agi_gui_argv
    assert "test/test_app_template_registry.py" in agi_gui_argv
    assert "test/test_cluster_flight_validation.py" in agi_gui_argv
    assert "test/test_cluster_lan_discovery.py" in agi_gui_argv
    assert "test/test_dag_distributed_submitter.py" in agi_gui_argv
    assert "test/test_agilab_dev_shortcuts.py" in agi_gui_argv
    assert "test/test_env_footprint.py" in agi_gui_argv
    assert "test/test_ga_regression_selector.py" in agi_gui_argv
    assert "test/test_pipeline_mistral.py" in agi_gui_argv
    assert "test/test_pipeline_openai_compatible.py" in agi_gui_argv
    assert "test/test_notebook_colab_support.py" in agi_gui_argv
    assert "test/test_notebook_import_sample.py" in agi_gui_argv
    assert "test/test_pinned_expander.py" in agi_gui_argv
    assert "test/test_workflow_ui.py" in agi_gui_argv
    assert "test/test_agilab_web_robot.py" in agi_gui_argv
    assert "test/test_agilab_widget_robot_matrix.py" in agi_gui_argv
    assert "test/test_agilab_widget_robot.py" in agi_gui_argv
    assert "test/test_first_launch_robot.py" in agi_gui_argv
    assert "test/test_screenshot_manifest.py" in agi_gui_argv
    assert "test/test_ui_robot_coverage_contract.py" in agi_gui_argv
    assert "test/test_ui_robot_action_contract.py" in agi_gui_argv
    assert "test/test_ui_robot_failure_replay.py" in agi_gui_argv
    assert "test/test_ui_robot_canary.py" in agi_gui_argv
    assert "test/test_ui_robot_trend_report.py" in agi_gui_argv
    assert "test/test_ui_visual_baseline_report.py" in agi_gui_argv
    assert "test/test_ui_pages.py" in agi_gui_argv
    assert "--data-file=test-results/coverage-agi-gui-pages-flow.db" in agi_gui_argv
    assert "--data-file=test-results/coverage-agi-gui-pages-rest.db" in agi_gui_argv
    assert "execute_page or experiment_page or pipeline_page_project_selectbox" in agi_gui_argv
    assert "not (execute_page or experiment_page or pipeline_page_project_selectbox)" in agi_gui_argv
    assert "test/test_view*.py" not in agi_gui_argv
    assert "test/test_view_maps.py" in agi_gui_argv
    assert "test/test_ci_provider_artifacts.py" in agi_gui_argv
    assert "test/test_ci_artifact_harvest_report.py" in agi_gui_argv
    assert "test/test_*_workflow.py" not in agi_gui_argv
    assert release_proof_docs.label == "release proof manifest check"
    assert release_proof_docs.argv[-2:] == ["--check", "--compact"]
    assert diagram_wording_docs.label == "docs diagram wording check"
    assert diagram_wording_docs.argv[-1] == "tools/docs_diagram_wording_check.py"
    assert docs.argv[-2:] == ["docs/source", "docs/html"]
    assert docs.remove_paths == ["docs/html"]
    assert badges[-1].label == "badge drift guard"
    assert badges[-1].argv == ["git", "diff", "--exit-code", "--", "badges/"]
    assert strict_typing.argv[-1] == "tools/shared_core_strict_typing.py"
    assert dependency_policy.label == "dependency policy"
    assert dependency_policy.argv[-1] == "test/test_pyproject_dependency_hygiene.py"
    assert "addopts=" in dependency_policy.argv
    assert release_proof.label == "fresh source clone first-proof plus notebook import/export proof"
    assert release_proof.env["AGILAB_RUN_RELEASE_PROOF_SLOW"] == "1"
    assert release_proof.timeout_seconds == 15 * 60
    assert "-m" in release_proof.argv
    assert "release_proof" in release_proof.argv
    assert release_proof.argv[-1].endswith("test_newcomer_first_proof_passes_from_fresh_source_clone")
    assert security_adoption.label == "security adoption check"
    assert security_adoption.argv[-3:] == [
        "tools/security_adoption_check.py",
        "--output",
        "test-results/security-check.json",
    ]
    assert security_adoption.ensure_dirs == ["test-results"]
    assert security_adoption.remove_paths == ["test-results/security-check.json"]
    assert production_readiness.label == "production readiness gate"
    assert production_readiness.argv[-5:] == [
        "tools/production_readiness_report.py",
        "--run-docs-profile",
        "--output",
        "test-results/production-readiness.json",
        "--compact",
    ]
    assert production_readiness.timeout_seconds == 5 * 60
    assert production_readiness.ensure_dirs == ["test-results"]
    assert production_readiness.remove_paths == ["test-results/production-readiness.json"]
    assert [command.label for command in cloud_emulators] == [
        "cloud emulator connector evidence",
        "cloud emulator connector tests",
    ]
    assert cloud_emulators[0].argv[-2:] == [
        "tools/data_connector_cloud_emulator_report.py",
        "--compact",
    ]
    assert cloud_emulators[1].argv[-1] == "test/test_data_connector_cloud_emulator_report.py"
    assert [command.label for command in ui_robot_contract] == [
        "ui robot coverage contract",
        "ui robot action contract",
    ]
    assert ui_robot_coverage_contract.timeout_seconds == 2 * 60
    assert ui_robot_coverage_contract.argv[-2:] == ["tools/ui_robot_coverage_contract.py", "--json"]
    assert ui_robot_action_contract.timeout_seconds == 2 * 60
    assert ui_robot_action_contract.argv[-2:] == ["tools/ui_robot_action_contract.py", "--json"]
    assert ui_robot_canary.label == "ui robot fault-injection canary"
    assert ui_robot_canary.timeout_seconds == 5 * 60
    assert "tools/ui_robot_canary.py" in ui_robot_canary.argv
    assert "test-results/ui-robot-canary.json" in ui_robot_canary.argv
    assert _has_with_dependency(ui_robot_canary.argv, "playwright")
    assert _has_with_dependency(ui_robot_canary.argv, "pillow")
    assert ui_frontend_smoke.label == "ui frontend smoke robot"
    assert ui_frontend_smoke.timeout_seconds == 5 * 60
    assert ui_frontend_smoke.remove_paths == ["screenshots/ui-frontend-smoke"]
    assert "tools/agilab_web_robot.py" in ui_frontend_smoke.argv
    assert "--frontend-smoke-only" in ui_frontend_smoke.argv
    assert "--timeout" in ui_frontend_smoke.argv
    assert "--target-seconds" in ui_frontend_smoke.argv
    assert "45" in ui_frontend_smoke.argv
    assert "screenshots/ui-frontend-smoke" in ui_frontend_smoke.argv
    assert _has_extra(ui_frontend_smoke.argv, "ui")
    assert _has_with_dependency(ui_frontend_smoke.argv, "playwright")
    assert set(ui_robot_matrix) == {"core", "state", "quality", "layout"}
    expected_matrix_scenarios = {
        "core": {
            "isolated-core-pages",
            "isolated-entry-and-app-pages",
            "isolated-project-page",
            "isolated-project-notebook-import",
            "isolated-project-import-sidebar",
            "isolated-project-rename-sidebar",
            "isolated-settings-page",
        },
        "state": {
            "isolated-fresh-session-core-pages",
            "isolated-browser-history",
        },
        "quality": {
            "isolated-browser-error-core-pages",
            "isolated-pytorch-playground-analysis",
            "isolated-above-fold-core-pages",
            "isolated-keyboard-focus-core-pages",
            "isolated-accessibility-core-pages",
        },
        "layout": {
            "isolated-layout-integrity-desktop",
            "isolated-mobile-core-pages",
            "isolated-layout-integrity-mobile",
        },
    }
    for shard, command in ui_robot_matrix.items():
        assert command.label == f"ui robot matrix ({shard})"
        assert command.timeout_seconds == 50 * 60
        assert command.remove_paths == [
            f"test-results/ui-robot-matrix/{shard}",
            f"screenshots/ui-robot-matrix/{shard}",
        ]
        assert "tools/agilab_widget_robot_matrix.py" in command.argv
        assert expected_matrix_scenarios[shard] == set(_option_values(command.argv, "--scenario"))
        assert "--quiet-progress" in command.argv
        assert "--json" in command.argv
        assert "--no-result-cache" in command.argv
        assert "--screenshot-dir" in command.argv
        assert f"screenshots/ui-robot-matrix/{shard}" in command.argv
        assert f"test-results/ui-robot-matrix/{shard}/failure-bundles" in command.argv
        assert "--retry-failed-with-artifacts" in command.argv
        assert f"test-results/ui-robot-matrix/{shard}/failure-artifacts/traces" in command.argv
        assert f"test-results/ui-robot-matrix/{shard}/failure-artifacts/har" in command.argv
        assert f"test-results/ui-robot-matrix/{shard}/failure-artifacts/video" in command.argv
        assert _has_with_dependency(command.argv, "playwright")
        assert _has_extra(command.argv, "ai")
    assert ui_artifact_capture_robot.label == "ui artifact capture robot"
    assert ui_artifact_capture_robot.timeout_seconds == 15 * 60
    assert "isolated-project-page" in ui_artifact_capture_robot.argv
    assert "flight_telemetry_project" in ui_artifact_capture_robot.argv
    assert "--trace-dir" in ui_artifact_capture_robot.argv
    assert "test-results/ui-artifact-capture-robot/traces" in ui_artifact_capture_robot.argv
    assert "--har-dir" in ui_artifact_capture_robot.argv
    assert "test-results/ui-artifact-capture-robot/har" in ui_artifact_capture_robot.argv
    assert "--video-dir" in ui_artifact_capture_robot.argv
    assert "test-results/ui-artifact-capture-robot/video" in ui_artifact_capture_robot.argv
    assert ui_artifact_capture_robot.remove_paths == [
        "test-results/ui-artifact-capture-robot",
        "screenshots/ui-artifact-capture-robot",
    ]
    assert _has_with_dependency(ui_artifact_capture_robot.argv, "playwright")
    assert ui_history_robot.label == "ui browser history robot"
    assert ui_history_robot.timeout_seconds == 30 * 60
    assert ui_history_robot.remove_paths == ["test-results/ui-history-robot", "screenshots/ui-history-robot"]
    assert "tools/agilab_widget_robot_matrix.py" in ui_history_robot.argv
    assert "isolated-browser-history" in ui_history_robot.argv
    assert "screenshots/ui-history-robot" in ui_history_robot.argv
    assert "test-results/ui-history-robot/failure-bundles" in ui_history_robot.argv
    assert _has_with_dependency(ui_history_robot.argv, "playwright")
    assert ui_mobile_robot.label == "ui mobile viewport robot"
    assert ui_mobile_robot.timeout_seconds == 30 * 60
    assert ui_mobile_robot.remove_paths == ["test-results/ui-mobile-robot", "screenshots/ui-mobile-robot"]
    assert "isolated-mobile-core-pages" in ui_mobile_robot.argv
    assert "screenshots/ui-mobile-robot" in ui_mobile_robot.argv
    assert "test-results/ui-mobile-robot/failure-bundles" in ui_mobile_robot.argv
    assert _has_with_dependency(ui_mobile_robot.argv, "playwright")
    assert ui_release_evidence_robot.label == "ui release evidence robot"
    assert ui_release_evidence_robot.timeout_seconds == 45 * 60
    assert ui_release_evidence_robot.remove_paths == [
        "test-results/ui-release-evidence-robot",
        "screenshots/ui-release-evidence-robot",
    ]
    assert "isolated-release-evidence" in ui_release_evidence_robot.argv
    assert "isolated-fresh-session-core-pages" in ui_release_evidence_robot.argv
    assert "--no-result-cache" in ui_release_evidence_robot.argv
    assert "screenshots/ui-release-evidence-robot" in ui_release_evidence_robot.argv
    assert "test-results/ui-release-evidence-robot/failure-bundles" in ui_release_evidence_robot.argv
    assert _has_with_dependency(ui_release_evidence_robot.argv, "playwright")
    assert ui_first_proof_robot.label == "ui first-proof golden path robot"
    assert ui_first_proof_robot.timeout_seconds == 45 * 60
    assert ui_first_proof_robot.remove_paths == [
        "test-results/ui-first-proof-robot",
        "screenshots/ui-first-proof-robot",
    ]
    assert "current-home-first-proof-golden-path" in ui_first_proof_robot.argv
    assert "flight_telemetry_project" in ui_first_proof_robot.argv
    assert "screenshots/ui-first-proof-robot" in ui_first_proof_robot.argv
    assert "test-results/ui-first-proof-robot/failure-bundles" in ui_first_proof_robot.argv
    assert _has_with_dependency(ui_first_proof_robot.argv, "playwright")
    assert ui_keyboard_robot.label == "ui keyboard focus robot"
    assert ui_keyboard_robot.timeout_seconds == 30 * 60
    assert ui_keyboard_robot.remove_paths == ["test-results/ui-keyboard-robot", "screenshots/ui-keyboard-robot"]
    assert "isolated-keyboard-focus-core-pages" in ui_keyboard_robot.argv
    assert "test-results/ui-keyboard-robot/failure-bundles" in ui_keyboard_robot.argv
    assert _has_with_dependency(ui_keyboard_robot.argv, "playwright")
    assert ui_layout_robot.label == "ui layout integrity robot"
    assert ui_layout_robot.timeout_seconds == 45 * 60
    assert ui_layout_robot.remove_paths == ["test-results/ui-layout-robot", "screenshots/ui-layout-robot"]
    assert "isolated-layout-integrity-desktop" in ui_layout_robot.argv
    assert "isolated-layout-integrity-mobile" in ui_layout_robot.argv
    assert "test-results/ui-layout-robot/failure-bundles" in ui_layout_robot.argv
    assert _has_with_dependency(ui_layout_robot.argv, "playwright")
    assert ui_accessibility_robot.label == "ui accessibility semantics robot"
    assert ui_accessibility_robot.timeout_seconds == 30 * 60
    assert ui_accessibility_robot.remove_paths == ["test-results/ui-accessibility-robot", "screenshots/ui-accessibility-robot"]
    assert "isolated-accessibility-core-pages" in ui_accessibility_robot.argv
    assert "test-results/ui-accessibility-robot/failure-bundles" in ui_accessibility_robot.argv
    assert _has_with_dependency(ui_accessibility_robot.argv, "playwright")
    assert ui_browser_error_robot.label == "ui browser error robot"
    assert ui_browser_error_robot.timeout_seconds == 30 * 60
    assert ui_browser_error_robot.remove_paths == ["test-results/ui-browser-error-robot", "screenshots/ui-browser-error-robot"]
    assert "isolated-browser-error-core-pages" in ui_browser_error_robot.argv
    assert "test-results/ui-browser-error-robot/failure-bundles" in ui_browser_error_robot.argv
    assert _has_with_dependency(ui_browser_error_robot.argv, "playwright")
    assert ui_above_fold_robot.label == "ui above-fold primary targets robot"
    assert ui_above_fold_robot.timeout_seconds == 30 * 60
    assert ui_above_fold_robot.remove_paths == ["test-results/ui-above-fold-robot", "screenshots/ui-above-fold-robot"]
    assert "isolated-above-fold-core-pages" in ui_above_fold_robot.argv
    assert "test-results/ui-above-fold-robot/failure-bundles" in ui_above_fold_robot.argv
    assert _has_with_dependency(ui_above_fold_robot.argv, "playwright")
    assert [command.label for command in ui_visual_baseline_robot] == [
        "ui visual baseline screenshot capture",
        "ui visual baseline report",
    ]
    assert ui_visual_baseline_robot[0].remove_paths == [
        "test-results/ui-visual-baseline-robot",
        "screenshots/ui-visual-baseline-robot",
    ]
    assert "isolated-visual-baseline-core-pages" in ui_visual_baseline_robot[0].argv
    assert "flight_telemetry_project" in ui_visual_baseline_robot[0].argv
    assert "screenshots/ui-visual-baseline-robot/current" in ui_visual_baseline_robot[0].argv
    assert "tools/ui_visual_baseline_report.py" in ui_visual_baseline_robot[1].argv
    assert "--advisory" in ui_visual_baseline_robot[1].argv
    assert _has_with_dependency(ui_visual_baseline_robot[0].argv, "playwright")
    assert _has_with_dependency(ui_visual_baseline_robot[1].argv, "pillow")
    assert ui_trend_robot.label == "ui robot trend report"
    assert "tools/ui_robot_trend_report.py" in ui_trend_robot.argv
    assert "test-results/ui-robot-trend-report.json" in ui_trend_robot.argv
    assert "--max-total-seconds" in ui_trend_robot.argv
    assert "--max-mean-page-seconds" in ui_trend_robot.argv
    assert [command.label for command in ui_cross_browser_robot] == [
        "ui cross-browser playwright browsers",
        "ui cross-browser robot (firefox)",
        "ui cross-browser robot (webkit)",
    ]
    assert ui_cross_browser_robot[0].remove_paths == [
        "test-results/ui-cross-browser-robot",
        "screenshots/ui-cross-browser-robot",
    ]
    assert ui_cross_browser_robot[0].argv[-4:] == ["playwright", "install", "firefox", "webkit"]
    assert "isolated-cross-browser-core-pages" in ui_cross_browser_robot[1].argv
    assert ui_cross_browser_robot[1].argv[ui_cross_browser_robot[1].argv.index("--browser") + 1] == "firefox"
    assert "isolated-cross-browser-core-pages" in ui_cross_browser_robot[2].argv
    assert ui_cross_browser_robot[2].argv[ui_cross_browser_robot[2].argv.index("--browser") + 1] == "webkit"
    assert all(_has_with_dependency(command.argv, "playwright") for command in ui_cross_browser_robot)
    assert hf_install_robot.label == "hf first-proof install robot"
    assert hf_install_robot.timeout_seconds == 25 * 60
    assert hf_install_robot.remove_paths == ["test-results/hf-install-robot", "screenshots/hf-install-robot"]
    assert "tools/agilab_widget_robot_matrix.py" in hf_install_robot.argv
    assert "hf-first-proof-install" in hf_install_robot.argv
    assert "flight_telemetry_project,weather_forecast_project" in hf_install_robot.argv
    assert "https://huggingface.co/spaces/jpmorard/agilab" in hf_install_robot.argv
    assert "--active-app" not in hf_install_robot.argv
    assert "screenshots/hf-install-robot" in hf_install_robot.argv
    assert "test-results/hf-install-robot/failure-bundles" in hf_install_robot.argv
    assert _has_with_dependency(hf_install_robot.argv, "playwright")
    assert hf_visual_smoke_robot.label == "hf first-proof visual smoke robot"
    assert hf_visual_smoke_robot.timeout_seconds == 25 * 60
    assert hf_visual_smoke_robot.remove_paths == ["test-results/hf-visual-smoke-robot", "screenshots/hf-visual-smoke-robot"]
    assert "hf-first-proof-visual-smoke" in hf_visual_smoke_robot.argv
    assert "hf-first-proof-app-pages-visual-smoke" in hf_visual_smoke_robot.argv
    assert hf_visual_smoke_robot.argv.count("--scenario") == 2
    assert "flight_telemetry_project,weather_forecast_project" in hf_visual_smoke_robot.argv
    assert "https://huggingface.co/spaces/jpmorard/agilab" in hf_visual_smoke_robot.argv
    assert "--active-app" not in hf_visual_smoke_robot.argv
    assert "screenshots/hf-visual-smoke-robot" in hf_visual_smoke_robot.argv
    assert _has_with_dependency(hf_visual_smoke_robot.argv, "playwright")


def test_agi_gui_coverage_chunk_wrapper_writes_manifest(tmp_path) -> None:
    module = _load_module()
    data_file = tmp_path / "coverage-agi-gui-demo.db"
    db_fragment = Path(f"{data_file}.worker")
    junit_path = tmp_path / "junit-agi-gui-demo.xml"
    manifest_path = tmp_path / "coverage-agi-gui-demo.manifest.json"
    chunk_code = module._agi_gui_coverage_chunk_code(
        "demo",
        data_file.as_posix(),
        junit_path.as_posix(),
        manifest_path.as_posix(),
    )
    inner_code = (
        "from pathlib import Path\n"
        f"Path({db_fragment.as_posix()!r}).write_text('coverage fragment', encoding='utf-8')\n"
        f"Path({junit_path.as_posix()!r}).write_text('<testsuite/>', encoding='utf-8')\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", chunk_code, "-c", inner_code],
        check=False,
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == module.AGI_GUI_COVERAGE_MANIFEST_SCHEMA
    assert manifest["chunk"] == "demo"
    assert manifest["returncode"] == 0
    assert manifest["data_file"] == data_file.as_posix()
    assert manifest["junit_path"] == junit_path.as_posix()
    assert manifest["coverage_db_paths"] == [db_fragment.as_posix()]


def test_agi_gui_coverage_combine_recovers_missing_success_manifest(tmp_path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "AGI_GUI_COVERAGE_MANIFEST_WAIT_SECONDS", 0.0)
    test_results = tmp_path / "test-results"
    test_results.mkdir()
    recovered_chunk = "pipeline"
    combined_commands: list[list[str]] = []

    for chunk in module.AGI_GUI_COVERAGE_CHUNKS:
        db_fragment = test_results / f"coverage-agi-gui-{chunk}.db.fragment"
        db_fragment.write_text("coverage-db\n", encoding="utf-8")
        (test_results / f"junit-agi-gui-{chunk}.xml").write_text("<testsuite/>\n", encoding="utf-8")
        if chunk == recovered_chunk:
            continue
        (test_results / f"coverage-agi-gui-{chunk}.manifest.json").write_text(
            json.dumps(
                {
                    "schema": module.AGI_GUI_COVERAGE_MANIFEST_SCHEMA,
                    "chunk": chunk,
                    "returncode": 0,
                    "data_file": f"test-results/coverage-agi-gui-{chunk}.db",
                    "junit_path": f"test-results/junit-agi-gui-{chunk}.xml",
                    "coverage_db_paths": [f"test-results/coverage-agi-gui-{chunk}.db.fragment"],
                }
            ),
            encoding="utf-8",
        )

    def fake_run(cmd, check=False):
        combined_commands.append(list(cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "subprocess", SimpleNamespace(run=fake_run))

    try:
        exec(module._agi_gui_coverage_combine_code(), {})
    except SystemExit as exc:
        assert exc.code == 0

    assert combined_commands
    assert "test-results/coverage-agi-gui-pipeline.db.fragment" in combined_commands[0]


def test_agi_gui_coverage_combine_does_not_recover_failing_junit(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "AGI_GUI_COVERAGE_MANIFEST_WAIT_SECONDS", 0.0)
    test_results = tmp_path / "test-results"
    test_results.mkdir()
    recovered_chunk = "pipeline"

    for chunk in module.AGI_GUI_COVERAGE_CHUNKS:
        db_fragment = test_results / f"coverage-agi-gui-{chunk}.db.fragment"
        db_fragment.write_text("coverage-db\n", encoding="utf-8")
        failures = "1" if chunk == recovered_chunk else "0"
        (test_results / f"junit-agi-gui-{chunk}.xml").write_text(
            f'<testsuite failures="{failures}" errors="0"/>\n',
            encoding="utf-8",
        )
        if chunk == recovered_chunk:
            continue
        (test_results / f"coverage-agi-gui-{chunk}.manifest.json").write_text(
            json.dumps(
                {
                    "schema": module.AGI_GUI_COVERAGE_MANIFEST_SCHEMA,
                    "chunk": chunk,
                    "returncode": 0,
                    "data_file": f"test-results/coverage-agi-gui-{chunk}.db",
                    "junit_path": f"test-results/junit-agi-gui-{chunk}.xml",
                    "coverage_db_paths": [f"test-results/coverage-agi-gui-{chunk}.db.fragment"],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.chdir(tmp_path)

    try:
        exec(module._agi_gui_coverage_combine_code(), {})
    except SystemExit as exc:
        assert exc.code == 1

    assert "coverage-agi-gui-pipeline.manifest.json" in capsys.readouterr().out


def test_badges_profile_accepts_component_filter() -> None:
    module = _load_module()

    badges = module._badges_profile(["agilab", "agi-env"])

    assert badges[0].argv[-3:] == ["--components", "agilab", "agi-env"]


def test_selected_profiles_uses_combined_core_profile_by_default() -> None:
    module = _load_module()
    args = SimpleNamespace(profile=None)

    selected = module._selected_profiles(args)

    assert "agi-core-combined" in selected
    assert "cloud-emulators" in selected
    assert "agi-node" not in selected
    assert "agi-cluster" not in selected
    assert "release-proof" not in selected
    assert "security-adoption" not in selected
    assert "production-readiness" not in selected
    assert "ui-robot-contract" not in selected
    assert "ui-robot-canary" not in selected
    assert "ui-frontend-smoke" not in selected
    assert "ui-robot-matrix" not in selected
    assert "ui-artifact-capture-robot" not in selected
    assert "ui-history-robot" not in selected
    assert "ui-mobile-robot" not in selected
    assert "ui-release-evidence-robot" not in selected
    assert "ui-first-proof-robot" not in selected
    assert "ui-keyboard-robot" not in selected
    assert "ui-layout-robot" not in selected
    assert "ui-accessibility-robot" not in selected
    assert "ui-browser-error-robot" not in selected
    assert "ui-above-fold-robot" not in selected
    assert "ui-visual-baseline-robot" not in selected
    assert "ui-trend-robot" not in selected
    assert "ui-cross-browser-robot" not in selected
    assert "hf-install-robot" not in selected
    assert "hf-visual-smoke-robot" not in selected


def test_selected_profiles_can_select_ui_robot_profiles_from_changed_files() -> None:
    module = _load_module()
    args = SimpleNamespace(
        profile=None,
        select_ui_robot_profiles=True,
        changed_file=["tools/agilab_widget_robot.py", "docs/source/_static/page-shots/home.png"],
        changed_base="",
    )

    selected = module._selected_profiles(args)

    assert selected == [
        "ui-robot-contract",
        "ui-robot-canary",
        "ui-artifact-capture-robot",
        "ui-visual-baseline-robot",
        "ui-trend-robot",
    ]


def test_ui_robot_profile_selection_covers_change_classes() -> None:
    module = _load_module()

    assert module.select_ui_robot_profiles_for_files([".github/workflows/coverage.yml"]) == [
        "ui-robot-contract",
        "ui-robot-canary",
        "ui-trend-robot",
    ]
    assert module.select_ui_robot_profiles_for_files(["src/agilab/pages/project.py"]) == [
        "ui-frontend-smoke",
        "ui-robot-matrix",
        "ui-history-robot",
        "ui-mobile-robot",
        "ui-keyboard-robot",
        "ui-layout-robot",
        "ui-accessibility-robot",
        "ui-browser-error-robot",
        "ui-above-fold-robot",
        "ui-trend-robot",
    ]
    assert module.select_ui_robot_profiles_for_files([".github/workflows/huggingface.yml"]) == [
        "hf-install-robot",
        "hf-visual-smoke-robot",
    ]
    assert module.select_ui_robot_profiles_for_files(["tools/hf_space_smoke.py"]) == [
        "hf-install-robot",
        "hf-visual-smoke-robot",
    ]
    assert module.select_ui_robot_profiles_for_files(["tools/hf_space_release_sync.py"]) == [
        "hf-install-robot",
        "hf-visual-smoke-robot",
    ]
    assert module.select_ui_robot_profiles_for_files(["tools/workflow_parity.py"]) == [
        "ui-robot-contract",
        "ui-robot-canary",
        "ui-frontend-smoke",
    ]
    assert module.select_ui_robot_profiles_for_files(["tools/agilab_web_robot.py"]) == [
        "ui-frontend-smoke",
    ]
    assert module.select_ui_robot_profiles_for_files(["pyproject.toml"]) == [
        "ui-frontend-smoke",
    ]
    assert module.select_ui_robot_profiles_for_files(["tools/run_configs/agilab/agilab-run-dev.sh"]) == [
        "ui-frontend-smoke",
    ]
    assert module.select_ui_robot_profiles_for_files(["README.md"]) == [
        "ui-robot-contract"
    ]


def test_selected_ui_robot_profiles_reads_dirty_tree_when_no_files_given(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_git_changed_files",
        lambda base="": ["tools/ui_robot_canary.py"],
    )
    args = SimpleNamespace(
        changed_file=[],
        changed_base="",
    )

    assert module._selected_ui_robot_profiles(args) == [
        "ui-robot-contract",
        "ui-robot-canary",
        "ui-artifact-capture-robot",
        "ui-trend-robot",
    ]


def test_git_changed_files_collects_unique_paths(monkeypatch) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def _fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if argv[:2] == ["git", "diff"] and argv[-1] == "HEAD":
            return SimpleNamespace(returncode=0, stdout="tools/a.py\nshared.py\n")
        if argv == ["git", "diff", "--name-only", "origin/main...HEAD"]:
            return SimpleNamespace(returncode=0, stdout="tools/a.py\nshared.py\n")
        if argv[:3] == ["git", "diff", "--cached"]:
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=0, stdout="shared.py\nuntracked.py\n")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    assert module._git_changed_files() == ["tools/a.py", "shared.py", "untracked.py"]
    assert calls == [
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]

    calls.clear()
    assert module._git_changed_files("origin/main") == ["tools/a.py", "shared.py"]
    assert calls == [["git", "diff", "--name-only", "origin/main...HEAD"]]


def test_installer_profile_adds_contract_check_when_app_path_is_provided() -> None:
    module = _load_module()
    args = SimpleNamespace(
        components=None,
        skills=None,
        app_path="src/agilab/apps/builtin/flight_telemetry_project",
        worker_copy="~/wenv/builtin/flight_telemetry_worker",
    )

    profiles = module._profile_commands(args)
    installer_commands = profiles["installer"]

    assert len(installer_commands) == 3
    assert installer_commands[0].argv == [
        "bash",
        "-n",
        "install.sh",
        "src/agilab/install_apps.sh",
        "src/agilab/core/install.sh",
    ]
    contract = installer_commands[-1]
    assert contract.label == "installer contract check"
    assert contract.argv[-4:] == [
        "--app-path",
        "src/agilab/apps/builtin/flight_telemetry_project",
        "--worker-copy",
        "~/wenv/builtin/flight_telemetry_worker",
    ]


def test_prepare_command_removes_globbed_coverage_fragments(tmp_path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    results_dir = tmp_path / "test-results"
    results_dir.mkdir()
    stale_dir = results_dir / "stale-dir"
    stale_dir.mkdir()
    (stale_dir / "old.txt").write_text("old")
    exact = results_dir / "coverage-agi-gui-pages.db"
    fragment = results_dir / "coverage-agi-gui-pages.db.m41.123.abc"
    unrelated = results_dir / "coverage-agi-gui-views.db.m41.123.abc"
    exact.write_text("exact")
    fragment.write_text("fragment")
    unrelated.write_text("unrelated")

    module._prepare_command(
        module.CommandSpec(
            label="cleanup",
            argv=["true"],
            ensure_dirs=["test-results"],
            remove_paths=[
                "test-results/coverage-agi-gui-pages.db",
                "test-results/coverage-agi-gui-pages.db.*",
                "test-results/stale-dir",
                "test-results/missing-file",
            ],
        )
    )

    assert not exact.exists()
    assert not fragment.exists()
    assert not stale_dir.exists()
    assert unrelated.exists()


def test_run_command_executes_with_env_and_cwd(tmp_path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    workdir = tmp_path / "work"
    spec = module.CommandSpec(
        label="demo",
        argv=[
            sys.executable,
            "-c",
            "import os, pathlib; pathlib.Path('out.txt').write_text(os.environ['DEMO_ENV'])",
        ],
        env={"DEMO_ENV": "ok"},
        cwd="work",
        timeout_seconds=10,
        ensure_dirs=["work"],
    )

    result = module._run_command(spec)

    assert result.returncode == 0
    assert result.cwd == str(workdir)
    assert result.env == {"DEMO_ENV": "ok"}
    assert (workdir / "out.txt").read_text(encoding="utf-8") == "ok"


def test_run_profiles_reuses_cached_success_without_executing(tmp_path, monkeypatch) -> None:
    module = _load_module()
    cache_path = tmp_path / "workflow-parity-cache.json"
    spec = module.CommandSpec(
        label="cached success",
        argv=[sys.executable, "-c", "raise SystemExit(9)"],
        timeout_seconds=10,
    )
    commands_by_profile = {"skills": [spec]}
    monkeypatch.setattr(module, "_profile_commands", lambda _args: commands_by_profile)
    monkeypatch.setattr(module, "_git_changed_files", lambda base="": [])
    args = _cache_args(cache_path)
    descriptions = module._profile_descriptions()
    cache_key = module._run_result_cache_key(
        ["skills"],
        commands_by_profile,
        descriptions,
        changed_files=[],
        cache_path=cache_path,
    )
    cached_result = module.ProfileResult(
        profile="skills",
        description=descriptions["skills"],
        success=True,
        commands=[
            module.CommandResult(
                label=spec.label,
                argv=spec.argv,
                returncode=0,
                duration_seconds=12.0,
                cwd=str(module.REPO_ROOT),
                env={},
            )
        ],
    )
    module._store_run_results(
        cache_path,
        module._empty_result_cache(),
        cache_key,
        ["skills"],
        [cached_result],
    )

    results = module.run_profiles(["skills"], args=args)

    assert results[0].success is True
    assert results[0].commands[0].returncode == 0
    assert results[0].commands[0].duration_seconds == 0.0


def test_run_profiles_records_successful_result_cache(tmp_path, monkeypatch) -> None:
    module = _load_module()
    cache_path = tmp_path / "workflow-parity-cache.json"
    spec = module.CommandSpec(
        label="quick success",
        argv=[sys.executable, "-c", "pass"],
        timeout_seconds=10,
    )
    commands_by_profile = {"skills": [spec]}
    monkeypatch.setattr(module, "_profile_commands", lambda _args: commands_by_profile)
    monkeypatch.setattr(module, "_git_changed_files", lambda base="": [])
    args = _cache_args(cache_path)

    results = module.run_profiles(["skills"], args=args)

    assert results[0].success is True
    cache_key = module._run_result_cache_key(
        ["skills"],
        commands_by_profile,
        module._profile_descriptions(),
        changed_files=[],
        cache_path=cache_path,
    )
    cached = module._cached_run_results(module._load_result_cache(cache_path), cache_key, ["skills"])
    assert cached is not None
    assert cached[0].commands[0].label == "quick success"


def test_run_profiles_does_not_cache_failures(tmp_path, monkeypatch) -> None:
    module = _load_module()
    cache_path = tmp_path / "workflow-parity-cache.json"
    spec = module.CommandSpec(
        label="quick failure",
        argv=[sys.executable, "-c", "raise SystemExit(7)"],
        timeout_seconds=10,
    )
    commands_by_profile = {"skills": [spec]}
    monkeypatch.setattr(module, "_profile_commands", lambda _args: commands_by_profile)
    monkeypatch.setattr(module, "_git_changed_files", lambda base="": [])
    args = _cache_args(cache_path)

    results = module.run_profiles(["skills"], args=args)

    assert results[0].success is False
    cache_key = module._run_result_cache_key(
        ["skills"],
        commands_by_profile,
        module._profile_descriptions(),
        changed_files=[],
        cache_path=cache_path,
    )
    cached = module._cached_run_results(module._load_result_cache(cache_path), cache_key, ["skills"])
    assert cached is None


def test_run_profiles_no_result_cache_bypasses_cached_success(tmp_path, monkeypatch) -> None:
    module = _load_module()
    cache_path = tmp_path / "workflow-parity-cache.json"
    spec = module.CommandSpec(
        label="uncached failure",
        argv=[sys.executable, "-c", "raise SystemExit(5)"],
        timeout_seconds=10,
    )
    commands_by_profile = {"skills": [spec]}
    monkeypatch.setattr(module, "_profile_commands", lambda _args: commands_by_profile)
    monkeypatch.setattr(module, "_git_changed_files", lambda base="": [])
    descriptions = module._profile_descriptions()
    cache_key = module._run_result_cache_key(
        ["skills"],
        commands_by_profile,
        descriptions,
        changed_files=[],
        cache_path=cache_path,
    )
    module._store_run_results(
        cache_path,
        module._empty_result_cache(),
        cache_key,
        ["skills"],
        [
            module.ProfileResult(
                profile="skills",
                description=descriptions["skills"],
                success=True,
                commands=[
                    module.CommandResult(
                        label=spec.label,
                        argv=spec.argv,
                        returncode=0,
                        duration_seconds=0.1,
                        cwd=str(module.REPO_ROOT),
                        env={},
                    )
                ],
            )
        ],
    )

    results = module.run_profiles(["skills"], args=_cache_args(cache_path, no_result_cache=True))

    assert results[0].success is False
    assert results[0].commands[0].returncode == 5


def test_run_profiles_stops_on_first_failure_by_default() -> None:
    module = _load_module()
    args = SimpleNamespace(
        profile=["skills", "badges"],
        components=None,
        skills=None,
        app_path=None,
        worker_copy=None,
        keep_going=False,
    )
    seen = []

    def _fake_runner(spec):
        seen.append(spec.label)
        return module.CommandResult(
            label=spec.label,
            argv=spec.argv,
            returncode=1,
            duration_seconds=0.01,
            cwd=str(module.REPO_ROOT),
            env=spec.env,
        )

    results = module.run_profiles(["skills", "badges"], args=args, runner=_fake_runner)

    assert [result.profile for result in results] == ["skills"]
    assert seen == ["validate codex skills"]
    assert results[0].success is False


def test_result_cache_helpers_round_trip_successful_profile(tmp_path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "RESULT_CACHE_INPUT_GLOBS", ("present.txt", "*.yml", "missing.txt"))
    monkeypatch.setattr(module, "RESULT_CACHE_HASH_LIMIT_BYTES", 128)
    (tmp_path / "present.txt").write_text("present", encoding="utf-8")
    (tmp_path / "workflow.yml").write_text("workflow", encoding="utf-8")
    changed = tmp_path / "changed.txt"
    changed.write_text("changed", encoding="utf-8")
    outside = tmp_path.parent / "outside-workflow-parity.txt"
    outside.write_text("outside", encoding="utf-8")
    cache_path = tmp_path / ".pytest_cache" / "agilab" / "workflow_parity_results.json"
    args = SimpleNamespace(
        result_cache=True,
        no_result_cache=False,
        result_cache_path=str(cache_path),
        changed_file=[changed.as_posix()],
        changed_base="origin/main",
        select_ui_robot_profiles=True,
    )

    assert module._result_cache_enabled(args, module._run_command) is True
    assert module._result_cache_enabled(SimpleNamespace(result_cache=False, no_result_cache=False), module._run_command) is False
    assert module._result_cache_enabled(SimpleNamespace(no_result_cache=True), module._run_command) is False
    assert module._result_cache_enabled(args, lambda _spec: None) is False
    assert module._result_cache_path(args) == cache_path
    assert module._result_cache_changed_files(args) == [changed.as_posix()]
    assert module._repo_relative_or_absolute(tmp_path / "present.txt") == "present.txt"
    assert module._repo_relative_or_absolute(outside) == outside.as_posix()

    input_paths = module._result_cache_input_paths([changed.as_posix(), cache_path.as_posix()], cache_path)

    assert input_paths == ["present.txt", "workflow.yml", "missing.txt", "changed.txt"]
    signatures = module._result_cache_fingerprints([changed.as_posix()], cache_path)
    signatures_by_path = {signature["path"]: signature for signature in signatures}
    assert signatures_by_path["present.txt"]["state"] == "file"
    assert "sha256" in signatures_by_path["present.txt"]
    assert signatures_by_path["missing.txt"]["state"] == "missing"
    assert module._file_sha256(tmp_path / "present.txt") == signatures_by_path["present.txt"]["sha256"]

    command_spec = module.CommandSpec(label="cacheable", argv=["python", "-V"], env={"DEMO": "1"})
    commands_by_profile = {"skills": [command_spec]}
    descriptions = {"skills": "Validate skills"}
    monkeypatch.setattr(module, "_git_head", lambda: "abc123")
    monkeypatch.setenv("CI", "true")

    key = module._run_result_cache_key(
        ["skills"],
        commands_by_profile,
        descriptions,
        changed_files=[changed.as_posix()],
        cache_path=cache_path,
    )

    assert len(key) == 64
    result = module.ProfileResult(
        profile="skills",
        description="Validate skills",
        success=True,
        commands=[
            module.CommandResult(
                label="cacheable",
                argv=["python", "-V"],
                returncode=0,
                duration_seconds=3.5,
                cwd=str(tmp_path),
                env={"DEMO": "1"},
            )
        ],
    )
    state = module._empty_result_cache()
    module._store_run_results(cache_path, state, key, ["skills"], [result])

    loaded = module._load_result_cache(cache_path)
    cached = module._cached_run_results(loaded, key, ["skills"])

    assert loaded["schema"] == module.RESULT_CACHE_SCHEMA
    assert cached is not None
    assert cached[0].profile == "skills"
    assert cached[0].success is True
    assert cached[0].commands[0].duration_seconds == 0.0
    assert cached[0].commands[0].env == {"DEMO": "1"}


def test_result_cache_helpers_reject_invalid_payloads_and_prune(tmp_path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "RESULT_CACHE_MAX_ENTRIES", 2)
    cache_path = tmp_path / "workflow_parity_results.json"

    assert module._load_result_cache(cache_path) == module._empty_result_cache()
    cache_path.write_text("{bad json", encoding="utf-8")
    assert module._load_result_cache(cache_path) == module._empty_result_cache()
    cache_path.write_text(json.dumps({"schema": "wrong", "entries": {}}), encoding="utf-8")
    assert module._load_result_cache(cache_path) == module._empty_result_cache()
    cache_path.write_text(json.dumps({"schema": module.RESULT_CACHE_SCHEMA, "entries": []}), encoding="utf-8")
    assert module._load_result_cache(cache_path) == module._empty_result_cache()

    assert module._command_result_from_cache(None) is None
    assert module._command_result_from_cache({"label": "bad", "argv": [1], "env": {}, "returncode": 0, "cwd": "."}) is None
    assert module._command_result_from_cache({"label": "bad", "argv": [], "env": [], "returncode": 0, "cwd": "."}) is None
    assert module._command_result_from_cache({"label": "bad", "argv": [], "env": {}, "returncode": "0", "cwd": "."}) is None
    assert module._profile_result_from_cache(None) is None
    assert module._profile_result_from_cache({"profile": 3, "description": "desc", "success": True, "commands": []}) is None
    assert module._profile_result_from_cache({"profile": "skills", "description": "desc", "success": True, "commands": {}}) is None
    assert module._profile_result_from_cache(
        {"profile": "skills", "description": "desc", "success": True, "commands": [{"label": "bad"}]}
    ) is None
    assert module._cached_run_results({"entries": []}, "key", ["skills"]) is None
    assert module._cached_run_results({"entries": {"key": {"profiles": ["docs"], "results": []}}}, "key", ["skills"]) is None
    assert module._cached_run_results({"entries": {"key": {"profiles": ["skills"], "results": {}}}}, "key", ["skills"]) is None
    assert (
        module._cached_run_results(
            {"entries": {"key": {"profiles": ["skills"], "results": [{"profile": 3}]}}},
            "key",
            ["skills"],
        )
        is None
    )

    entries = {
        "invalid": "not-a-cache-entry",
        "old": {"stored_at": 1.0},
        "middle": {"stored_at": 2.0},
        "new": {"stored_at": 3.0},
    }
    module._prune_result_cache(entries)

    assert set(entries) == {"middle", "new"}

    bad_state = {"schema": module.RESULT_CACHE_SCHEMA, "entries": []}
    module._write_result_cache(cache_path, bad_state)
    assert json.loads(cache_path.read_text(encoding="utf-8"))["entries"] == []
    missing_entries_path = tmp_path / "missing-entries.json"
    module._store_run_results(
        missing_entries_path,
        {"schema": module.RESULT_CACHE_SCHEMA, "entries": []},
        "key",
        ["skills"],
        [],
    )
    assert not missing_entries_path.exists()


def test_result_cache_helpers_cover_git_and_signature_failures(tmp_path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    def _failing_git_run(_argv, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="fatal")

    monkeypatch.setattr(module.subprocess, "run", _failing_git_run)
    assert module._git_head() == ""

    target = tmp_path / "hash-error.txt"
    target.write_text("content", encoding="utf-8")
    monkeypatch.setattr(module, "_file_sha256", lambda _path: (_ for _ in ()).throw(OSError("denied")))

    signature = module._file_signature("hash-error.txt")

    assert signature["state"] == "file"
    assert signature["sha256_error"] == "OSError"


def test_main_print_only_json_lists_selected_profile_commands(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--profile", "skills", "--skills", "agilab-installer", "--print-only", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profiles"] == ["skills"]
    first = payload["commands"]["skills"][0]
    assert first["label"] == "sync shared skills"
    assert first["argv"] == [
        "python3",
        "tools/sync_agent_skills.py",
        "--skills",
        "agilab-installer",
    ]


def test_main_list_profiles_and_print_only_human(capsys) -> None:
    module = _load_module()

    assert module.main(["--list-profiles", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert "skills" in listed

    assert module.main(["--list-profiles"]) == 0
    assert "skills:" in capsys.readouterr().out

    assert module.main(["--profile", "skills", "--print-only"]) == 0
    printed = capsys.readouterr().out
    assert "Selected profiles:" in printed
    assert "- skills:" in printed


def test_main_runs_profile_and_renders_results(capsys, monkeypatch) -> None:
    module = _load_module()
    result = module.ProfileResult(
        profile="skills",
        description="Validate skills",
        success=True,
        commands=[
            module.CommandResult(
                label="validate codex skills",
                argv=["python", "tools/validate_agent_skills.py"],
                returncode=0,
                duration_seconds=0.01,
                cwd=str(module.REPO_ROOT),
                env={},
            )
        ],
    )
    monkeypatch.setattr(module, "run_profiles", lambda _selected, *, args: [result])

    assert module.main(["--profile", "skills", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["success"] is True

    assert module.main(["--profile", "skills"]) == 0
    rendered = capsys.readouterr().out
    assert "[PASS] skills" in rendered
    assert "validate codex skills" in rendered


def test_main_accepts_production_readiness_profile(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--profile", "production-readiness", "--print-only", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profiles"] == ["production-readiness"]
    command = payload["commands"]["production-readiness"][0]
    assert command["label"] == "production readiness gate"
    assert command["argv"][-5:] == [
        "tools/production_readiness_report.py",
        "--run-docs-profile",
        "--output",
        "test-results/production-readiness.json",
        "--compact",
    ]
