import multiprocessing
import time
import sys
from pathlib import Path

import pandas as pd
import pytest

multiprocessing.set_start_method("spawn", force=True)

data_src = Path(__file__).parent.parent
worker_root = data_src.parent
for src in [data_src, worker_root / "fireducks_worker", worker_root / "agi_dispatcher"]:
    path = str(src.absolute() / "src")
    if path not in sys.path:
        sys.path.insert(0, path)

from agi_node.fireducks_worker import FireducksWorker
from agi_node.agi_dispatcher import BaseWorker


class DummyFireduckFrame:
    def __init__(self, value):
        self._df = pd.DataFrame({"col": [value]})

    def to_pandas(self):
        return self._df


class DummyFireducksWorker(FireducksWorker):
    def __init__(self, worker_id=0, output_format="csv", verbose=0):
        self._worker_id = worker_id
        self.verbose = verbose
        self.args = {"output_format": output_format}
        self.data_out = None
        self.pool_vars = None
        self.last_df = None

    def _actual_work_pool(self, x):
        return DummyFireduckFrame(x)

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


@pytest.fixture
def temp_output_dir(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def worker_csv(temp_output_dir):
    worker = DummyFireducksWorker(worker_id=0, output_format="csv", verbose=0)
    worker.data_out = temp_output_dir
    return worker


@pytest.fixture
def worker_parquet(temp_output_dir):
    worker = DummyFireducksWorker(worker_id=0, output_format="parquet", verbose=0)
    worker.data_out = temp_output_dir
    return worker


def test_work_pool(worker_csv):
    df = worker_csv.work_pool(42)
    assert isinstance(df, pd.DataFrame)
    assert df["col"].tolist() == [42]


def test_work_done_csv(worker_csv):
    worker_csv.work_done(pd.DataFrame({"col": [1, 2]}))
    output_file = worker_csv.data_out / "0_output.csv"
    assert output_file.exists()
    df_read = pd.read_csv(output_file)
    assert df_read["col"].tolist() == [1, 2]


def test_work_done_parquet(worker_parquet):
    worker_parquet.work_done(pd.DataFrame({"col": [3, 4]}))
    output_file = worker_parquet.data_out / "0_output.parquet"
    assert output_file.exists()
    df_read = pd.read_parquet(output_file)
    assert df_read["col"].tolist() == [3, 4]


def test_exec_mono_process(worker_csv):
    worker_csv._mode = 0
    workers_tree = {0: [[10, 20]]}
    worker_csv.last_df = None
    worker_csv._exec_mono_process(workers_tree, None)
    result_df = worker_csv.last_df
    assert result_df is not None
    assert len(result_df) == 2


def test_exec_multi_process(worker_csv):
    worker_csv._mode = 1
    workers_tree = {0: [[100, 102]]}
    worker_csv.last_df = None
    worker_csv._exec_multi_process(workers_tree, None)
    result_df = worker_csv.last_df
    assert result_df is not None
    assert result_df["col"].tolist() == [100, 102]


def test_works_method(worker_csv):
    dummy_tree = {0: [[1], [2, 3]]}
    worker_csv._mode = 0
    exec_time = worker_csv.works(dummy_tree, None)
    assert isinstance(exec_time, float)
    assert exec_time >= 0
