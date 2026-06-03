from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import polars as pl

from agi_node.reduction import ReduceArtifact
from agi_node.agi_dispatcher import BaseWorker


APP_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from execution_polars.execution_polars import ExecutionPolars
from execution_polars.app_args import ExecutionPolarsArgs
from execution_polars.reduction import (
    REDUCE_ARTIFACT_NAME,
    REDUCER_NAME,
    build_reduce_artifact,
    partial_from_result_frame,
    reduce_artifact_path,
)
from execution_polars_worker import execution_polars_worker as worker_module
from execution_polars_worker.execution_polars_worker import (
    TAIL_KERNEL_RUNTIME_COLUMN,
    ExecutionPolarsWorker,
    _tail_checksum_from_columns,
    _tail_checksum_numba_kernel_py,
    _tail_checksum_scalar_py,
)


def _make_env(tmp_path: Path) -> SimpleNamespace:
    share_root = tmp_path / "share"
    share_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        verbose=0,
        resolve_share_path=_resolve_share_path,
        home_abs=tmp_path,
        _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share_root),
        target="execution_polars_project",
    )


def test_execution_polars_generates_dataset_and_distribution(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPolarsArgs(n_partitions=2, nfile=2, rows_per_file=20, n_groups=5)

    manager = ExecutionPolars(env, args=args)
    files = sorted(manager.args.data_in.glob("*.csv"))

    assert len(files) == 2

    workers = {"127.0.0.1": 1}
    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution(workers)

    assert len(work_plan) == 1
    assert len(work_plan[0]) == 1
    assert len(work_plan[0][0]) == 2
    assert partition_key == "file"
    assert weights_key == "size_kb"
    assert unit == "KB"
    assert metadata[0][0]["file"] == "2 files"
    assert metadata[0][0]["size_kb"] >= 1
    assert "dir_path" not in manager.as_dict()


def test_execution_polars_worker_processes_a_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(worker_module, "_get_tail_checksum_numba_kernel", lambda: None)
    env = _make_env(tmp_path)
    args = ExecutionPolarsArgs(n_partitions=1, nfile=1, rows_per_file=16, n_groups=4)
    manager = ExecutionPolars(env, args=args)
    source = sorted(manager.args.data_in.glob("*.csv"))[0]

    worker = ExecutionPolarsWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source))

    assert isinstance(result, pl.DataFrame)
    assert {"engine", "execution_model", "weighted_score", "python_tail_checksum", "source_file"} <= set(result.columns)
    assert set(result["engine"].to_list()) == {"polars"}
    assert set(result["execution_model"].to_list()) == {"threads"}
    assert set(result[TAIL_KERNEL_RUNTIME_COLUMN].to_list()) == {"python"}


def test_execution_polars_tail_checksum_matches_scalar_reference() -> None:
    x_values = [1.5, 2.0, 3.5, 5.0, 8.0]
    y_values = [0.2, 0.4, 0.6, 0.8, 1.0]
    signal_values = [0.1, -0.2, 0.3, -0.4, 0.5]
    weight_values = [1.0, 1.1, 1.2, 1.3, 1.4]
    pass_count = 3
    sample_stride = 2

    expected = 0.0
    for idx in range(0, len(x_values), sample_stride):
        value = float(x_values[idx]) + float(y_values[idx]) * 0.01
        signal = float(signal_values[idx])
        weight = float(weight_values[idx])
        for _ in range(pass_count * 8):
            value = abs((value * 1.0000007) + signal * 0.17 - weight * 0.03)
        expected += value

    actual = _tail_checksum_scalar_py(
        x_values,
        y_values,
        signal_values,
        weight_values,
        pass_count=pass_count,
        sample_stride=sample_stride,
    )

    assert actual == expected


