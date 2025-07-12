# BSD 3-Clause License
#
# [License Text Remains Unchanged]
#
# (Include the full BSD 3-Clause License text here)

"""

pandas_worker Framework Callback Functions Module
===============================================

This module provides the `PandasWorker` class, which extends the foundational
functionalities of `BaseWorker` for processing data using multiprocessing or
single-threaded approaches with pandas.

Classes:
    PandasWorker: Worker class for data processing tasks using pandas.

Internal Libraries:
    os, warnings

External Libraries:
    concurrent.futures.ProcessPoolExecutor
    pathlib.Path
    time
    pandas as pd
    BaseWorker from node import BaseWorker.node

"""

# Internal Libraries:
import os
import warnings

# External Libraries:
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time

from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker

import pandas as pd
import logging
warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

class PandasWorker(BaseWorker):
    """
    PandasWorker Class
    --------------------

    Inherits from :class:`BaseWorker` to provide extended data processing functionalities using pandas.

    Attributes:
        verbose (int): Verbosity level for logging.
        data_out (str): Path to the output directory.
        worker_id (int): Identifier for the worker instance.
        args (dict): Configuration arguments for the worker.
    """

    def work_pool(self, x: any = None) -> pd.DataFrame:
        """
        Processes a single task.

        Args:
            x (any, optional): The task to process. Defaults to None.

        Returns:
            pd.DataFrame: A pandas DataFrame with the processed results.
        """
        logging.info("work_pool")

        # Call the actual work_pool method, which should return a pandas DataFrame.
        # Ensure that the original _actual_work_pool method is refactored accordingly.
        return self._actual_work_pool(x)

    def work_done(self, df: pd.DataFrame = None) -> None:
        """
        Handles the post-processing of the DataFrame after `work_pool` execution.

        Args:
            df (pd.DataFrame, optional): The pandas DataFrame to process. Defaults to None.

        Raises:
            ValueError: If an unsupported output format is specified.
        """
        logging.info("work_done")

        if df is None or df.empty:
            return

        output_format = self.args.get("output_format")
        output_filename = f"{self.worker_id}_output"
        output_path = Path(self.data_out) / f"{output_filename}"

        if output_format == "parquet":
            df.to_parquet(output_path.with_suffix(".parquet"))
        elif output_format == "csv":
            df.to_csv(output_path.with_suffix(".csv"), index=False)
        else:
            raise ValueError("Unsupported output format")

    def works(self, workers_tree: any, workers_tree_info: any) -> float:
        """
        Executes worker tasks based on the distribution tree.

        Args:
            workers_tree (any): Distribution tree structure.
            workers_tree_info (any): Additional information about the workers.

        Returns:
            float: Execution time in seconds.
        """
        if workers_tree:
            if self.mode & 4:
                self.exec_multi_process(workers_tree, workers_tree_info)
            else:
                self.exec_mono_process(workers_tree, workers_tree_info)

        self.stop()

        if BaseWorker.t0 is None:
            BaseWorker.t0 = time.time()
        return time.time() - BaseWorker.t0

    def exec_multi_process(self, workers_tree: any, workers_tree_info: any) -> None:
        """
        Executes tasks in multiprocessing mode.

        Args:
            workers_tree (any): Distribution tree structure.
            workers_tree_info (any): Additional information about the workers.
        """
        works = []
        if isinstance(workers_tree, list):
            for i in workers_tree[self.worker_id]:
                works += i
            ncore = max(min(len(works), int(os.cpu_count())), 1)
        else:
            ncore = 1

        logging.info(
            f"PandasWorker.work - ncore {ncore} - mycode_worker #{self.worker_id}"
            f" - work_pool x {len(works)}",
        )

        self.work_init()
        for work_id, work in enumerate(workers_tree[self.worker_id]):
            list_df = []
            df = pd.DataFrame()
            ncore = max(min(len(work), int(os.cpu_count())), 1)

            if os.name == "nt":
                process_factory_type = "spawn"
            else:
                process_factory_type = "spawn"

            # Note: multiprocessing context commented out, as ThreadPoolExecutor is used
            # mp_ctx = multiprocessing.get_context(process_factory_type)

            with ProcessPoolExecutor(
                # mp_context=mp_ctx,
                max_workers=ncore,
                initializer=self.pool_init,
                initargs=(self.pool_vars,),
            ) as exec:
                dfs = exec.map(self.work_pool, work)

            for df_result in dfs:
                if not df_result.empty:
                    list_df.append(df_result)

            if list_df:
                for idx, df_result in enumerate(list_df):
                    df_result = df_result.copy()
                    df_result["worker_id"] = str((self.worker_id, idx))
                    list_df[idx] = df_result

                df = pd.concat(list_df, axis=0, ignore_index=True)

            self.work_done(df if not df.empty else pd.DataFrame())

    def exec_mono_process(self, workers_tree: any, workers_tree_info: any) -> None:
        """
        Executes tasks in single-threaded mode.

        Args:
            workers_tree (any): Distribution tree structure.
            workers_tree_info (any): Additional information about the workers.
        """
        self.work_init()
        for work_id, work in enumerate(workers_tree[self.worker_id]):
            list_df = []
            df = pd.DataFrame()
            logging.info(
                f"PandasWorker.work - monoprocess work #{work_id} - work_pool x {len(work)}"
            )

            if workers_tree:
                dfs = [self.work_pool(file) for file in work]

                if dfs and isinstance(dfs[0], pd.DataFrame):
                    for df_result in dfs:
                        if not df_result.empty:
                            list_df.append(df_result)

                    if list_df:
                        for idx, df_result in enumerate(list_df):
                            df_result = df_result.copy()
                            df_result["worker_id"] = str((self.worker_id, 0))
                            list_df[idx] = df_result

                        df = pd.concat(list_df, axis=0, ignore_index=True)

            self.work_done(df)
