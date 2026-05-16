from __future__ import annotations

from pathlib import Path
import re


WORKFLOW_PATH = Path(".github/workflows/coverage.yml")
AGI_ENV_COVERAGE_CONFIG = Path(".coveragerc.agi-env")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _agi_gui_run_block() -> str:
    return _run_block("Run agi-gui coverage", "Upload JUnit results")


def _agi_env_run_block() -> str:
    return _run_block("Run agi-env coverage", "Upload agi-env coverage")


def _agi_core_run_block() -> str:
    return _run_block("Run agi-node + agi-cluster coverage", "Upload agi-node coverage")


def _run_block(start_name: str, end_name: str) -> str:
    workflow_text = _workflow_text()
    start_marker = f"      - name: {start_name}"
    end_marker = f"      - name: {end_name}"
    start = workflow_text.index(start_marker)
    end = workflow_text.index(end_marker, start)
    return workflow_text[start:end]


def _step_block(step_name: str) -> str:
    workflow_text = _workflow_text()
    start_marker = f"      - name: {step_name}"
    start = workflow_text.index(start_marker)
    next_step = workflow_text.find("\n      - name:", start + len(start_marker))
    if next_step == -1:
        next_step = len(workflow_text)
    return workflow_text[start:next_step]


def test_core_coverage_runs_shared_core_suite_once_for_node_and_cluster() -> None:
    workflow_text = _workflow_text()

    assert "  agi-core:" in workflow_text
    assert "Run agi-node + agi-cluster coverage" in workflow_text
    assert "--source=agi_node,agi_cluster" in workflow_text
    assert workflow_text.count("src/agilab/core/test") == 1
    assert "coverage-agi-node.xml" in workflow_text
    assert "coverage-agi-cluster.xml" in workflow_text
    assert "      - agi-core" in workflow_text
    assert "      - agi-node" not in workflow_text
    assert "      - agi-cluster" not in workflow_text


def test_coverage_push_trigger_is_path_filtered_for_cost_control() -> None:
    workflow_text = _workflow_text()
    trigger_block = workflow_text.split("workflow_dispatch:", 1)[0]

    for path in (
        '".coveragerc*"',
        '".github/workflows/coverage.yml"',
        '"pyproject.toml"',
        '"src/**"',
        '"test/**"',
        '"tools/coverage_badge_guard.py"',
        '"tools/generate_component_coverage_badges.py"',
        '"tools/workflow_parity.py"',
        '"uv.lock"',
    ):
        assert path in trigger_block
    assert '"docs/**"' not in trigger_block
    assert '"README.md"' not in trigger_block
    assert '"badges/**"' not in trigger_block


def test_agi_env_coverage_installs_streamlit_ui_dependency() -> None:
    run_block = _agi_env_run_block()

    assert "--with streamlit" in run_block


def test_agi_env_coverage_excludes_ipython_signature_compatibility_line() -> None:
    config_text = AGI_ENV_COVERAGE_CONFIG.read_text(encoding="utf-8")

    assert r"_tb_kwargs\['theme_name'\] = 'NoColor'" in config_text


def test_agi_core_coverage_installs_parquet_engine() -> None:
    run_block = _agi_core_run_block()

    assert run_block.count("--with fastparquet") == 3


def test_agi_gui_coverage_lists_all_root_view_tests() -> None:
    run_block = _agi_gui_run_block()
    listed_tests: set[str] = set()
    for token in re.findall(r"test/test_view[^\s\\]+\.py", run_block):
        if "*" in token:
            listed_tests.update(path.as_posix() for path in Path().glob(token))
        else:
            listed_tests.add(token)
    expected_tests = {path.as_posix() for path in Path("test").glob("test_view*.py")}

    missing = sorted(expected_tests - listed_tests)
    extra = sorted(listed_tests - expected_tests)

    assert not missing and not extra, (
        f"coverage.yml agi-gui job is out of sync with root test_view files; "
        f"missing={missing}, extra={extra}"
    )


def test_agi_gui_coverage_includes_notebook_colab_support_helper() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_notebook_colab_support.py" in run_block


def test_agi_gui_coverage_includes_first_proof_and_notebook_import_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_first_proof_wizard.py" in run_block
    assert "test/test_notebook_import_doctor.py" in run_block


def test_agi_gui_coverage_includes_pages_lib_package_tests() -> None:
    run_block = _agi_gui_run_block()

    assert "src/agilab/lib/agi-gui/test" in run_block


def test_agi_gui_coverage_uses_chunked_append_profile() -> None:
    run_block = _agi_gui_run_block()
    junit_upload = _step_block("Upload JUnit results")

    assert "run_gui_chunk support" in run_block
    assert "run_gui_chunk pipeline" in run_block
    assert "run_gui_chunk pages" in run_block
    assert "run_gui_chunk views" in run_block
    assert "run_gui_chunk reports" in run_block
    assert "--append" in run_block
    assert "python -m coverage xml" in run_block
    assert "--cov=src/agilab" not in run_block
    assert "test-results/junit-agi-gui-*.xml" in junit_upload


def test_agi_gui_coverage_installs_ui_and_viz_extras_in_clean_ci_env() -> None:
    run_block = _agi_gui_run_block()

    assert run_block.count("--extra ui") >= 2
    assert run_block.count("--extra viz") >= 2


