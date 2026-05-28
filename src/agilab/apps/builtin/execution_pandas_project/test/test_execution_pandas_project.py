from __future__ import annotations

import json
import sys
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from agi_node.reduction import ReduceArtifact
from agi_node.agi_dispatcher import BaseWorker


APP_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from execution_pandas.execution_pandas import ExecutionPandas
from execution_pandas.app_args import ExecutionPandasArgs
from execution_pandas.reduction import (
    REDUCE_ARTIFACT_NAME,
    REDUCER_NAME,
    build_reduce_artifact,
    partial_from_result_frame,
    reduce_artifact_path,
)
from execution_pandas_worker.execution_pandas_worker import (
    ExecutionPandasWorker,
    _fill_vectorized_score_array,
    _tail_checksum_from_arrays,
)


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


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
        target="execution_pandas_project",
    )


def test_execution_pandas_declares_cython_worker_reference_contract() -> None:
    settings = _load_toml(APP_ROOT / "src" / "app_settings.toml")
    worker_manifest = _load_toml(
        APP_ROOT / "src" / "execution_pandas_worker" / "pyproject.toml"
    )

    build_requires = {
        str(requirement).split(">", 1)[0].split("=", 1)[0].lower()
        for requirement in worker_manifest["build-system"]["requires"]
    }

    assert settings["args"]["kernel_mode"] == "typed_numeric"
    assert settings["cluster"]["cython"] is True
    assert {"setuptools", "cython"} <= build_requires


def test_execution_pandas_generates_dataset_and_distribution(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=3, nfile=3, rows_per_file=24, n_groups=6)

    manager = ExecutionPandas(env, args=args)
    files = sorted(manager.args.data_in.glob("*.csv"))

    assert len(files) == 3

    workers = {"127.0.0.1": 1}
    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution(workers)

    assert len(work_plan) == 1
    assert len(work_plan[0]) == 1
    assert len(work_plan[0][0]) == 3
    assert partition_key == "file"
    assert weights_key == "size_kb"
    assert unit == "KB"
    assert metadata[0][0]["file"] == "3 files"
    assert metadata[0][0]["size_kb"] >= 1
    assert "dir_path" not in manager.as_dict()


def test_execution_pandas_worker_processes_a_file(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=1, nfile=1, rows_per_file=16, n_groups=4)
    manager = ExecutionPandas(env, args=args)
    source = sorted(manager.args.data_in.glob("*.csv"))[0]

    worker = ExecutionPandasWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source))

    assert isinstance(result, pd.DataFrame)
    assert {
        "engine",
        "execution_model",
        "weighted_score",
        "python_tail_checksum",
        "kernel_mode",
        "kernel_runtime",
        "dtype_contract",
        "source_file",
    } <= set(result.columns)
    assert set(result["engine"]) == {"pandas"}
    assert set(result["execution_model"]) == {"process"}
    assert set(result["kernel_mode"]) == {"typed_numeric"}
    assert set(result["kernel_runtime"]) == {"python"}
    assert set(result["dtype_contract"]) == {"float64-contiguous"}


def test_execution_pandas_vectorized_tail_checksum_matches_scalar_reference() -> None:
    x_values = np.asarray([1.5, 2.0, 3.5, 5.0, 8.0], dtype=np.float64)
    y_values = np.asarray([0.2, 0.4, 0.6, 0.8, 1.0], dtype=np.float64)
    signal_values = np.asarray([0.1, -0.2, 0.3, -0.4, 0.5], dtype=np.float64)
    weight_values = np.asarray([1.0, 1.1, 1.2, 1.3, 1.4], dtype=np.float64)
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

    actual = _tail_checksum_from_arrays(
        x_values,
        y_values,
        signal_values,
        weight_values,
        pass_count=pass_count,
        sample_stride=sample_stride,
    )

    assert actual == expected


