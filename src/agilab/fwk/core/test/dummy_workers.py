# Dummy subclass for testing PandasWorker.
import  pandas as pd
from agi_core.workers.pandas_worker import PandasWorker
from agi_core.workers.agi_worker import AgiWorker

# DummyWorker can be defined if needed for instance methods test.
class DummyWorker(AgiWorker):
    def works(self, workers_tree, workers_tree_info):
        # Minimal dummy implementation for testing purposes.
        pass

class DummyPandasWorker(PandasWorker):
    def __init__(self, worker_id=0, output_format="csv", verbose=0):
        self.worker_id = worker_id
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

    def stop(self):
        pass

    # Override work_done to capture the DataFrame for inspection.
    def work_done(self, df: pd.DataFrame = None) -> None:
        self.last_df = df
        if self.data_out:
            super().work_done(df)
