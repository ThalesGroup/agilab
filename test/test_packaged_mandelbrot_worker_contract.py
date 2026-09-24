"""Reject malformed worker evidence before accepting free-threading results."""
import copy
import importlib
import importlib.util
from pathlib import Path
import sys

import pytest


@pytest.fixture
def worker_evidence(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources/free_threading_demo"
    pool = importlib.import_module("agilab.demos.resources.free_threading_demo.agilab_pool")
    monkeypatch.setitem(sys.modules, "agilab_pool", pool)
    spec = importlib.util.spec_from_file_location("_mandelbrot_worker_contract", root / "free_threading_core.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    runtime = {"free_threaded_build": True, "gil_enabled": True, "version": "synthetic"}
    tile = {"tile_id": 0, "row_start": 0, "row_stop": 2}
    record = dict(tile, counts=[1, 2, 1, 2], pid=100, thread_id=200, start=10.0, end=11.0,
                  runtime_before=copy.deepcopy(runtime), runtime_after=copy.deepcopy(runtime),
                  gil_before=True, gil_after=True)
    arguments = dict(records=[record], tiles=[tile], width=2, height=2, iterations=2,
                     mode="gil_on_threads", info_before=runtime, engine_seconds=1.0,
                     engine_start=10.0, engine_end=12.0)
    return core, arguments


def test_corner_worker_evidence_passes_independent_contract(worker_evidence):
    core, arguments = worker_evidence
    core._validate_records(**arguments)
    assert core.reference_image(2, 2, 2) == [1, 2, 1, 2]


@pytest.mark.parametrize("field,value", [
    ("tile_id", 1), ("row_start", -1), ("row_stop", 3), ("row_stop", 1),
    ("counts", []), ("counts", [True, 2, 1, 2]), ("counts", [-1, 2, 1, 2]),
    ("counts", [3, 2, 1, 2]), ("counts", [1.0, 2, 1, 2]),
    ("gil_before", False), ("gil_after", False),
    ("runtime_before", {}), ("runtime_after", {}),
    ("pid", True), ("pid", 0), ("pid", 1.5),
    ("thread_id", False), ("thread_id", -1), ("thread_id", "2"),
    ("start", float("nan")), ("end", float("inf")),
    ("start", 11.0), ("start", 9.0), ("end", 13.0),
])
def test_corrupt_worker_record_cannot_be_accepted(worker_evidence, field, value):
    core, arguments = worker_evidence
    arguments["records"][0][field] = value
    with pytest.raises(RuntimeError):
        core._validate_records(**arguments)


@pytest.mark.parametrize("field,value", [
    ("records", []), ("engine_seconds", 0), ("engine_seconds", float("nan")),
    ("engine_seconds", float("inf")), ("engine_start", float("nan")),
    ("engine_end", float("inf")), ("engine_end", 10.0), ("engine_end", 9.0),
    ("height", 3),
])
def test_invalid_engine_bracket_or_missing_image_rows_are_rejected(worker_evidence, field, value):
    core, arguments = worker_evidence
    arguments[field] = value
    with pytest.raises(RuntimeError):
        core._validate_records(**arguments)


def test_duplicate_worker_tile_cannot_cover_a_missing_tile(worker_evidence):
    core, arguments = worker_evidence
    arguments["records"] *= 2
    with pytest.raises(RuntimeError, match="Duplicate"):
        core._validate_records(**arguments)


@pytest.mark.parametrize("mode", ["gil_on_threads", "gil_on_processes", "gil_off_threads"])
@pytest.mark.parametrize("free_threaded", [False, True])
@pytest.mark.parametrize("gil", [False, True])
def test_runtime_evidence_must_match_requested_execution_mode(worker_evidence, mode, free_threaded, gil):
    core, _ = worker_evidence
    info = {"free_threaded_build": free_threaded, "gil_enabled": gil}
    valid = free_threaded and (gil is (mode != "gil_off_threads"))
    if valid:
        core._check_runtime(mode, info)
    else:
        with pytest.raises(RuntimeError):
            core._check_runtime(mode, info)


@pytest.mark.parametrize("field,value", [
    ("width", True), ("width", 1), ("height", 257), ("height", 2.5),
    ("iterations", 0), ("iterations", 301), ("workers", 0), ("workers", 9), ("mode", "unknown"),
])
def test_invalid_case_does_not_probe_or_launch_runtime(worker_evidence, monkeypatch, field, value):
    core, _ = worker_evidence
    def forbidden():
        pytest.fail("invalid case must be rejected before runtime inspection")
    monkeypatch.setattr(core, "runtime_info", forbidden)
    params = dict(width=2, height=2, iterations=2, workers=1, mode="gil_on_threads")
    params[field] = value
    with pytest.raises((ValueError, TypeError)):
        core.run_case(**params)
