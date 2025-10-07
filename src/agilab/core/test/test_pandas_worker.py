import pytest
import multiprocessing
import time

import sys
from pathlib import Path

multiprocessing.set_start_method("spawn", force=True)

data_src = Path(__file__).parent.parent
worker_root = data_src.parent
for src in [data_src, worker_root / "pandas_worker", worker_root / "agi_dispatcher"]:
    path = str(src.absolute() / "src")
    if path not in sys.path:
        sys.path.insert(0, str(path))

# Now import modules
from agi_node.pandas_worker import PandasWorker
import pandas as pd
from agi_node.agi_dispatcher import BaseWorker
# DummyWorker can be defined if needed for instance methods test.
class DummyWorker(BaseWorker):
    def works(self, workers_tree, workers_tree_info):
        # Minimal dummy implementation for testing purposes.
        pass

class DummyPandasWorker(PandasWorker):
    def __init__(self, worker_id=0, output_format="csv", verbose=0):
        self._worker_id = worker_id
        self.verbose = verbose
        self.args = {"output_format": output_format}
        self.data_out = None
        self.pool_vars = None
        self.last_df = None

    def _actual_work_pool(self, x):
        """Dummy implementation that returns a simple DataFrame."""
        return pd.DataFrame({"col": [x]})

    def work_init(self):
        pass

    def pool_init(self, pool_vars):
        pass

    def works(self, workers_tree, workers_tree_info):
        start = time.time()
        # Appelle la méthode réelle pour faire un travail minimal
        if self._mode == 0:
            self._exec_mono_process(workers_tree, workers_tree_info)
        elif self._mode == 1:
            self._exec_multi_process(workers_tree, workers_tree_info)
        else:
            pass
        end = time.time()
        return end - start

    def stop(self):
        pass

    # Override work_done to capture the DataFrame for inspection.
    def work_done(self, df: pd.DataFrame = None) -> None:
        self.last_df = df
        if self.data_out:
            super().work_done(df)



# --- Pytest Fixtures ---
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


# --- Tests ---
def test_work_pool(worker_csv):
    dummy_input = 42
    df = worker_csv.work_pool(dummy_input)
    assert isinstance(df, pd.DataFrame)
    assert df["col"].tolist() == [42]

def test_work_done_csv(worker_csv):
    df = pd.DataFrame({"col": [1, 2, 3]})
    worker_csv.work_done(df)
    output_file = worker_csv.data_out / "0_output.csv"
    assert output_file.exists(), f"Expected output file {output_file} to exist."
    df_read = pd.read_csv(str(output_file))
    assert df_read["col"].tolist() == [1, 2, 3]

def test_work_done_parquet(worker_parquet):
    df = pd.DataFrame({"col": [4, 5, 6]})
    worker_parquet.work_done(df)
    output_file = worker_parquet.data_out / "0_output.parquet"
    assert output_file.exists(), f"Expected output file {output_file} to exist."
    df_read = pd.read_parquet(str(output_file))
    assert df_read["col"].tolist() == [4, 5, 6]

def test_exec_mono_process(worker_csv):
    worker_csv._mode = 0
    workers_tree = {0: [[10, 20]]}
    workers_tree_info = None
    worker_csv.last_df = None
    worker_csv._exec_mono_process(workers_tree, workers_tree_info)
    result_df = worker_csv.last_df
    assert result_df is not None, "Expected a DataFrame from ._exec_mono_process."
    assert len(result_df) == 2, f"Expected DataFrame length 2, got {len(result_df)}."
    part_values = result_df["worker_id"].tolist()
    assert part_values == [str((0, 0)), str((0, 0))], f"Unexpected worker_id values: {part_values}"

def test_exec_multi_process(worker_csv):
    worker_csv._mode = 1
    workers_tree = {0: [[100, 102]]}
    workers_tree_info = None
    worker_csv.last_df = None
    worker_csv._exec_multi_process(workers_tree, workers_tree_info)
    result_df = worker_csv.last_df
    assert result_df is not None, "Expected a DataFrame from ._exec_multi_process."
    assert len(result_df) == 2, f"Expected DataFrame length 2, got {len(result_df)}."
    assert result_df["col"].tolist() == [100, 102], "Column 'col' does not match expected values."
    assert "worker_id" in result_df.columns, "Expected 'worker_id' in the DataFrame columns."

def test_works_method(worker_csv):
    dummy_tree = {0: [[1], [2, 3]]}
    dummy_info = None
    worker_csv._mode = 0
    exec_time = worker_csv.works(dummy_tree, dummy_info)
    assert isinstance(exec_time, float), "works() should return a float."
    assert exec_time > 0, f"Expected execution time > 0, got {exec_time}."

if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
