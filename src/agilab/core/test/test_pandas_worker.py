import multiprocessing
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

multiprocessing.set_start_method("spawn", force=True)

data_src = Path(__file__).parent.parent
worker_root = data_src.parent
for src in [data_src, worker_root / "pandas_worker", worker_root / "agi_dispatcher"]:
    path = str(src.absolute() / "src")
    if path not in sys.path:
        sys.path.insert(0, str(path))

from agi_node.agi_dispatcher import BaseWorker
from agi_node.pandas_worker import PandasWorker
import agi_node.pandas_worker.pandas_worker as pandas_module


class DummyPandasWorker(PandasWorker):
    def __init__(self, worker_id=0, output_format="csv", verbose=0):
        self._worker_id = worker_id
        self.verbose = verbose
        self.args = {"output_format": output_format}
        self.data_out = None
        self.pool_vars = None
        self.last_df = None

    def _actual_work_pool(self, x):
        return pd.DataFrame({"col": [x]})

    def work_init(self):
        pass

    def pool_init(self, pool_vars):
        pass

    def works(self, workers_tree, workers_tree_info):
        start = time.time()
        if self._mode == 0:
            self._exec_mono_process(workers_tree, workers_tree_info)
        elif self._mode == 1:
            self._exec_multi_process(workers_tree, workers_tree_info)
        end = time.time()
        return end - start

    def stop(self):
        pass

    def work_done(self, df: pd.DataFrame = None) -> None:
        self.last_df = df
        if self.data_out:
            super().work_done(df)


class DispatchPandasWorker(PandasWorker):
    def __init__(self, mode=0):
        self._worker_id = 0
        self._mode = mode
        self.verbose = 0
        self.args = {"output_format": "csv"}
        self.data_out = None
        self.pool_vars = None
        self.called = []

    def _actual_work_pool(self, x):
        return pd.DataFrame({"col": [x]})

    def work_init(self):
        pass

    def pool_init(self, pool_vars):
        pass

    def _exec_multi_process(self, workers_plan, workers_plan_metadata):
        self.called.append("multi")

    def _exec_mono_process(self, workers_plan, workers_plan_metadata):
        self.called.append("mono")

    def stop(self):
        self.called.append("stop")


class NonDataFrameWorker(DummyPandasWorker):
    def _actual_work_pool(self, x):
        return x


class EmptyDataFrameWorker(DummyPandasWorker):
    def _actual_work_pool(self, x):
        return pd.DataFrame()


class FalsyWorkersPlan:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, item):
        return self._data[item]

    def __bool__(self):
        return False


class InlineProcessPool:
    def __init__(self, max_workers, initializer, initargs):
        self._initializer = initializer
        self._initargs = initargs

    def __enter__(self):
        if self._initializer:
            self._initializer(*self._initargs)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def map(self, fn, items):
        return [fn(item) for item in items]


