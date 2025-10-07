import sys
from pathlib import Path
import polars as pl
import pytest

data_src = Path(__file__).parent.parent
worker_root = data_src.parent / "node/src"
for src in [data_src, worker_root / "polars_worker", worker_root / "agi_dispatcher"]:
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

# Import PolarsWorker from your module.
from agi_node.polars_worker import PolarsWorker

# Dummy subclass for testing PolarsWorker.
class DummyPolarsWorker(PolarsWorker):
    def __init__(self, worker_id=0, output_format="csv", verbose=0):
        self._worker_id = worker_id
        self.verbose = verbose
        self.args = {"output_format": output_format}
        self.data_out = None
        self.pool_vars = None
        self.last_df = None

    def _actual_work_pool(self, x):
        """Dummy implementation that returns a simple Polars DataFrame."""
        return pl.DataFrame({"col": [x]})

    def work_init(self):
        pass

    def pool_init(self, pool_vars):
        pass

    def stop(self):
        pass

    # Override work_done to capture the DataFrame for inspection.
    def work_done(self, df: pl.DataFrame = None) -> None:
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
    worker = DummyPolarsWorker(worker_id=0, output_format="csv", verbose=0)
    worker.data_out = temp_output_dir
    return worker

@pytest.fixture
def worker_parquet(temp_output_dir):
    worker = DummyPolarsWorker(worker_id=0, output_format="parquet", verbose=0)
    worker.data_out = temp_output_dir
    return worker


# --- Tests ---
def test_work_pool(worker_csv):
    dummy_input = 42
    df = worker_csv.work_pool(dummy_input)
    assert isinstance(df, pl.DataFrame)
    assert df["col"].to_list() == [42]

def test_work_done_csv(worker_csv):
    df = pl.DataFrame({"col": [1, 2, 3]})
    worker_csv.work_done(df)
    output_file = worker_csv.data_out / "0_output.csv"
    assert output_file.exists(), f"Expected output file {output_file} to exist."
    df_read = pl.read_csv(str(output_file))
    assert df_read["col"].to_list() == [1, 2, 3]

def test_work_done_parquet(worker_parquet):
    df = pl.DataFrame({"col": [4, 5, 6]})
    worker_parquet.work_done(df)
    output_file = worker_parquet.data_out / "0_output.parquet"
    assert output_file.exists(), f"Expected output file {output_file} to exist."
    df_read = pl.read_parquet(str(output_file))
    assert df_read["col"].to_list() == [4, 5, 6]

def test_exec_mono_process(worker_csv):
    worker_csv._mode = 0
    workers_tree = {0: [[10, 20]]}
    workers_tree_info = None
    worker_csv.last_df = None
    worker_csv._exec_mono_process(workers_tree, workers_tree_info)
    result_df = worker_csv.last_df
    assert result_df is not None, "Expected a DataFrame from ._exec_mono_process."
    assert result_df.height == 2, f"Expected DataFrame height 2, got {result_df.height}."
    part_values = result_df["worker_id"].to_list()
    assert part_values == [str((0, 0)), str((0, 0))], f"Unexpected worker_id values: {part_values}"

def test_exec_multi_process(worker_csv):
    worker_csv._mode = 1
    workers_tree = {0: [[100, 200]]}
    workers_tree_info = None
    worker_csv.last_df = None
    worker_csv._exec_multi_process(workers_tree, workers_tree_info)
    result_df = worker_csv.last_df
    assert result_df is not None, "Expected a DataFrame from ._exec_multi_process."
    assert result_df.height == 2, f"Expected DataFrame height 2, got {result_df.height}."
    assert result_df["col"].to_list() == [100, 200], "Column 'col' does not match expected values."
    assert "worker_id" in result_df.columns, "Expected 'worker_id' in the DataFrame columns."

def test_works_method(worker_csv):
    dummy_tree = {0: [[1], [2, 3]]}
    dummy_info = None
    worker_csv._mode = 0
    exec_time = worker_csv.works(dummy_tree, dummy_info)
    assert isinstance(exec_time, float), "works() should return a float."
    assert exec_time > 0, f"Expected execution time > 0, got {exec_time}."
