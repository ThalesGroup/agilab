import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
import subprocess
import polars as pl
import pytest

data_src = Path(__file__).parent.parent
worker_root = data_src.parent
for src in [data_src, worker_root / "dag_worker", worker_root / "agent_worker", worker_root / "agi_worker"]:
    path = str(src.absolute() / "src")
    if path not in sys.path:
        sys.path.insert(0, str(path))

# Import AgiDataWorker from your module.
from agi_core.workers.data_worker import AgiDataWorker

# Dummy subclass for testing AgiDataWorker.
class DummyAgiDataWorker(AgiDataWorker):
    def __init__(self, worker_id=0, output_format="csv", verbose=0):
        # Set minimal attributes needed for testing.
        self.worker_id = worker_id
        self.verbose = verbose
        self.args = {"output_format": output_format}
        # data_out will be set to a temporary directory during test.
        self.data_out = None
        # Dummy variables for pool initialization.
        self.pool_vars = None
        # To capture the DataFrame from work_done.
        self.last_df = None

    def _actual_work_pool(self, x):
        """Dummy implementation that returns a simple DataFrame."""
        return pl.DataFrame({"col": [x]})

    def work_init(self):
        """Dummy work_init method."""
        pass

    def pool_init(self, pool_vars):
        """Dummy pool_init method."""
        pass

    def stop(self):
        """Override stop so that it does not perform a real shutdown."""
        pass

    # Override work_done to capture the DataFrame for inspection.
    def work_done(self, df: pl.DataFrame = None) -> None:
        self.last_df = df
        if self.data_out:
            super().work_done(df)

# --- Pytest Fixtures ---
@pytest.fixture
def temp_output_dir(tmp_path):
    # Create and return a temporary output directory as a Path object.
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir

@pytest.fixture
def worker_csv(temp_output_dir):
    worker = DummyAgiDataWorker(worker_id=0, output_format="csv", verbose=0)
    worker.data_out = Path(temp_output_dir)
    return worker

@pytest.fixture
def worker_parquet(temp_output_dir):
    worker = DummyAgiDataWorker(worker_id=0, output_format="parquet", verbose=0)
    worker.data_out = Path(temp_output_dir)
    return worker

# --- Tests ---
def test_work_pool(worker_csv):
    # Verify work_pool returns a Polars DataFrame with expected content.
    dummy_input = 42
    df = worker_csv.work_pool(dummy_input)
    assert isinstance(df, pl.DataFrame)
    assert df["col"].to_list() == [42]

def test_work_done_csv(worker_csv):
    # Verify that work_done with CSV output creates a file with the correct content.
    df = pl.DataFrame({"col": [1, 2, 3]})
    worker_csv.work_done(df)
    output_file = worker_csv.data_out / "0_output.csv"
    assert output_file.exists(), f"Expected output file {output_file} to exist."
    df_read = pl.read_csv(str(output_file))
    assert df_read["col"].to_list() == [1, 2, 3]

def test_work_done_parquet(worker_parquet):
    # Verify that work_done with Parquet output creates a file with the correct content.
    df = pl.DataFrame({"col": [4, 5, 6]})
    worker_parquet.work_done(df)
    output_file = worker_parquet.data_out / "0_output.parquet"
    assert output_file.exists(), f"Expected output file {output_file} to exist."
    df_read = pl.read_parquet(str(output_file))
    assert df_read["col"].to_list() == [4, 5, 6]

def test_exec_mono_process(worker_csv):
    # For mono-process execution, set mode to an even number.
    worker_csv.mode = 0
    # workers_tree: For worker_id 0, one group of tasks with two elements.
    workers_tree = {0: [[10, 20]]}
    workers_tree_info = None
    worker_csv.last_df = None
    worker_csv.exec_mono_process(workers_tree, workers_tree_info)
    result_df = worker_csv.last_df
    assert result_df is not None, "Expected a DataFrame from exec_mono_process."
    # Expect two rows in the resulting DataFrame.
    assert result_df.height == 2, f"Expected DataFrame height of 2, got {result_df.height}."
    # Expect each row to have part_col equal to str((0, 0)).
    part_values = result_df["part_col"].to_list()
    assert part_values == [str((0, 0)), str((0, 0))], f"Unexpected part_col values: {part_values}"

def test_exec_multi_process(worker_csv):
    # For multi-process execution, set mode to an odd number.
    worker_csv.mode = 1
    workers_tree = {0: [[100, 200]]}
    workers_tree_info = None
    worker_csv.last_df = None
    worker_csv.exec_multi_process(workers_tree, workers_tree_info)
    result_df = worker_csv.last_df
    assert result_df is not None, "Expected a DataFrame from exec_multi_process."
    assert result_df.height == 2, f"Expected DataFrame height of 2, got {result_df.height}."
    assert result_df["col"].to_list() == [100, 200], "Column 'col' does not match expected values."
    assert "part_col" in result_df.columns, "Expected 'part_col' in the DataFrame columns."

def test_works_method(worker_csv):
    # Verify that works() returns a float execution time greater than zero.
    dummy_tree = {0: [[1], [2, 3]]}
    dummy_info = None
    worker_csv.mode = 0
    exec_time = worker_csv.works(dummy_tree, dummy_info)
    assert isinstance(exec_time, float), "works() should return a float."
    assert exec_time > 0, f"Expected execution time > 0, got {exec_time}."