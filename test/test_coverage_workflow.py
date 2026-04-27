from __future__ import annotations

from pathlib import Path
import re


WORKFLOW_PATH = Path(".github/workflows/coverage.yml")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _agi_gui_run_block() -> str:
    workflow_text = _workflow_text()
    start_marker = "      - name: Run agi-gui coverage"
    end_marker = "      - name: Upload JUnit results"
    start = workflow_text.index(start_marker)
    end = workflow_text.index(end_marker, start)
    return workflow_text[start:end]


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


def test_agi_gui_coverage_includes_about_agilab_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_about_agilab_helpers.py" in run_block


def test_agi_gui_coverage_includes_cluster_doctor_helpers() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_cluster_flight_validation.py" in run_block
    assert "test/test_cluster_lan_discovery.py" in run_block


def test_agi_gui_coverage_includes_pipeline_run_controls() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_pipeline_run_controls.py" in run_block


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


def test_agi_gui_workflow_wildcard_covers_all_workflow_tests() -> None:
    run_block = _agi_gui_run_block()
    assert "test/test_*_workflow.py" in run_block

    listed_tests: set[str] = set()
    for token in re.findall(r"test/test_[^\s\\]+_workflow\.py", run_block):
        if "*" in token:
            listed_tests.update(path.as_posix() for path in Path().glob(token))
        else:
            listed_tests.add(token)

    workflow_tests = {path.as_posix() for path in Path("test").glob("test_*_workflow.py")}
    assert "test/test_coverage_workflow.py" in workflow_tests
    assert "test/test_pypi_publish_workflow.py" in workflow_tests

    missing = sorted(workflow_tests - listed_tests)
    extra = sorted(listed_tests - workflow_tests)

    assert not missing and not extra, (
        f"coverage.yml agi-gui workflow wildcard is out of sync; "
        f"missing={missing}, extra={extra}"
    )
