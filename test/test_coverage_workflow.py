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
