"""Exercise packaged benchmark subprocess boundaries with synthetic child replies."""

import copy
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def benchmark(monkeypatch):
    root = (
        Path(__file__).resolve().parents[1]
        / "src/agilab/demos/resources/free_threading_demo_rtx"
    )
    pool = importlib.import_module(
        "agilab.demos.resources.free_threading_demo_rtx.agilab_pool"
    )
    monkeypatch.setitem(sys.modules, "agilab_pool", pool)
    modules = []
    for name, filename in (
        ("free_threading_core", "free_threading_core.py"),
        ("_rtx_benchmark_contract", "benchmark.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, root / filename)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    core, runner = modules
    monkeypatch.setattr(
        core,
        "child_argv",
        lambda *args: ["synthetic-python", "-m", "free_threading_core"],
    )
    monkeypatch.setattr(core, "child_env", lambda mode: {"CONTRACT_TEST": mode})
    process = Mock(returncode=0)
    popen = Mock(return_value=process)
    terminate = Mock()
    monkeypatch.setattr(
        runner, "subprocess", SimpleNamespace(**{**vars(subprocess), "Popen": popen})
    )
    monkeypatch.setattr(runner, "_terminate_process_group", terminate)

    def run():
        return runner._run_one_case(
            "synthetic-python",
            {"width": 2, "height": 2},
            core.MODE_GIL_ON_THREADS,
            2,
            1,
            3.0,
            str(root),
        )

    return SimpleNamespace(
        run=run,
        process=process,
        popen=popen,
        terminate=terminate,
        runner=runner,
        root=root,
    )


@pytest.fixture
def child_payload():
    tile = {
        "row_start": 0,
        "row_end": 2,
        "rows": 2,
        "start": 10.0,
        "end": 12.0,
        "pid": 11,
        "thread": 22,
        "runtime_before": {"gil_enabled": True},
        "runtime_after": {"gil_enabled": True},
        "counts": [1, 2, 3, 4],
    }
    repeat = {
        "repeat": 0,
        "engine_seconds": 2.0,
        "engine_wall_seconds": 3.0,
        "engine_start": 10.0,
        "engine_end": 13.0,
        "engine_width": 2,
        "engine_backend": "thread",
        "tiles": [tile],
        "digest": "synthetic-digest",
    }
    return {
        "ok": True,
        "repeats": [repeat],
        "gil_before": True,
        "gil_after": True,
        "same_as_serial_reference": True,
    }


def test_timeout_terminates_only_owned_child(benchmark):
    benchmark.process.communicate.side_effect = subprocess.TimeoutExpired(
        "synthetic", 3
    )
    result = benchmark.run()
    assert result["status"] == "timeout"
    benchmark.process.communicate.assert_called_once_with(timeout=3.0)
    benchmark.terminate.assert_called_once_with(benchmark.process)


@pytest.mark.parametrize(
    "stdout,code,reason",
    [
        ("", 0, "no valid JSON"),
        ("not json", 0, "no valid JSON"),
        ('{"ok": false}', 0, "child reported failure"),
        ('{"ok": false, "error": "bad workload"}', 0, "bad workload"),
        ("", 7, "child exited 7"),
    ],
)
def test_child_failures_remain_explicit(benchmark, stdout, code, reason):
    benchmark.process.returncode = code
    benchmark.process.communicate.return_value = stdout, "diagnostic"
    result = benchmark.run()
    assert result["status"] == "error" and reason in result["error"]
    assert benchmark.terminate.call_count == int(code != 0)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("engine_seconds", 0, "non-positive measured time"),
        ("engine_wall_seconds", -1, "non-positive measured time"),
        ("tiles", [], "no tile records"),
        ("engine_end", 10.0, "non-positive measured interval"),
    ],
)
def test_invalid_measurements_are_rejected(
    benchmark, child_payload, field, value, reason
):
    child_payload["repeats"][0][field] = value
    benchmark.process.communicate.return_value = json.dumps(child_payload), ""
    with pytest.raises(ValueError, match=reason):
        benchmark.run()


def test_repeated_work_must_have_matching_digest(benchmark, child_payload):
    second = copy.deepcopy(child_payload["repeats"][0])
    second["digest"] = "different"
    child_payload["repeats"].append(second)
    benchmark.process.communicate.return_value = json.dumps(child_payload), ""
    with pytest.raises(ValueError, match="digest mismatch"):
        benchmark.run()


@pytest.mark.parametrize("wall_seconds", [None, 4.5])
def test_child_intervals_and_work_are_preserved(benchmark, child_payload, wall_seconds):
    if wall_seconds is not None:
        child_payload["repeats"][0]["wall_seconds"] = wall_seconds
    benchmark.process.communicate.return_value = (
        "startup log\n" + json.dumps(child_payload),
        "",
    )
    result = benchmark.run()
    assert result["status"] == "ok"
    assert result["throughput_pixels_per_s"] == 2
    assert result["median_wall_seconds"] == (
        3 if wall_seconds is None else wall_seconds
    )
    repeat = result["repeats"][0]
    assert (repeat["engine_start"], repeat["engine_end"]) == (10, 13)
    assert repeat["actual_workers"] == 1
    assert repeat["records"][0]["counts"] == [1, 2, 3, 4]
    assert repeat["records"][0]["duration_seconds"] == 2
    assert repeat["records"][0]["runtime_after"] == {"gil_enabled": True}
    assert benchmark.popen.call_args.kwargs["cwd"] == str(benchmark.root)
    assert benchmark.popen.call_args.kwargs["start_new_session"] is True
    benchmark.terminate.assert_not_called()


