"""Real-compile soundness gate for the Cython type preprocessor.

Each adversarial snippet is run through ``preprocess_source``, the output is
compiled with REAL cythonize into a shared tmp build dir, and the compiled
behavior is compared against the pure-CPython exec of the original source.
A raw (un-preprocessed) cythonized baseline guards against blaming the
preprocessor for base Cython limitations.

Contract notes:
- Marked ``cython_compile``; the whole suite skips automatically when Cython
  or a working C toolchain is unavailable (one cheap probe per session).
- Assertions target COMPILED BEHAVIOR (and the ``PreprocessPreview`` API for
  the over-blocking guard), never the emitted text format, so the suite stays
  valid if emission moves from cdef-splicing to ``@cython.locals`` decorators.
- Known divergences owned by other plan items are encoded as imperative
  xfails; they flip to passing automatically once those items land.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import cython_worker_verify as verify  # noqa: E402
from agi_node.agi_dispatcher.cython_type_preprocess import preprocess_source  # noqa: E402


pytestmark = pytest.mark.cython_compile


@pytest.fixture(scope="session")
def cython_build_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One shared build dir per session; skip the suite when no toolchain."""

    pytest.importorskip("Cython", reason="Cython is required for compile gate tests")
    build_root = tmp_path_factory.mktemp("cython-compile-gate")
    try:
        probe = verify.compile_python_module(
            build_root,
            "_agilab_toolchain_probe",
            "def ping():\n    return 41 + 1\n",
        )
    # Defensive: any toolchain failure (missing C compiler, broken setuptools)
    # must skip this marker-gated suite instead of failing it.
    except Exception as exc:
        pytest.skip(f"C toolchain unavailable for Cython compile tests: {exc}")
    assert probe.ping() == 42
    return build_root


@dataclass(frozen=True)
class Case:
    name: str
    source: str
    entry: str
    args: tuple[Any, ...] = ()
    # Over-blocking guard: the straightforward kernel must keep typed locals.
    expect_typed: bool = False
    # Known divergence owned by another plan item -> imperative xfail until it lands.
    pending: str | None = None


CASES = (
    Case(
        name="starred_unpack",
        source=(
            "def run():\n"
            "    a, *b, c = [1.5, 2.5, 3.5, 4.5]\n"
            "    total = a + c\n"
            "    return (a, b, c, total)\n"
        ),
        entry="run",
    ),
    Case(
        name="match_capture",
        source=(
            "def run(v):\n"
            "    match v:\n"
            "        case [x, *rest]:\n"
            "            total = 1.5\n"
            "            return total + x + len(rest)\n"
            "        case _:\n"
            "            return 0.0\n"
        ),
        entry="run",
        args=([2.0, 1, 2],),
    ),
    Case(
        name="import_alias",
        source=(
            "def run():\n"
            "    import math as flag\n"
            "    out = float(flag.floor(2.9))\n"
            "    flag = 1.5\n"
            "    return out + flag\n"
        ),
        entry="run",
    ),
    Case(
        name="shadowed_range_builtin",
        source=(
            "def run():\n"
            "    range = lambda n: [0.25, 0.75]\n"
            "    total = 0.0\n"
            "    for i in range(2):\n"
            "        total = total + i\n"
            "    return total\n"
        ),
        entry="run",
    ),
    Case(
        name="inline_one_liner_def",
        source="def run(): x = 1.5; y = x * 2.0; return y\n",
        entry="run",
    ),
    Case(
        name="docstring_sharing_body_line",
        source=(
            "def run():\n"
            '    "doc"; x = 1.5\n'
            "    return x * 2.0\n"
        ),
        entry="run",
        pending=(
            "plan items 6/8: declaration spliced after a docstring that shares "
            "its line with a body statement lands after first use"
        ),
    ),
    Case(
        name="overloaded_comparison",
        source=(
            "class Vec:\n"
            "    def __init__(self, values):\n"
            "        self.values = list(values)\n"
            "\n"
            "    def __gt__(self, other):\n"
            "        return Vec([1.0 if v > other else 0.0 for v in self.values])\n"
            "\n"
            "    def total(self):\n"
            "        out = 0.0\n"
            "        for v in self.values:\n"
            "            out = out + v\n"
            "        return out\n"
            "\n"
            "def run():\n"
            "    data = Vec([0.5, -1.5, 2.5])\n"
            "    mask = data > 0\n"
            "    return mask.total()\n"
        ),
        entry="run",
    ),
    Case(
        name="conditional_assignment_mixed_types",
        source=(
            "def run(flag):\n"
            "    if flag:\n"
            "        x = 1.0\n"
            "    else:\n"
            "        x = 'fallback'\n"
            "    return x\n"
        ),
        entry="run",
        args=(False,),
    ),
    Case(
        name="conditional_assignment_both_branches",
        source=(
            "def run(flag):\n"
            "    if flag:\n"
            "        y = 2.5\n"
            "    else:\n"
            "        y = 3.5\n"
            "    return y\n"
        ),
        entry="run",
        args=(False,),
    ),
    Case(
        name="huge_int_range_bound",
        source=(
            "def run():\n"
            "    for i in range(10**20):\n"
            "        break\n"
            "    return i\n"
        ),
        entry="run",
        pending=(
            "plan item 14: range() bounds beyond Py_ssize_t must not type the "
            "loop index"
        ),
    ),
    Case(
        name="deleted_name",
        source=(
            "def run():\n"
            "    x = 1.5\n"
            "    y = x + 1.0\n"
            "    del x\n"
            "    return y\n"
        ),
        entry="run",
    ),
    Case(
        name="numeric_kernel",
        source=(
            "def kernel(n):\n"
            "    total = 0.0\n"
            "    scale = 0.5\n"
            "    count = len([])\n"
            "    for i in range(n):\n"
            "        contrib = i * scale\n"
            "        flag = contrib > 100.0\n"
            "        if flag:\n"
            "            total = total + 1.0\n"
            "        else:\n"
            "            total = total + contrib / 4.0\n"
            "    return total\n"
        ),
        entry="kernel",
        args=(500,),
        expect_typed=True,
    ),
)