@pytest.fixture
def temp_output_dir(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def worker_csv(temp_output_dir):
    worker = DummyPandasWorker(worker_id=0, output_format="csv", verbose=0)
    worker.data_out = temp_output_dir
    return worker


@pytest.fixture
def worker_parquet(temp_output_dir):
    worker = DummyPandasWorker(worker_id=0, output_format="parquet", verbose=0)
    worker.data_out = temp_output_dir
    return worker


def test_work_pool(worker_csv):
    df = worker_csv.work_pool(42)
    assert isinstance(df, pd.DataFrame)
    assert df["col"].tolist() == [42]


def test_work_done_csv(worker_csv):
    df = pd.DataFrame({"col": [1, 2, 3]})
    worker_csv.work_done(df)
    output_file = worker_csv.data_out / "0_output.csv"
    assert output_file.exists()
    df_read = pd.read_csv(str(output_file))
    assert df_read["col"].tolist() == [1, 2, 3]


def test_work_done_parquet(worker_parquet, pandas_parquet_io_stub):
    _ = pandas_parquet_io_stub
    df = pd.DataFrame({"col": [4, 5, 6]})
    worker_parquet.work_done(df)
    output_file = worker_parquet.data_out / "0_output.parquet"
    assert output_file.exists()
    df_read = pd.read_parquet(str(output_file))
    assert df_read["col"].tolist() == [4, 5, 6]


def test_work_done_unsupported_output_format_raises(temp_output_dir):
    worker = DummyPandasWorker(worker_id=0, output_format="json", verbose=0)
    worker.data_out = temp_output_dir
    with pytest.raises(ValueError, match="Unsupported output format"):
        PandasWorker.work_done(worker, pd.DataFrame({"col": [1]}))


def test_work_done_returns_early_on_none_or_empty(temp_output_dir):
    worker = DummyPandasWorker(worker_id=0, output_format="csv", verbose=0)
    worker.data_out = temp_output_dir
    PandasWorker.work_done(worker, None)
    PandasWorker.work_done(worker, pd.DataFrame())
    assert list(temp_output_dir.iterdir()) == []


def test_exec_mono_process(worker_csv):
    worker_csv._mode = 0
    worker_csv.last_df = None
    worker_csv._exec_mono_process({0: [[10, 20]]}, None)
    result_df = worker_csv.last_df
    assert result_df is not None
    assert len(result_df) == 2
    assert result_df["worker_id"].tolist() == [str((0, 0)), str((0, 0))]


def test_exec_multi_process(monkeypatch, worker_csv):
    monkeypatch.setattr(pandas_module, "ProcessPoolExecutor", InlineProcessPool)
    worker_csv._mode = 1
    worker_csv.last_df = None
    worker_csv._exec_multi_process({0: [[100, 102]]}, None)
    result_df = worker_csv.last_df
    assert result_df is not None
    assert len(result_df) == 2
    assert result_df["col"].tolist() == [100, 102]
    assert "worker_id" in result_df.columns


def test_exec_multi_process_with_list_plan(monkeypatch, worker_csv):
    monkeypatch.setattr(pandas_module, "ProcessPoolExecutor", InlineProcessPool)
    worker_csv._mode = 1
    worker_csv.last_df = None
    worker_csv._exec_multi_process([[[200, 201]]], None)
    result_df = worker_csv.last_df
    assert result_df is not None
    assert result_df["col"].tolist() == [200, 201]


def test_exec_multi_process_windows_branch(monkeypatch, worker_csv):
    monkeypatch.setattr(pandas_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(pandas_module, "ProcessPoolExecutor", InlineProcessPool)

    worker_csv.last_df = None
    worker_csv.data_out = None
    worker_csv._exec_multi_process([[[9, 10]]], None)
    assert worker_csv.last_df is not None
    assert worker_csv.last_df["col"].tolist() == [9, 10]


def test_exec_mono_process_handles_non_dataframe_outputs(temp_output_dir):
    worker = NonDataFrameWorker(worker_id=0, output_format="csv", verbose=0)
    worker.data_out = temp_output_dir
    worker._exec_mono_process({0: [[1, 2]]}, None)
    assert worker.last_df is not None
    assert worker.last_df.empty


def test_exec_mono_process_handles_empty_dataframe_outputs(temp_output_dir):
    worker = EmptyDataFrameWorker(worker_id=0, output_format="csv", verbose=0)
    worker.data_out = temp_output_dir
    worker._exec_mono_process({0: [[1, 2]]}, None)
    assert worker.last_df is not None
    assert worker.last_df.empty


def test_exec_mono_process_handles_falsy_workers_plan(worker_csv):
    worker_csv.last_df = None
    worker_csv._exec_mono_process(FalsyWorkersPlan({0: [[1, 2]]}), None)
    assert worker_csv.last_df is not None
    assert worker_csv.last_df.empty


def test_works_method(worker_csv):
    worker_csv._mode = 0
    exec_time = worker_csv.works({0: [[1], [2, 3]]}, None)
    assert isinstance(exec_time, float)
    assert exec_time > 0


def test_pandas_worker_works_dispatches_mono_and_stops():
    BaseWorker._t0 = time.time() - 0.01
    worker = DispatchPandasWorker(mode=0)
    elapsed = worker.works({0: [[1]]}, None)
    assert worker.called == ["mono", "stop"]
    assert elapsed >= 0.0


def test_pandas_worker_works_dispatches_multi_and_stops():
    BaseWorker._t0 = time.time() - 0.01
    worker = DispatchPandasWorker(mode=4)
    elapsed = worker.works({0: [[1]]}, None)
    assert worker.called == ["multi", "stop"]
    assert elapsed >= 0.0


def test_pandas_worker_works_without_plan_stops_and_initializes_t0():
    BaseWorker._t0 = None
    worker = DispatchPandasWorker(mode=0)
    elapsed = worker.works(None, None)
    assert worker.called == ["stop"]
    assert BaseWorker._t0 is not None
    assert elapsed >= 0.0


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