def test_execution_pandas_vectorized_score_fill_matches_reference() -> None:
    x_values = np.asarray([1.5, -2.0, 3.5, 5.0], dtype=np.float64)
    y_values = np.asarray([0.2, 0.4, -0.6, 0.8], dtype=np.float64)
    signal_values = np.asarray([0.1, -0.2, 0.3, -0.4], dtype=np.float64)
    weight_values = np.asarray([1.0, 1.1, 1.2, 1.3], dtype=np.float64)
    weighted_signal = signal_values * weight_values
    out = np.empty_like(x_values)

    _fill_vectorized_score_array(
        x_values,
        y_values,
        weighted_signal,
        x_scale=2.3,
        y_scale=0.45,
        out=out,
    )

    expected = np.abs((x_values * 2.3) - (y_values * 0.45) + weighted_signal)
    np.testing.assert_allclose(out, expected, rtol=0.0, atol=0.0)


def test_execution_pandas_typed_kernel_matches_dataframe_scores(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(
        n_partitions=1,
        nfile=1,
        rows_per_file=32,
        n_groups=4,
        compute_passes=5,
    )
    manager = ExecutionPandas(env, args=args)
    source = sorted(manager.args.data_in.glob("*.csv"))[0]

    frames: dict[str, pd.DataFrame] = {}
    for kernel_mode in ("typed_numeric", "dataframe"):
        run_args = manager.args.model_copy(update={"kernel_mode": kernel_mode})
        worker = ExecutionPandasWorker()
        worker.env = env
        worker.args = run_args.model_dump(mode="json")
        worker._worker_id = 0
        worker.verbose = 0
        worker.start()
        frames[kernel_mode] = worker.work_pool(str(source)).reset_index(drop=True)

    typed = frames["typed_numeric"]
    dataframe = frames["dataframe"]
    pd.testing.assert_series_equal(typed["row_count"], dataframe["row_count"])
    pd.testing.assert_series_equal(typed["source_file"], dataframe["source_file"])
    pd.testing.assert_series_equal(typed["engine"], dataframe["engine"])
    pd.testing.assert_series_equal(typed["execution_model"], dataframe["execution_model"])
    pd.testing.assert_series_equal(
        typed["weighted_score"],
        dataframe["weighted_score"],
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
    pd.testing.assert_series_equal(
        typed["score_max"],
        dataframe["score_max"],
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
    assert set(typed["kernel_mode"]) == {"typed_numeric"}
    assert set(dataframe["kernel_mode"]) == {"dataframe"}


def test_execution_pandas_reduce_contract_merges_result_partials(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=2, nfile=2, rows_per_file=16, n_groups=4)
    manager = ExecutionPandas(env, args=args)
    sources = sorted(manager.args.data_in.glob("*.csv"))
    worker = ExecutionPandasWorker()
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
    assert artifact.payload["engines"] == ["pandas"]
    assert artifact.payload["execution_models"] == ["process"]
    assert artifact.payload["kernel_modes"] == ["typed_numeric"]
    assert artifact.payload["kernel_runtimes"] == ["python"]
    assert artifact.payload["dtype_contracts"] == ["float64-contiguous"]


def test_execution_pandas_worker_runs_monoprocess_plan(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=2, nfile=2, rows_per_file=24, n_groups=6, reset_target=True)
    manager = ExecutionPandas(env, args=args)
    workers = {"127.0.0.1": 1}
    work_plan, metadata, *_ = manager.build_distribution(workers)

    worker = ExecutionPandasWorker()
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
    assert artifact.partial_ids == ("execution_pandas_worker_0",)
    assert artifact.payload["row_count"] == 48
    assert artifact.payload["source_file_count"] == 2
    assert artifact.payload["engines"] == ["pandas"]
    assert artifact.payload["kernel_modes"] == ["typed_numeric"]


def test_execution_pandas_worker_uses_parallel_path_for_pool_mode(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = ExecutionPandasArgs(n_partitions=4, nfile=4, rows_per_file=24, n_groups=6, reset_target=True)
    manager = ExecutionPandas(env, args=args)
    workers = {"127.0.0.1": 1}
    work_plan, metadata, *_ = manager.build_distribution(workers)

    worker = ExecutionPandasWorker()
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