def _entry_spec(case: Case) -> verify.EntrySpec:
    return verify.EntrySpec(
        module=case.name,
        function=case.entry,
        args=tuple(case.args),
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_preprocessed_compile_matches_cpython(case: Case, cython_build_root: Path) -> None:
    spec = _entry_spec(case)
    python_module = verify.load_python_module(
        f"_gate_python_{case.name}",
        case.source,
        filename=f"<{case.name}>",
    )
    expected = verify.workload_outcome(python_module, spec)

    preprocessed, preview = preprocess_source(case.source, filename=case.name)
    if case.expect_typed:
        assert preview.typed_variables, (
            "over-blocking regression: the straightforward numeric kernel "
            "produced no typed locals"
        )

    try:
        raw_module = verify.compile_python_module(
            cython_build_root,
            f"_gate_raw_{case.name}",
            case.source,
        )
    except verify.WorkerCompileError as exc:
        pytest.skip(
            "base Cython cannot compile this construct "
            f"(not a preprocessor defect): {str(exc)[:300]}"
        )

    raw_outcome = verify.workload_outcome(raw_module, spec)
    assert verify.outcomes_equivalent(expected, raw_outcome), (
        "raw cythonized baseline diverged from CPython (environment issue, "
        f"not the preprocessor): expected {expected!r}, got {raw_outcome!r}"
    )

    try:
        preprocessed_module = verify.compile_python_module(
            cython_build_root,
            f"_gate_pre_{case.name}",
            preprocessed,
        )
    except verify.WorkerCompileError as exc:
        if case.pending:
            pytest.xfail(f"known pending divergence ({case.pending}): {str(exc)[:300]}")
        pytest.fail(
            f"preprocessed source no longer compiles for {case.name}: {str(exc)[:1200]}"
        )

    preprocessed_outcome = verify.workload_outcome(preprocessed_module, spec)
    if not verify.outcomes_equivalent(expected, preprocessed_outcome):
        if case.pending:
            pytest.xfail(
                f"known pending divergence ({case.pending}): expected "
                f"{expected!r}, got {preprocessed_outcome!r}"
            )
        pytest.fail(
            "compiled behavior diverged from CPython for "
            f"{case.name}: expected {expected!r}, got {preprocessed_outcome!r}"
        )
