from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import benchmark_execution_mode_matrix as matrix
from tools import benchmark_execution_pandas_cython_kernel as cython_kernel
from tools import benchmark_execution_playground as playground
from tools import cython_worker_verify as verify_tool


def test_benchmark_playground_apps_path_is_absolute() -> None:
    expected = (
        Path(__file__).resolve().parents[1] / "src/agilab/apps/builtin"
    ).resolve()
    assert playground.APPS_PATH == expected
    assert playground.APPS_PATH.is_absolute()


def test_cython_kernel_benchmark_uses_execution_pandas_worker_source() -> None:
    assert cython_kernel.WORKER_SOURCE.is_file()
    assert cython_kernel.WORKER_SOURCE.name == "execution_pandas_worker.py"
    assert cython_kernel.KERNEL_NAME == "_typed_numeric_score_kernel"


def test_cython_kernel_benchmark_csv_rows_report_speedup() -> None:
    results = {
        "environment": {"rows": 100},
        "runtimes": {
            "python": {
                "median_seconds": 2.0,
                "min_seconds": 2.0,
                "max_seconds": 2.0,
                "checksum": 1.0,
            },
            "cython": {
                "median_seconds": 0.5,
                "min_seconds": 0.5,
                "max_seconds": 0.5,
                "checksum": 1.0,
            },
        },
        "speedup_vs_python": 4.0,
    }

    rows = cython_kernel._rows_for_csv(results)

    assert rows[0]["runtime"] == "python"
    assert rows[0]["speedup_vs_python"] == "1.00"
    assert rows[1]["runtime"] == "cython"
    assert rows[1]["speedup_vs_python"] == "4.00"
    assert rows[1]["rows_per_second"] == "200"


def test_committed_benchmark_csv_matches_json_via_tool_helpers(tmp_path) -> None:
    """The committed CSV must be reproducible from the committed JSON.

    This is a fast, no-compile consistency guard: it loads the checked-in
    benchmark JSON, feeds it back through the tool's own ``_rows_for_csv`` and
    ``_write_csv`` helpers, and asserts the regenerated CSV equals the committed
    CSV. Row order is compared keyed by runtime because the committed JSON sorts
    its ``runtimes`` keys, which is independent of the CSV row layout.
    """

    import csv as _csv

    data_dir = REPO_ROOT / "docs" / "source" / "data"
    json_path = data_dir / "execution_pandas_typed_kernel_benchmark.json"
    csv_path = data_dir / "execution_pandas_typed_kernel_benchmark.csv"

    results = json.loads(json_path.read_text(encoding="utf-8"))

    regenerated = tmp_path / "regenerated.csv"
    cython_kernel._write_csv(regenerated, results)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        committed_reader = _csv.DictReader(fh)
        committed_fieldnames = committed_reader.fieldnames
        committed_rows = {row["runtime"]: dict(row) for row in committed_reader}
    with regenerated.open(newline="", encoding="utf-8") as fh:
        regen_reader = _csv.DictReader(fh)
        regen_fieldnames = regen_reader.fieldnames
        regen_rows = {row["runtime"]: dict(row) for row in regen_reader}

    assert regen_fieldnames == committed_fieldnames
    assert regen_rows == committed_rows

    # Also assert the derived helper rows agree with the committed CSV values so
    # a drift between the committed JSON and CSV would fail here before release.
    helper_rows = {row["runtime"]: row for row in cython_kernel._rows_for_csv(results)}
    assert set(helper_rows) == set(committed_rows)
    for runtime, committed in committed_rows.items():
        for field in committed_fieldnames:
            assert helper_rows[runtime][field] == committed[field]


def test_cython_kernel_benchmark_writes_lf_csv(tmp_path) -> None:
    results = {
        "environment": {"rows": 100},
        "runtimes": {
            "python": {
                "median_seconds": 2.0,
                "min_seconds": 2.0,
                "max_seconds": 2.0,
                "checksum": 1.0,
            },
            "cython": {
                "median_seconds": 0.5,
                "min_seconds": 0.5,
                "max_seconds": 0.5,
                "checksum": 1.0,
            },
        },
        "speedup_vs_python": 4.0,
    }
    csv_path = tmp_path / "benchmark.csv"

    cython_kernel._write_csv(csv_path, results)

    data = csv_path.read_bytes()
    assert b"\r\n" not in data
    assert b"\n" in data


