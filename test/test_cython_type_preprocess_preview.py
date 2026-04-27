from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools/cython_type_preprocess_preview.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("cython_type_preprocess_preview", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


previewer = _load_module()


def test_analyze_source_keeps_only_stable_native_candidates() -> None:
    source = """
def compute(values):
    total = 0.0
    ok = True
    count = len(values)
    dynamic = 0.0
    dynamic = make_value()
    label = "demo"
    for i in range(count):
        total += 1.0
    for item in values:
        label = item
    return total, ok, count
"""

    preview = previewer.analyze_source(source)
    typed = {(item.name, item.cython_type) for item in preview.typed_variables}
    skipped = {item.name for item in preview.skipped}

    assert typed == {
        ("count", "Py_ssize_t"),
        ("i", "Py_ssize_t"),
        ("ok", "bint"),
        ("total", "double"),
    }
    assert {"dynamic", "item", "label"} <= skipped


def test_render_pyx_inserts_declarations_after_function_docstring() -> None:
    source = '''class Demo:
    def run(self, values):
        """Worker method."""
        total = 0.0
        for i in range(len(values)):
            total += 1.0
        return total
'''

    pyx_source = previewer.render_pyx(source, previewer.analyze_source(source))

    assert '        """Worker method."""\n        cdef Py_ssize_t i\n' in pyx_source
    assert "        cdef double total\n        total = 0.0\n" in pyx_source


def test_existing_source_annotations_are_not_duplicated_as_cdef() -> None:
    source = """
def compute():
    total: float = 0.0
    flag: bool = True
    inferred = 0.0
    return total, flag, inferred
"""

    preview = previewer.analyze_source(source)
    pyx_source = previewer.render_pyx(source, preview)

    assert "cdef double inferred" in pyx_source
    assert "cdef double total" not in pyx_source
    assert "cdef bint flag" not in pyx_source
    assert {item.name for item in preview.skipped} == {"flag", "total"}


def test_cli_writes_pyx_and_report(tmp_path: Path) -> None:
    input_path = tmp_path / "worker.py"
    output_path = tmp_path / "worker.pyx"
    report_path = tmp_path / "report.json"
    input_path.write_text(
        "def run(values):\n"
        "    total = 0.0\n"
        "    for i in range(len(values)):\n"
        "        total += 1.0\n"
        "    return total\n",
        encoding="utf-8",
    )

    exit_code = previewer.main(
        [
            str(input_path),
            "--output",
            str(output_path),
            "--report-json",
            str(report_path),
            "--fail-on-empty",
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert output_path.exists()
    assert "cdef double total" in output_path.read_text(encoding="utf-8")
    assert {item["name"] for item in report["declarations"]} == {"i", "total"}
