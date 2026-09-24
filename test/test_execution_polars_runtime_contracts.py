"""Polars workload runtime state and scalar fallback contracts."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

ROOT = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/execution_polars_project/src"
)


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    module = importlib.import_module("execution_polars_worker.execution_polars_worker")
    monkeypatch.setattr(module, "_runtime", {})
    monkeypatch.setattr(module, "_TAIL_CHECKSUM_NUMBA_KERNEL", None)
    monkeypatch.setattr(module, "_TAIL_CHECKSUM_NUMBA_KERNEL_ATTEMPTED", True)
    monkeypatch.setattr(module.PolarsWorker, "_t0", None)
    return module


@pytest.mark.parametrize("shape", ["dict", "object", "namespace"])
def test_polars_start_publishes_normalized_paths_and_replaces_pool_state(
    runtime, tmp_path, shape
):
    worker = object.__new__(runtime.ExecutionPolarsWorker)
    values = dict(data_in="source", data_out="destination", reset_target=True)
    if shape == "dict":
        worker.args = values
    elif shape == "namespace":
        worker.args = SimpleNamespace(**values)
    else:
        worker.args = type("Args", (), {})()
        vars(worker.args).update(values)
    calls = []
    paths = SimpleNamespace(
        normalized_input="normalized/source",
        normalized_output="normalized/destination",
        output_path=tmp_path / "destination",
    )
    worker.setup_data_directories = lambda **kwargs: calls.append(kwargs) or paths
    worker.start()
    assert calls == [
        dict(
            source_path="source",
            target_path="destination",
            target_subdir="results",
            reset_target=True,
        )
    ]
    assert worker.args.data_in == "normalized/source"
    assert worker.data_out == tmp_path / "destination"
    worker.pool_init({"args": {"compute_passes": 2}})
    assert worker._current_args().compute_passes == 2
    assert worker.work_init() is None


@pytest.mark.parametrize(
    "plan,mode,dispatch",
    [([], 0, None), ([[1]], 0, "mono"), ([[1]], 1, "multi"), ([[1]], 4, "multi")],
)
@pytest.mark.parametrize("existing_timer", [False, True])
def test_polars_workflow_mode_routes_once_and_always_stops(
    runtime, monkeypatch, plan, mode, dispatch, existing_timer
):
    worker = object.__new__(runtime.ExecutionPolarsWorker)
    worker._mode = mode
    calls = []
    worker._exec_multi_process = lambda work, metadata: calls.append(
        ("multi", work, metadata)
    )
    worker._exec_mono_process = lambda work, metadata: calls.append(
        ("mono", work, metadata)
    )
    worker.stop = lambda: calls.append("stop")
    monkeypatch.setattr(runtime.PolarsWorker, "_t0", 8.0 if existing_timer else None)
    times = iter([10.0, 12.0])
    monkeypatch.setattr(runtime.time, "time", lambda: next(times))
    elapsed = worker.works(plan, {"metadata": True})
    assert calls == (
        [] if dispatch is None else [(dispatch, plan, {"metadata": True})]
    ) + ["stop"]
    assert elapsed == 2.0


@pytest.mark.parametrize("values,stride", [([], 64), ([1.0], 0), ([1.0], -1)])
def test_polars_scalar_and_array_tail_handle_empty_or_disabled_samples(
    runtime, values, stride
):
    arrays = [np.asarray(values, dtype=np.float64)] * 4
    assert (
        runtime._tail_checksum_scalar_py(*arrays, pass_count=1, sample_stride=stride)
        == 0.0
    )
    assert runtime._tail_checksum_numba_kernel_py(*arrays, 1, stride) == 0.0


def test_polars_failed_compiled_tail_falls_back_to_same_python_checksum(
    runtime, monkeypatch
):
    data = pl.DataFrame(
        {"x": [1.0, 2.0], "y": [2.0, 3.0], "signal": [0.2, 0.3], "weight": [1.0, 1.0]}
    )

    def unavailable_kernel(*args):
        raise RuntimeError("compiled kernel unavailable for this runtime")

    monkeypatch.setattr(runtime, "_TAIL_CHECKSUM_NUMBA_KERNEL", unavailable_kernel)
    actual, backend = runtime._tail_checksum_from_columns(
        data, pass_count=2, sample_stride=1
    )
    expected = runtime._tail_checksum_scalar_py(
        data["x"].to_list(),
        data["y"].to_list(),
        data["signal"].to_list(),
        data["weight"].to_list(),
        pass_count=2,
        sample_stride=1,
    )
    assert actual == pytest.approx(expected)
    assert backend == "python"
    assert runtime._TAIL_CHECKSUM_NUMBA_KERNEL is None
    worker = object.__new__(runtime.ExecutionPolarsWorker)
    worker.args = SimpleNamespace(compute_passes=2)
    assert (
        worker._python_tail_checksum(data)
        == runtime._tail_checksum_from_columns(data, pass_count=2)[0]
    )


@pytest.mark.parametrize("output_format", ["csv", "parquet"])
def test_polars_completion_persists_real_aggregation_and_reduction(
    runtime, tmp_path, output_format
):
    worker = object.__new__(runtime.ExecutionPolarsWorker)
    worker.args = SimpleNamespace(
        output_format=output_format, compute_passes=2, python_tail_stride=1
    )
    worker.data_out = tmp_path
    worker._worker_id = 7
    source = tmp_path / "input.csv"
    pl.DataFrame(
        {
            "group_id": [1, 1],
            "bucket": [0, 0],
            "segment": ["alpha", "alpha"],
            "x": [2.0, 4.0],
            "y": [1.0, 3.0],
            "signal": [0.5, 1.0],
            "weight": [1.0, 2.0],
        }
    ).write_csv(source)
    result = worker.work_pool(source)
    assert result["row_count"].to_list() == [2]
    assert result["x_sum"].to_list() == [6.0]
    assert result["engine"].to_list() == ["polars"]
    worker.work_done(result)
    output = tmp_path / f"7_output.{output_format}"
    restored = (
        pl.read_parquet(output) if output_format == "parquet" else pl.read_csv(output)
    )
    assert restored.to_dicts() == result.to_dicts()
    reduction = importlib.import_module("execution_polars.reduction")
    assert reduction.reduce_artifact_path(tmp_path, 7).is_file()


@pytest.mark.parametrize("frame", [None, pl.DataFrame()])
def test_polars_empty_completion_writes_nothing(runtime, tmp_path, frame):
    worker = object.__new__(runtime.ExecutionPolarsWorker)
    worker.data_out = tmp_path
    before = set(tmp_path.iterdir())
    worker.work_done(frame)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize(
    "frame, message",
    [
        (None, "non-empty"),
        (pl.DataFrame(), "non-empty"),
        (pl.DataFrame({"row_count": [1]}), "missing columns"),
    ],
)
def test_polars_reduction_rejects_incomplete_frames(runtime, frame, message):
    reduction = importlib.import_module("execution_polars.reduction")
    with pytest.raises(ValueError, match=message):
        reduction.partial_from_result_frame(frame, partial_id="invalid")


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"row_count": 0}, "no source rows"),
        ({"source_file_count": 0}, "no source files"),
        ({"engines": []}, "no engine metadata"),
    ],
)
def test_polars_reduction_rejects_empty_aggregate_metadata(runtime, updates, message):
    reduction = importlib.import_module("execution_polars.reduction")
    payload = dict(row_count=1, source_file_count=1, engines=["polars"])
    payload.update(updates)
    with pytest.raises(ValueError, match=message):
        reduction.EXECUTION_POLARS_REDUCE_CONTRACT.validate_artifact(
            SimpleNamespace(payload=payload)
        )