def test_cython_kernel_compare_preprocess_csv_reports_counts(tmp_path) -> None:
    results = {
        "environment": {"rows": 100, "compare_preprocess": True},
        "preprocess": {"typed_count": 3, "skipped_count": 2},
        "runtimes": {
            "cython_raw": {
                "median_seconds": 1.0,
                "min_seconds": 1.0,
                "max_seconds": 1.0,
                "checksum": 1.0,
            },
            "cython_preprocessed": {
                "median_seconds": 0.8,
                "min_seconds": 0.8,
                "max_seconds": 0.8,
                "checksum": 1.0,
            },
        },
        "speedup_preprocessed_vs_raw": 1.25,
    }
    csv_path = tmp_path / "compare.csv"

    rows = cython_kernel._rows_for_preprocess_csv(results)
    cython_kernel._write_csv(csv_path, results)

    assert rows[0]["runtime"] == "cython_raw"
    assert rows[0]["speedup_preprocessed_vs_raw"] == "1.00"
    assert rows[1]["runtime"] == "cython_preprocessed"
    assert rows[1]["speedup_preprocessed_vs_raw"] == "1.25"
    assert rows[1]["typed_count"] == "3"
    assert rows[1]["skipped_count"] == "2"
    assert "speedup_preprocessed_vs_raw" in csv_path.read_text(encoding="utf-8")


def test_cython_kernel_build_compiled_worker_delegates_to_generic_machinery(
    tmp_path, monkeypatch
) -> None:
    sentinel = object()
    calls: dict[str, tuple] = {}

    def _fake_compile(build_root, module_name, source_text, *, compiler_directives=None):
        calls["args"] = (Path(build_root), module_name, source_text, compiler_directives)
        return sentinel

    monkeypatch.setattr(verify_tool, "compile_python_module", _fake_compile)

    result = cython_kernel._build_compiled_worker(
        tmp_path,
        module_name="demo_mod",
        source_text="def f():\n    pass\n",
    )

    assert result is sentinel
    assert calls["args"] == (tmp_path, "demo_mod", "def f():\n    pass\n", None)


def test_cython_kernel_measure_reports_checksum_via_generic_timer() -> None:
    module = types.SimpleNamespace(**{cython_kernel.KERNEL_NAME: lambda *args: 7.5})
    arrays = tuple(np.zeros(3) for _ in range(4))

    result = cython_kernel._measure(module, arrays, compute_passes=1, repeats=2, warmups=0)

    assert result["checksum"] == 7.5
    assert len(result["samples_seconds"]) == 2
    assert {"median_seconds", "min_seconds", "max_seconds"} <= set(result)


def test_cython_worker_verify_parse_entry_variants() -> None:
    spec = verify_tool.parse_entry("demo_worker:run")
    assert (spec.module, spec.function, spec.args, spec.kwargs) == (
        "demo_worker",
        "run",
        (),
        {},
    )

    spec = verify_tool.parse_entry("demo_worker:run:[1, 2.5]")
    assert spec.args == (1, 2.5)
    assert spec.kwargs == {}

    spec = verify_tool.parse_entry('demo_worker:run:{"rows": 3, "label": "x:y"}')
    assert spec.args == ()
    assert spec.kwargs == {"rows": 3, "label": "x:y"}

    spec = verify_tool.parse_entry("demo_worker:run:7")
    assert spec.args == (7,)

    with pytest.raises(ValueError):
        verify_tool.parse_entry("missing_separator")
    with pytest.raises(ValueError):
        verify_tool.parse_entry("demo_worker:")


class _ElementwiseEq:
    """Numpy-style stub whose == returns a non-bool elementwise result."""

    def __init__(self, values):
        self.values = list(values)

    def __eq__(self, other):  # noqa: D105 - intentionally elementwise
        return [mine == theirs for mine, theirs in zip(self.values, other.values)]

    def __repr__(self) -> str:
        return f"_ElementwiseEq({self.values!r})"


def test_cython_worker_verify_deep_equal_semantics() -> None:
    assert verify_tool.deep_equal(1.0, 1.0 + 1e-12)
    assert not verify_tool.deep_equal(1.0, 1.1)
    assert verify_tool.deep_equal(float("nan"), float("nan"))
    assert verify_tool.deep_equal(True, True)
    assert not verify_tool.deep_equal(True, False)
    assert verify_tool.deep_equal(
        {"a": [1.0, (2.0, 3)], "b": "x"},
        {"a": [1.0 + 1e-13, (2.0, 3)], "b": "x"},
    )
    assert not verify_tool.deep_equal([1.0], (1.0,))
    assert not verify_tool.deep_equal([1.0, 2.0], [1.0])
    assert not verify_tool.deep_equal(1.0, "1.0")

    # Overloaded == that does not return bool falls back to repr comparison.
    assert verify_tool.deep_equal(
        _ElementwiseEq([1.0, 2.0]),
        _ElementwiseEq([1.0, 2.0]),
    )
    assert not verify_tool.deep_equal(
        _ElementwiseEq([1.0, 2.0]),
        _ElementwiseEq([1.0, 9.0]),
    )