def test_agi_gui_coverage_includes_about_agilab_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_about_agilab_helpers.py" in run_block


def test_agi_gui_coverage_includes_core_ui_runtime_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_action_execution.py" in run_block
    assert "test/test_import_guard.py" in run_block
    assert "test/test_logging_utils.py" in run_block
    assert "test/test_page_bundle_registry.py" in run_block
    assert "test/test_runtime_diagnostics.py" in run_block
    assert "test/test_snippet_registry.py" in run_block


def test_agi_gui_coverage_includes_cluster_doctor_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_cluster_flight_validation.py" in run_block
    assert "test/test_cluster_lan_discovery.py" in run_block


def test_agi_gui_coverage_includes_dag_execution_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_dag_execution_adapters.py" in run_block
    assert "test/test_dag_execution_registry.py" in run_block
    assert "test/test_dag_run_engine.py" in run_block


def test_agi_gui_coverage_includes_workflow_contract_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_evidence_graph.py" in run_block
    assert "test/test_multi_app_dag_draft.py" in run_block
    assert "test/test_multi_app_dag_templates.py" in run_block
    assert "test/test_workflow_run_manifest.py" in run_block
    assert "test/test_workflow_runtime_contract.py" in run_block


def test_agi_gui_coverage_includes_pipeline_run_controls() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_pipeline_ai_support.py" in run_block
    assert "test/test_pipeline_page_state.py" in run_block
    assert "test/test_pipeline_recipe_memory.py" in run_block
    assert "test/test_pipeline_run_controls.py" in run_block


def test_agi_gui_coverage_includes_orchestrate_page_support() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_orchestrate_page_support.py" in run_block


def test_agi_gui_coverage_explicit_test_files_exist() -> None:
    run_block = _agi_gui_run_block()
    explicit_tests: set[Path] = set()
    for line in run_block.splitlines():
        token = line.strip().removesuffix("\\").strip()
        if not token.startswith("test/") or "*" in token:
            continue
        explicit_tests.add(Path(token))

    missing = sorted(path.as_posix() for path in explicit_tests if not path.is_file())

    assert not missing, f"coverage.yml references missing explicit test files: {missing}"


def test_agi_gui_coverage_includes_tracking_facade() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_tracking.py" in run_block


def test_agi_gui_coverage_includes_orchestrate_page_state() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_orchestrate_page_state.py" in run_block


def test_agi_gui_coverage_includes_analysis_page_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_analysis_page_helpers.py" in run_block


def test_agi_gui_coverage_includes_support_parity_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_agent_run.py" in run_block
    assert "test/test_agent_tool_safety.py" in run_block
    assert "test/test_code_editor_support.py" in run_block
    assert "test/test_env_file_utils.py" in run_block
    assert "test/test_security_check.py" in run_block
    assert "test/test_secret_uri.py" in run_block
    assert "test/test_ui_public_bind_guard.py" in run_block
    assert "test/test_venv_linker.py" in run_block
    assert "test/test_workflow_ui.py" in run_block


def test_agi_gui_coverage_includes_direct_generation_and_selector_tests() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_generated_actions.py" in run_block
    assert "test/test_page_project_selector.py" in run_block


def test_agi_gui_coverage_includes_report_helper_regressions() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_*_report.py" in run_block


def test_agi_gui_report_wildcard_covers_all_report_tests() -> None:
    run_block = _agi_gui_run_block()
    assert "test/test_*_report.py" in run_block

    listed_tests: set[str] = set()
    for token in re.findall(r"test/test_[^\s\\]+_report\.py", run_block):
        if "*" in token:
            listed_tests.update(path.as_posix() for path in Path().glob(token))
        else:
            listed_tests.add(token)

    report_tests = {path.as_posix() for path in Path("test").glob("test_*_report.py")}
    assert "test/test_run_diff_evidence_report.py" in report_tests
    assert "test/test_ci_artifact_harvest_report.py" in report_tests

    missing = sorted(report_tests - listed_tests)
    extra = sorted(listed_tests - report_tests)

    assert not missing and not extra, (
        f"coverage.yml agi-gui report wildcard is out of sync; "
        f"missing={missing}, extra={extra}"
    )


def test_agi_gui_coverage_excludes_workflow_policy_tests() -> None:
    run_block = _agi_gui_run_block()
    assert "test/test_*_workflow.py" not in run_block


def test_codecov_uploads_are_blocking_coverage_publication_gates() -> None:
    upload_steps = [
        "Upload agi-env coverage to Codecov",
        "Upload agi-node coverage to Codecov",
        "Upload agi-cluster coverage to Codecov",
        "Upload agi-gui coverage to Codecov",
        "Upload repo-wide agilab coverage to Codecov",
    ]

    for step_name in upload_steps:
        block = _step_block(step_name)

        assert "uses: codecov/codecov-action@" in block
        assert "# v6" in block
        assert "continue-on-error: true" not in block
        assert "fail_ci_if_error: true" in block


def test_coverage_artifacts_have_short_retention_for_cost_control() -> None:
    for step_name in (
        "Archive agi-env coverage XML",
        "Archive agi-node coverage XML",
        "Archive agi-cluster coverage XML",
        "Upload JUnit results",
        "Archive agi-gui coverage XML",
    ):
        block = _step_block(step_name)

        assert "uses: actions/upload-artifact@" in block
        assert "# v7" in block
        assert "retention-days: 3" in block
