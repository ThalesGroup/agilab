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


def test_render_pyx_adds_locals_decorator_above_def() -> None:
    source = '''class Demo:
    def run(self, values):
        """Worker method."""
        total = 0.0
        for i in range(len(values)):
            total += 1.0
        return total
'''

    pyx_source = previewer.render_pyx(source, previewer.analyze_source(source))

    assert pyx_source.startswith("import cython\n")
    assert (
        "    @cython.locals(i=cython.Py_ssize_t, total=cython.double)\n"
        "    def run(self, values):\n"
    ) in pyx_source
    assert "cdef" not in pyx_source


def test_existing_source_annotations_are_not_duplicated() -> None:
    source = """
def compute():
    total: float = 0.0
    flag: bool = True
    inferred = 0.0
    return total, flag, inferred
"""

    preview = previewer.analyze_source(source)
    pyx_source = previewer.render_pyx(source, preview)

    assert "@cython.locals(inferred=cython.double)\ndef compute():" in pyx_source
    assert "total=" not in pyx_source
    assert "flag=" not in pyx_source
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
    assert "@cython.locals(i=cython.Py_ssize_t, total=cython.double)" in output_path.read_text(encoding="utf-8")
    assert {item["name"] for item in report["declarations"]} == {"i", "total"}
    assert report["degraded_reasons"] == []


def test_range_bound_that_overflows_py_ssize_t_blocks_loop_index() -> None:
    # Regression: a range() bound that is a compile-time-constant integer larger
    # than Py_ssize_t must NOT type the loop index. ``2**64 - 1`` is the
    # adversarial case — the >63-bit power is provably out-of-range, and the
    # trailing ``- 1`` must not cancel that back into range (which would wrongly
    # type ``i`` as Py_ssize_t and overflow at runtime).
    for bound in ("2**64 - 1", "0, 2**64 - 1, 1", "-(2**100), 5", "10**20"):
        source = (
            "def run():\n"
            f"    for i in range({bound}):\n"
            "        break\n"
            "    return i\n"
        )
        preview = previewer.analyze_source(source)
        typed = {item.name for item in preview.typed_variables}
        skipped = {item.name for item in preview.skipped}
        assert "i" not in typed, f"loop index wrongly typed for range({bound})"
        assert "i" in skipped, f"loop index not recorded as skipped for range({bound})"


def test_range_bound_within_py_ssize_t_still_types_loop_index() -> None:
    # Guard the optimization the overflow fix must preserve: a fitting constant
    # bound and a variable bound both still type the loop index as Py_ssize_t.
    source = (
        "def run(values):\n"
        "    count = len(values)\n"
        "    for i in range(1000):\n"
        "        pass\n"
        "    for j in range(count):\n"
        "        pass\n"
        "    return count\n"
    )
    preview = previewer.analyze_source(source)
    typed = {(item.name, item.cython_type) for item in preview.typed_variables}
    assert ("i", "Py_ssize_t") in typed
    assert ("j", "Py_ssize_t") in typed
