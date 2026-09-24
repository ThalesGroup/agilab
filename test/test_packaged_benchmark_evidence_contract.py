"""Reject altered benchmark evidence without requiring a free-threaded runtime."""

import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def evidence():
    path = (
        Path(__file__).resolve().parents[1]
        / "src/agilab/demos/resources/free_threading_demo/benchmark.py"
    )
    spec = importlib.util.spec_from_file_location("_packaged_benchmark_evidence", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    params = {
        "width": 2,
        "height": 2,
        "iterations": 2,
        "workers": 1,
        "mode": "gil_on_threads",
    }
    runtime = {
        "free_threaded_build": True,
        "gil_enabled": True,
        "version": "synthetic-runtime",
    }
    tile = {"tile_id": 0, "row_start": 0, "row_stop": 2}
    # Four corner points: (-2,+/-1.2) escape after one step; (1,+/-1.2) after two.
    counts = [1, 2, 1, 2]
    digest = hashlib.sha256(b"001002001002").hexdigest()
    record = dict(
        tile,
        counts=counts,
        pid=100,
        thread_id=200,
        start=10.0,
        end=11.0,
        runtime_before=copy.deepcopy(runtime),
        runtime_after=copy.deepcopy(runtime),
        gil_before=True,
        gil_after=True,
    )
    result = dict(
        params,
        before=copy.deepcopy(runtime),
        after=copy.deepcopy(runtime),
        records=[record],
        engine_start=10.0,
        engine_end=12.0,
        engine_seconds=1.0,
        actual_workers=1,
        pool_width=1,
        digest=digest,
        backend="thread (forced by env)",
    )
    kwargs = dict(
        expected_params=params,
        expected_mode="gil_on_threads",
        expected_interpreter_version="synthetic-runtime",
        expected_free_threaded=True,
        expected_gil=True,
        expected_tiles=[tile],
        expected_width=2,
        expected_height=2,
        expected_iterations=2,
        wall_seconds=3.0,
    )
    return runner, result, kwargs


def test_valid_corner_calculation_is_independently_verified(evidence):
    runner, result, kwargs = evidence
    runner._validate_child_result(result, **kwargs)
    assert (
        runner._compute_reference_digest(2, 2, 2)
        == hashlib.sha256(b"001002001002").hexdigest()
    )


@pytest.mark.parametrize(
    "path,value,reason",
    [
        (("width",), 3, "param mismatch"),
        (("height",), 3, "param mismatch"),
        (("iterations",), 3, "param mismatch"),
        (("workers",), 2, "param mismatch"),
        (("mode",), "wrong", "param mismatch"),
        (("before", "free_threaded_build"), False, "free_threaded_build"),
        (("after", "free_threaded_build"), False, "free_threaded_build"),
        (("before", "gil_enabled"), False, "GIL state"),
        (("after", "gil_enabled"), False, "GIL state"),
        (("before", "version"), "other", "Interpreter version"),
        (("records",), [], "no records"),
        (("records",), {}, "no records"),
        (("records", 0, "tile_id"), 1, "Tile mismatch"),
        (("records", 0, "row_start"), "0", "Invalid row bounds"),
        (("records", 0, "row_start"), -1, "Invalid row range"),
        (("records", 0, "row_stop"), 3, "Invalid row range"),
        (("records", 0, "row_stop"), 1, "row bounds"),
        (("records", 0, "counts"), [1], "counts length"),
        (("records", 0, "counts"), [True, 2, 1, 2], "invalid count"),
        (("records", 0, "counts"), [-1, 2, 1, 2], "invalid count"),
        (("records", 0, "counts"), [3, 2, 1, 2], "invalid count"),
        (("records", 0, "pid"), 0, "invalid pid"),
        (("records", 0, "pid"), True, "invalid pid"),
        (("records", 0, "thread_id"), False, "invalid thread_id"),
        (("records", 0, "thread_id"), -1, "invalid thread_id"),
        (("engine_start",), "10", "not numeric"),
        (("engine_end",), float("inf"), "not finite"),
        (("engine_end",), 10, "engine_end <="),
        (("records", 0, "start"), "10", "non-numeric"),
        (("records", 0, "end"), float("nan"), "non-finite"),
        (("records", 0, "end"), 10, "non-positive duration"),
        (("records", 0, "start"), 9, "outside engine bracket"),
        (("engine_seconds",), True, "not numeric"),
        (("engine_seconds",), 0, "not finite/positive"),
        (("engine_seconds",), float("inf"), "not finite/positive"),
        (("engine_seconds",), 4, "> wall_seconds"),
        (("engine_seconds",), 2.5, "> engine_end-engine_start"),
        (("actual_workers",), True, "actual_workers invalid"),
        (("actual_workers",), 0, "actual_workers invalid"),
        (("pool_width",), True, "pool_width invalid"),
        (("pool_width",), 0, "pool_width invalid"),
        (("digest",), "", "digest invalid"),
        (("digest",), "f" * 64, "Digest mismatch"),
        (("after", "version"), "other", "before/after dicts differ"),
        (("records", 0, "runtime_before"), {}, "runtime_before/after mismatch"),
        (("records", 0, "runtime_after"), {}, "runtime_before/after mismatch"),
        (("records", 0, "gil_before"), False, "gil_before"),
        (("records", 0, "gil_after"), False, "gil_after"),
        (("backend",), "process", "backend mismatch"),
        (("actual_workers",), 2, "distinct"),
        (("pool_width",), 2, "expected_workers"),
    ],
)
def test_corrupted_child_evidence_is_rejected(evidence, path, value, reason):
    runner, result, kwargs = evidence
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(RuntimeError, match=reason):
        runner._validate_child_result(result, **kwargs)


def test_duplicate_tiles_are_rejected(evidence):
    runner, result, kwargs = evidence
    result["records"].append(copy.deepcopy(result["records"][0]))
    with pytest.raises(RuntimeError, match="Duplicate tile_ids"):
        runner._validate_child_result(result, **kwargs)


def test_self_consistent_digest_cannot_hide_incorrect_computation(evidence):
    runner, result, kwargs = evidence
    result["records"][0]["counts"] = [2, 2, 2, 2]
    result["digest"] = hashlib.sha256(b"002002002002").hexdigest()
    with pytest.raises(RuntimeError, match="Digest mismatch vs reference"):
        runner._validate_child_result(result, **kwargs)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nested_nonfinite_results_are_rejected(evidence, value):
    runner, _, _ = evidence
    with pytest.raises((RuntimeError, ValueError)):
        runner._reject_nonfinite({"runs": [{"measurement": value}]})


def test_finite_nested_results_are_accepted(evidence):
    runner, _, _ = evidence
    runner._reject_nonfinite({"runs": [{"measurement": 1.5, "status": "ok"}]})