def test_execution_polars_tail_checksum_uses_optional_numba_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = pl.DataFrame(
        {
            "x": [1.5, 2.0, 3.5, 5.0, 8.0],
            "y": [0.2, 0.4, 0.6, 0.8, 1.0],
            "signal": [0.1, -0.2, 0.3, -0.4, 0.5],
            "weight": [1.0, 1.1, 1.2, 1.3, 1.4],
        }
    )
    calls = {"count": 0}

    def fake_kernel(*args):
        calls["count"] += 1
        return _tail_checksum_numba_kernel_py(*args)

    monkeypatch.setattr(worker_module, "_get_tail_checksum_numba_kernel", lambda: fake_kernel)

    checksum, runtime_label = _tail_checksum_from_columns(df, pass_count=3, sample_stride=2)
    expected = _tail_checksum_scalar_py(
        df["x"].to_list(),
        df["y"].to_list(),
        df["signal"].to_list(),
        df["weight"].to_list(),
        pass_count=3,
        sample_stride=2,
    )

    assert checksum == expected
    assert runtime_label == "numba"
    assert calls["count"] == 1


def test_execution_polars_tail_checksum_falls_back_after_kernel_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = pl.DataFrame(
        {
            "x": [1.5, 2.0, 3.5],
            "y": [0.2, 0.4, 0.6],
            "signal": [0.1, -0.2, 0.3],
            "weight": [1.0, 1.1, 1.2],
        }
    )

    def broken_kernel(*_args):
        raise RuntimeError("numba kernel failed")

    monkeypatch.setattr(worker_module, "_get_tail_checksum_numba_kernel", lambda: broken_kernel)

    checksum, runtime_label = _tail_checksum_from_columns(df, pass_count=2, sample_stride=1)
    expected = _tail_checksum_scalar_py(
        df["x"].to_list(),
        df["y"].to_list(),
        df["signal"].to_list(),
        df["weight"].to_list(),
        pass_count=2,
        sample_stride=1,
    )

    assert checksum == expected
    assert runtime_label == "python"


def test_execution_polars_reduce_contract_merges_result_partials(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPolarsArgs(n_partitions=2, nfile=2, rows_per_file=16, n_groups=4)
    manager = ExecutionPolars(env, args=args)
    sources = sorted(manager.args.data_in.glob("*.csv"))
    worker = ExecutionPolarsWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.verbose = 0
    worker.start()

    first = worker.work_pool(str(sources[0]))
    second = worker.work_pool(str(sources[1]))
    artifact = build_reduce_artifact(
        (
            partial_from_result_frame(first, partial_id="first"),
            partial_from_result_frame(second, partial_id="second"),
        )
    )

    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 2
    assert artifact.partial_ids == ("first", "second")
    assert artifact.payload["row_count"] == 32
    assert artifact.payload["source_file_count"] == 2
    assert artifact.payload["engines"] == ["polars"]
    assert artifact.payload["execution_models"] == ["threads"]


def test_execution_polars_worker_runs_monoprocess_plan(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPolarsArgs(n_partitions=2, nfile=2, rows_per_file=24, n_groups=6, reset_target=True)
    manager = ExecutionPolars(env, args=args)
    workers = {"127.0.0.1": 1}
    work_plan, metadata, *_ = manager.build_distribution(workers)

    worker = ExecutionPolarsWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker._mode = 0

    BaseWorker._t0 = time.time()
    worker.start()
    seconds = worker.works(work_plan, metadata)

    assert seconds >= 0.0
    assert any(Path(worker.data_out).glob("*.csv"))
    artifact_path = reduce_artifact_path(worker.data_out, 0)
    assert artifact_path.exists()
    artifact = ReduceArtifact.from_dict(json.loads(artifact_path.read_text(encoding="utf-8")))
    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 1
    assert artifact.partial_ids == ("execution_polars_worker_0",)
    assert artifact.payload["row_count"] == 48
    assert artifact.payload["source_file_count"] == 2
    assert artifact.payload["engines"] == ["polars"]


def test_execution_polars_worker_uses_parallel_path_for_pool_mode(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPolarsArgs(n_partitions=4, nfile=4, rows_per_file=24, n_groups=6, reset_target=True)
    manager = ExecutionPolars(env, args=args)
    workers = {"127.0.0.1": 1}
    work_plan, metadata, *_ = manager.build_distribution(workers)

    worker = ExecutionPolarsWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker._mode = 1

    calls = {"parallel": 0}

    def _fake_multi(plan, meta):
        calls["parallel"] += 1

    worker._exec_multi_process = _fake_multi

    BaseWorker._t0 = time.time()
    worker.start()
    seconds = worker.works(work_plan, metadata)

    assert seconds >= 0.0
    assert calls["parallel"] == 1