def test_cython_worker_verify_outcomes_equivalence() -> None:
    value = {"kind": "value", "value": 5.0}
    assert verify_tool.outcomes_equivalent(value, {"kind": "value", "value": 5.0 + 1e-13})
    assert not verify_tool.outcomes_equivalent(value, {"kind": "value", "value": 6.0})
    assert not verify_tool.outcomes_equivalent(
        value,
        {"kind": "exception", "type": "ValueError", "detail": "boom"},
    )
    assert verify_tool.outcomes_equivalent(
        {"kind": "exception", "type": "ValueError", "detail": "a"},
        {"kind": "exception", "type": "ValueError", "detail": "b"},
    )
    assert not verify_tool.outcomes_equivalent(
        {"kind": "exception", "type": "ValueError", "detail": "a"},
        {"kind": "exception", "type": "TypeError", "detail": "a"},
    )
    assert verify_tool.outcomes_equivalent(
        {"kind": "import-only"},
        {"kind": "import-only"},
    )


def _make_fake_project(tmp_path: Path, *, name: str = "demo_project") -> Path:
    project = tmp_path / name
    worker_dir = project / "src" / "demo_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "demo_worker.py").write_text(
        "def add(a, b):\n"
        "    total = 0.0\n"
        "    for _ in range(50):\n"
        "        total = total + 1.0\n"
        "    return a + b + total - total\n",
        encoding="utf-8",
    )
    return project


def test_cython_worker_verify_locate_worker_source_uses_convention(tmp_path) -> None:
    project = _make_fake_project(tmp_path)

    worker = verify_tool.locate_worker_source(project)

    assert worker == project / "src" / "demo_worker" / "demo_worker.py"

    empty = tmp_path / "empty_project"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        verify_tool.locate_worker_source(empty)
    with pytest.raises(FileNotFoundError):
        verify_tool.locate_worker_source(tmp_path / "missing_project")


def test_cython_worker_verify_run_verification_report_shape(tmp_path, monkeypatch) -> None:
    project = _make_fake_project(tmp_path)

    def _fake_compile(build_root, module_name, source_text, *, compiler_directives=None):
        return verify_tool.load_python_module(
            module_name,
            source_text,
            filename=f"<{module_name}>",
        )

    monkeypatch.setattr(verify_tool, "compile_python_module", _fake_compile)
    monkeypatch.setattr(verify_tool, "strip_worker_decorators", lambda source: source)
    monkeypatch.setattr(
        verify_tool,
        "preprocess_worker_source",
        lambda source, *, filename: (source, {"declarations": [], "skipped": []}),
    )
    directive_project_dirs: list[object] = []

    def _fake_directives(project_dir=None):
        directive_project_dirs.append(project_dir)
        return {}

    monkeypatch.setattr(verify_tool, "resolve_compiler_directives", _fake_directives)

    results = verify_tool.run_verification(
        project=project,
        entry="demo_worker:add:[2, 3]",
        mode=verify_tool.MODE_BOTH,
        repeats=2,
        warmups=0,
    )

    # Directives must resolve against the verified project (its pyproject
    # [tool.agilab.cython] table), matching the real build's --app-path chdir.
    assert directive_project_dirs == [project.resolve()]
    assert results["equivalent"] is True
    assert set(results["variants"]) == {
        verify_tool.VARIANT_PYTHON,
        verify_tool.VARIANT_RAW,
        verify_tool.VARIANT_PREPROCESSED,
    }
    assert results["preprocess"] == {
        "typed_count": 0,
        "skipped_count": 0,
        "report": {"declarations": [], "skipped": []},
    }
    for name, variant in results["variants"].items():
        assert variant["outcome"] == {"kind": "value", "value_repr": "5.0"}
        assert len(variant["samples_seconds"]) == 2
        assert variant["min_seconds"] <= variant["median_seconds"] <= variant["max_seconds"]
        if name != verify_tool.VARIANT_PYTHON:
            assert variant["equivalent_to_python"] is True
            assert variant["speedup_vs_python"] > 0
    assert results["speedup_preprocessed_vs_raw"] > 0
    # The full report must be JSON-serializable for --json-out.
    json.dumps(results)

    rows = verify_tool.rows_for_csv(results)
    assert [row["runtime"] for row in rows] == list(results["variants"])
    for row in rows:
        assert set(row) == set(verify_tool.CSV_FIELDNAMES)

    csv_path = tmp_path / "verify.csv"
    verify_tool.write_csv(csv_path, results)
    data = csv_path.read_bytes()
    assert b"\r\n" not in data
    assert data.decode("utf-8").splitlines()[0] == ",".join(verify_tool.CSV_FIELDNAMES)


