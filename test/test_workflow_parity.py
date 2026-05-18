from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("tools/workflow_parity.py").resolve()
WORKFLOW_PATH = Path(".github/workflows/coverage.yml")


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


def _load_module():
    spec = importlib.util.spec_from_file_location("workflow_parity_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _coverage_workflow_agi_gui_targets() -> dict[str, list[str]]:
    chunks: dict[str, list[str]] = {}
    current_chunk: str | None = None
    for line in WORKFLOW_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        match = re.fullmatch(r"run_gui_chunk ([a-z-]+) \\", stripped)
        if match:
            current_chunk = match.group(1)
            chunks[current_chunk] = []
            continue
        if current_chunk is None:
            continue
        if not stripped:
            current_chunk = None
            continue
        if stripped.startswith(("test/", "src/agilab/")):
            chunks[current_chunk].append(stripped.removesuffix("\\").strip())
            continue
        if stripped.startswith("-"):
            continue
        current_chunk = None
    return chunks


def _parity_agi_gui_targets(module) -> dict[str, list[str]]:
    args = SimpleNamespace(components=None, skills=None, app_path=None, worker_copy=None)
    commands = module._profile_commands(args)["agi-gui"][: len(module.AGI_GUI_COVERAGE_CHUNKS)]
    targets_by_chunk: dict[str, list[str]] = {}
    for command in commands:
        match = re.fullmatch(r"agi-gui coverage \(([a-z-]+)\)", command.label)
        assert match is not None
        targets_by_chunk[match.group(1)] = [
            arg for arg in command.argv if arg.startswith(("test/", "src/agilab/"))
        ]
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
    ui_robot_contract = profiles["ui-robot-contract"][0]
    ui_robot_matrix = profiles["ui-robot-matrix"][0]
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
    assert "test-results/coverage-agi-gui-pipeline.db.*" in agi_gui_commands[1].remove_paths
    assert "--data-file=test-results/coverage-agi-gui-support.db" in agi_gui_commands[0].argv
    agi_gui_combine_argv = " ".join(agi_gui_combine.argv)
    assert "'coverage', 'combine'" in agi_gui_combine_argv
    assert "--keep" in agi_gui_combine_argv
    assert agi_gui_combine.env["COVERAGE_FILE"] == ".coverage.agi-gui"
    assert "range(120)" in agi_gui_combine_argv
    assert "parent.glob(base_path.name + '*')" in agi_gui_combine_argv
    assert "stat().st_size > 0" in agi_gui_combine_argv
    assert "test-results/coverage-agi-gui-pipeline.db" in agi_gui_combine_argv
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
    assert "test/test_ga_regression_selector.py" in agi_gui_argv
    assert "test/test_pipeline_mistral.py" in agi_gui_argv
    assert "test/test_pipeline_openai_compatible.py" in agi_gui_argv
    assert "test/test_notebook_colab_support.py" in agi_gui_argv
    assert "test/test_pinned_expander.py" in agi_gui_argv
    assert "test/test_workflow_ui.py" in agi_gui_argv
    assert "test/test_agilab_web_robot.py" in agi_gui_argv
    assert "test/test_agilab_widget_robot_matrix.py" in agi_gui_argv
    assert "test/test_agilab_widget_robot.py" in agi_gui_argv
    assert "test/test_first_launch_robot.py" in agi_gui_argv
    assert "test/test_screenshot_manifest.py" in agi_gui_argv
    assert "test/test_ui_robot_coverage_contract.py" in agi_gui_argv
    assert "test/test_ui_robot_failure_replay.py" in agi_gui_argv
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
    assert release_proof.label == "fresh source clone first-proof install"
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
    assert ui_robot_contract.label == "ui robot coverage contract"
    assert ui_robot_contract.timeout_seconds == 2 * 60
    assert ui_robot_contract.argv[-2:] == ["tools/ui_robot_coverage_contract.py", "--json"]
    assert ui_robot_matrix.label == "ui robot matrix"
    assert ui_robot_matrix.timeout_seconds == 60 * 60
    assert ui_robot_matrix.remove_paths == ["test-results/ui-robot-matrix", "screenshots/ui-robot-matrix"]
    assert "tools/agilab_widget_robot_matrix.py" in ui_robot_matrix.argv
    assert "isolated-core-pages" in ui_robot_matrix.argv
    assert "isolated-entry-and-app-pages" in ui_robot_matrix.argv
    assert "isolated-project-page" in ui_robot_matrix.argv
    assert "isolated-project-notebook-import" in ui_robot_matrix.argv
    assert "isolated-project-import-sidebar" in ui_robot_matrix.argv
    assert "isolated-project-rename-sidebar" in ui_robot_matrix.argv
    assert "isolated-settings-page" in ui_robot_matrix.argv
    assert "--quiet-progress" in ui_robot_matrix.argv
    assert "--json" in ui_robot_matrix.argv
    assert "--screenshot-dir" in ui_robot_matrix.argv
    assert "screenshots/ui-robot-matrix" in ui_robot_matrix.argv
    assert "test-results/ui-robot-matrix/failure-bundles" in ui_robot_matrix.argv
    assert _has_with_dependency(ui_robot_matrix.argv, "playwright")
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
    assert hf_install_robot.label == "hf flight telemetry install robot"
    assert hf_install_robot.timeout_seconds == 25 * 60
    assert hf_install_robot.remove_paths == ["test-results/hf-install-robot", "screenshots/hf-install-robot"]
    assert "tools/agilab_widget_robot_matrix.py" in hf_install_robot.argv
    assert "hf-flight-telemetry-install" in hf_install_robot.argv
    assert "flight_telemetry_project" in hf_install_robot.argv
    assert "https://huggingface.co/spaces/jpmorard/agilab?active_app=flight_telemetry_project" in hf_install_robot.argv
    assert "screenshots/hf-install-robot" in hf_install_robot.argv
    assert "test-results/hf-install-robot/failure-bundles" in hf_install_robot.argv
    assert _has_with_dependency(hf_install_robot.argv, "playwright")
    assert hf_visual_smoke_robot.label == "hf flight telemetry visual smoke robot"
    assert hf_visual_smoke_robot.timeout_seconds == 25 * 60
    assert hf_visual_smoke_robot.remove_paths == ["test-results/hf-visual-smoke-robot", "screenshots/hf-visual-smoke-robot"]
    assert "hf-flight-telemetry-visual-smoke" in hf_visual_smoke_robot.argv
    assert "screenshots/hf-visual-smoke-robot" in hf_visual_smoke_robot.argv
    assert _has_with_dependency(hf_visual_smoke_robot.argv, "playwright")


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
    assert "ui-robot-matrix" not in selected
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


def test_installer_profile_adds_contract_check_when_app_path_is_provided() -> None:
    module = _load_module()
    args = SimpleNamespace(
        components=None,
        skills=None,
        app_path="src/agilab/apps/builtin/flight_telemetry_project",
        worker_copy="~/wenv/builtin/flight_worker",
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
        "~/wenv/builtin/flight_worker",
    ]


def test_prepare_command_removes_globbed_coverage_fragments(tmp_path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    results_dir = tmp_path / "test-results"
    results_dir.mkdir()
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
            ],
        )
    )

    assert not exact.exists()
    assert not fragment.exists()
    assert unrelated.exists()


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
