from __future__ import annotations

from pathlib import Path
import re


WORKFLOW_PATH = Path(".github/workflows/coverage.yml")


def _agi_gui_run_block() -> str:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    start_marker = "      - name: Run agi-gui coverage"
    end_marker = "      - name: Upload JUnit results"
    start = workflow_text.index(start_marker)
    end = workflow_text.index(end_marker, start)
    return workflow_text[start:end]


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


def test_agi_gui_coverage_includes_pipeline_run_controls() -> None:
    run_block = _agi_gui_run_block()

    assert "test/test_pipeline_run_controls.py" in run_block


def test_agi_gui_coverage_includes_report_helper_regressions() -> None:
    run_block = _agi_gui_run_block()

    expected_targets = {
        "test/test_compatibility_report.py",
        "test/test_connector_registry.py",
        "test/test_data_connector*_report.py",
        "test/test_global_pipeline*_report.py",
        "test/test_multi_app_dag_report.py",
        "test/test_notebook*_report.py",
        "test/test_production_readiness_report.py",
        "test/test_run_manifest.py",
    }

    missing = sorted(target for target in expected_targets if target not in run_block)

    assert not missing, f"agi-gui coverage is missing report/helper targets: {missing}"