def test_cython_worker_verify_import_only_smoke_has_no_timings(tmp_path, monkeypatch) -> None:
    project = _make_fake_project(tmp_path)

    monkeypatch.setattr(
        verify_tool,
        "compile_python_module",
        lambda build_root, module_name, source_text, *, compiler_directives=None: (
            verify_tool.load_python_module(
                module_name, source_text, filename=f"<{module_name}>"
            )
        ),
    )
    monkeypatch.setattr(verify_tool, "strip_worker_decorators", lambda source: source)
    monkeypatch.setattr(
        verify_tool, "resolve_compiler_directives", lambda project_dir=None: {}
    )

    results = verify_tool.run_verification(
        project=project,
        entry=None,
        mode=verify_tool.MODE_RAW,
        repeats=2,
        warmups=0,
    )

    assert results["equivalent"] is True
    assert set(results["variants"]) == {
        verify_tool.VARIANT_PYTHON,
        verify_tool.VARIANT_RAW,
    }
    assert results["preprocess"] is None
    for variant in results["variants"].values():
        assert variant["workload"] == "import-only"
        assert "median_seconds" not in variant


def test_cython_worker_verify_main_exits_nonzero_on_inequivalence(
    tmp_path, monkeypatch, capsys
) -> None:
    inequivalent = {"equivalent": False, "variants": {}}
    monkeypatch.setattr(
        verify_tool, "run_verification", lambda **kwargs: inequivalent
    )
    assert verify_tool.main(["--project", str(tmp_path)]) == 1

    equivalent = {"equivalent": True, "variants": {}}
    monkeypatch.setattr(verify_tool, "run_verification", lambda **kwargs: equivalent)
    json_out = tmp_path / "out" / "report.json"
    assert verify_tool.main(["--project", str(tmp_path), "--json-out", str(json_out)]) == 0
    assert json.loads(json_out.read_text(encoding="utf-8")) == equivalent
    capsys.readouterr()


def test_cython_worker_verify_parser_defaults() -> None:
    parser = verify_tool._build_parser()
    args = parser.parse_args(["--project", "some/project"])

    assert args.project == Path("some/project")
    assert args.entry is None
    assert args.mode == verify_tool.MODE_BOTH
    assert args.repeats == verify_tool.DEFAULT_REPEATS
    assert args.warmups == verify_tool.DEFAULT_WARMUPS
    assert args.json_out is None
    assert args.csv_out is None


def test_cython_worker_verify_rejects_unknown_mode(tmp_path) -> None:
    with pytest.raises(ValueError):
        verify_tool.run_verification(project=tmp_path, mode="sideways")


def test_ssh_target_defaults_to_agi_and_preserves_explicit_user() -> None:
    assert matrix._ssh_target("192.168.20.130") == "agi@192.168.20.130"
    assert matrix._ssh_target("bench@192.168.20.130") == "bench@192.168.20.130"


def test_mode_matrix_declares_macos_ssh_topology() -> None:
    assert matrix.TOPOLOGY_ID == "macos-ssh-2node"
    assert "macOS" in matrix.TOPOLOGY_DESCRIPTION
    assert "SSH" in matrix.TOPOLOGY_DESCRIPTION


def test_mode_matrix_rejects_non_macos_scheduler(monkeypatch) -> None:
    monkeypatch.setattr(matrix.platform, "system", lambda: "Linux")

    with pytest.raises(RuntimeError, match="macOS SSH 2-node benchmark"):
        matrix._require_macos_ssh_topology()


def test_sync_dataset_to_remote_reuses_consistent_ssh_target(
    tmp_path, monkeypatch
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, check=False, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(matrix.subprocess, "run", _fake_run)

    data_in = tmp_path / "dataset"
    data_in.mkdir()
    matrix._sync_dataset_to_remote(data_in, "192.168.20.130")

    assert calls == [
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "agi@192.168.20.130",
            f"mkdir -p {data_in.parent}",
        ],
        [
            "rsync",
            "-az",
            "--delete",
            f"{data_in}/",
            f"agi@192.168.20.130:{data_in}/",
        ],
    ]


def test_gpu_accelerated_respects_local_and_cluster_topologies() -> None:
    local_gpu = matrix.NodeInfo("local", "l", "macOS", True)
    local_cpu = matrix.NodeInfo("local", "l", "macOS", False)
    remote_gpu = matrix.NodeInfo("remote", "r", "macOS", True)
    remote_cpu = matrix.NodeInfo("remote", "r", "macOS", False)

    assert matrix._gpu_accelerated(8, local_gpu, remote_cpu) is True
    assert matrix._gpu_accelerated(8, local_cpu, remote_gpu) is False
    assert matrix._gpu_accelerated(12, local_gpu, remote_cpu) is True
    assert matrix._gpu_accelerated(12, local_cpu, remote_gpu) is True
    assert matrix._gpu_accelerated(12, local_cpu, remote_cpu) is False