@pytest.fixture
def matrix_runner(benchmark, monkeypatch, tmp_path, child_payload):
    runner = benchmark.runner
    monkeypatch.setattr(
        runner.core,
        "resolve_free_threading_python",
        lambda: (
            "synthetic-python",
            {
                "version": "synthetic-test-runtime",
                "free_threaded_build": True,
                "py_gil_disabled_build": True,
            },
        ),
    )
    monkeypatch.setattr(runner.core, "effective_cpu_allowance", lambda: 2)
    monkeypatch.setattr(runner, "_probe_interpreter_startup", lambda python: 0.125)
    benchmark.process.communicate.return_value = json.dumps(child_payload), ""
    return lambda **kwargs: runner.run_benchmark(
        width=2,
        height=2,
        iterations=2,
        workers=kwargs.pop("workers", 2),
        repeats=1,
        tile_rows=2,
        root=str(tmp_path),
        **kwargs,
    )


@pytest.mark.parametrize("workers", [1, 2])
def test_matrix_preserves_six_slots_and_exports_stable_projection(
    benchmark, matrix_runner, tmp_path, workers
):
    artifact = tmp_path / "synthetic-benchmark-evidence.json"
    progress = []
    payload = matrix_runner(
        workers=workers,
        out_path=str(artifact),
        progress_cb=lambda *args: progress.append(args),
    )
    results = payload["results"]
    assert len(results["cases"]) == len(results["runs"]) == len(results["summary"]) == 6
    assert {(run["mode"], run["role"]) for run in results["runs"]} == {
        (mode, role)
        for mode in benchmark.runner.MODE_KEYS.values()
        for role in ("baseline", "wide")
    }
    assert [item[:2] for item in progress] == [(n, 6) for n in range(1, 7)]
    assert all(row["speedup"] == 1 for row in results["summary"])
    assert all(row["wall_seconds"] == 3 for row in results["summary"])
    evidence = json.loads(artifact.read_text())["results"]
    assert evidence["digest"] == "synthetic-digest"
    assert "generated_at" not in evidence
    assert "executable" not in evidence["interpreter"]
    assert "pid" not in evidence["runs"][0]["records"][0]
    assert "start" not in evidence["runs"][0]["records"][0]
    assert evidence["runs"][0]["records"][0]["counts"] == [1, 2, 3, 4]
    before = copy.deepcopy(results)
    noisy = copy.deepcopy(results)
    noisy["generated_at"] = "another-run"
    noisy["interpreter"]["executable"] = "/another/python"
    noisy["runs"][0]["records"][0].update(pid=999, thread_id=888, start=100, end=200)
    assert benchmark.runner.deterministic_evidence(noisy) == evidence
    assert results == before
    # The lock is released after completion and a second run is admitted.
    matrix_runner(workers=workers)


def test_matrix_refuses_oversubscription_before_spawning(
    benchmark, matrix_runner, monkeypatch
):
    monkeypatch.setattr(benchmark.runner.core, "effective_cpu_allowance", lambda: 1)
    with pytest.raises(ValueError, match="effective CPU allowance"):
        matrix_runner()
    benchmark.popen.assert_not_called()


def test_matrix_refuses_concurrent_owner(benchmark, matrix_runner, tmp_path):
    handle = benchmark.runner._acquire_lock(str(tmp_path))
    try:
        with pytest.raises(RuntimeError, match="already in progress"):
            matrix_runner()
        benchmark.popen.assert_not_called()
    finally:
        benchmark.runner._release_lock(handle)


def test_matrix_reports_failure_and_releases_lock(benchmark, matrix_runner, tmp_path):
    benchmark.process.communicate.return_value = (
        '{"ok": false, "error": "synthetic failure"}',
        "",
    )
    with pytest.raises(RuntimeError, match="benchmark incomplete.*synthetic failure"):
        matrix_runner()
    handle = benchmark.runner._acquire_lock(str(tmp_path))
    assert handle is not None
    benchmark.runner._release_lock(handle)


def test_matrix_rejects_different_work_across_modes(
    benchmark, matrix_runner, child_payload
):
    replies = []
    for index in range(6):
        payload = copy.deepcopy(child_payload)
        payload["repeats"][0]["digest"] = str(index)
        replies.append((json.dumps(payload), ""))
    benchmark.process.communicate.side_effect = replies
    with pytest.raises(RuntimeError, match="digest mismatch across modes"):
        matrix_runner()


def test_matrix_marks_unstarted_slots_when_budget_expires(
    benchmark, matrix_runner, monkeypatch
):
    ticks = iter([0, 0, 0, 0, 100, 100, 100, 100, 100])
    monkeypatch.setattr(benchmark.runner.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="budget.*exhausted"):
        matrix_runner(total_timeout=1)
    assert benchmark.popen.call_count == 1
