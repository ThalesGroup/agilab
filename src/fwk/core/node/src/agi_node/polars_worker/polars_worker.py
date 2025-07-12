# BSD 3-Clause License
#
# [License Text Remains Unchanged]
#
# (Include the full BSD 3-Clause License text here)

"""

data_worker Framework Callback Functions Module
===============================================

This module provides the `PolarsWorker` class, which extends the foundational
functionalities of `BaseWorker` for processing data using multiprocessing or
single-threaded approaches.

Classes:
    PolarsWorker: Worker class for data processing tasks.

Internal Libraries:
    os, warnings

External Libraries:
    concurrent.futures.ProcessPoolExecutor
    pathlib.Path
    time
    polars as pl
    BaseWorker from node import BaseWorker


"""

# Internal Libraries:
import os
import warnings

# External Libraries:
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker

import polars as pl
import logging
warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

class PolarsWorker(BaseWorker):
    """
    PolarsWorker Class
    --------------------

    Inherits from :class:`BaseWorker` to provide extended data processing functionalities.

    Attributes:
        verbose (int): Verbosity level for logging.
        data_out (str): Path to the output directory.
        worker_id (int): Identifier for the worker instance.
        args (dict): Configuration arguments for the worker.
    """

    def work_pool(self, x: any = None) -> pl.DataFrame:
        """
        Processes a single task.

        Args:
            x (any, optional): The task to process. Defaults to None.

        Returns:
            pl.DataFrame: A Polars DataFrame with the processed results.
        """
        logging.info("work_pool")

        # Call the actual work_pool method, which should return a Polars DataFrame.
        # Ensure that the original _actual_work_pool method is refactored accordingly.
        return self._actual_work_pool(x)

    def work_done(self, df: pl.DataFrame = None) -> None:
        """
        Handles the post-processing of the DataFrame after `work_pool` execution.

        Args:
            df (pl.DataFrame, optional): The Polars DataFrame to process. Defaults to None.

        Raises:
            ValueError: If an unsupported output format is specified.
        """
        logging.info("work_done")

        if df is None or df.is_empty():
            return

        # Example post-processing logic using Polars.
        # For instance, saving the DataFrame to disk.
        output_format = self.args.get("output_format")
        output_filename = f"{self.worker_id}_output"

        if output_format == "parquet":
            output_path = Path(self.data_out) / f"{output_filename}.parquet"
            df.write_parquet(output_path)
        elif output_format == "csv":
            output_path = Path(self.data_out) / f"{output_filename}.csv"
            df.write_csv(output_path)
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
        ncore = 1
        works = []
        if isinstance(workers_tree, list):
            for i in workers_tree[self.worker_id]:
                works += i
            ncore = max(min(len(works), int(os.cpu_count())), 1)

        logging.info(
            f"PolarsWorker.work - ncore {ncore} - mycode_worker #{self.worker_id}"
            f" - work_pool x {len(works)}",
        )
        self.work_init()
        for work_id, work in enumerate(workers_tree[self.worker_id]):
            list_df = []
            df = pl.DataFrame()
            ncore = max(min(len(work), int(os.cpu_count())), 1)

            if os.name == "nt":
                process_factory_type = "spawn"
            else:
                process_factory_type ="spawn"

           # mp_ctx = multiprocessing.get_context(process_factory_type)

            with ThreadPoolExecutor(
                #mp_context=mp_ctx,
                max_workers=ncore,
                initializer=self.pool_init,
                initargs=(self.pool_vars,),
            ) as exec:
                # Map each work item to work_pool.
                dfs = exec.map(self.work_pool, work)
            # Post pool processinflight: collect non-empty DataFrames.
            for df_result in dfs:
                # Check if the result DataFrame has columns.
                if df_result.shape[1] > 0:
                    list_df.append(df_result)
                    # Additional processing per result can be done here.

            if list_df:
                # Add a 'worker_id' to each DataFrame.
                for idx, df_result in enumerate(list_df):
                    list_df[idx] = df_result.with_columns(
                        pl.lit(str((self.worker_id, idx))).alias("worker_id")
                    )

                # Concatenate all DataFrames into a single DataFrame.
                df = pl.concat(list_df, how="vertical")

            # Handle the concatenated DataFrame.
            self.work_done(df if not df.is_empty() else pl.DataFrame())

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
            df = pl.DataFrame()
            logging.info(
                f"PolarsWorker.work - monoprocess work #{work_id} - work_pool x {len(work)}"
            )

            if workers_tree:
                # Apply the work_pool function to each item in work.
                dfs = [self.work_pool(file) for file in work]

                # Ensure that the returned objects are Polars DataFrames.
                if dfs and isinstance(dfs[0], pl.DataFrame):
                    for df_result in dfs:
                        if not df_result.is_empty():
                            list_df.append(df_result)

                    if list_df:
                        # Add a 'worker_id' to each DataFrame.
                        for idx, df_result in enumerate(list_df):
                            list_df[idx] = df_result.with_columns(
                                pl.lit(str((self.worker_id, 0))).alias("worker_id")
                            )

                        # Concatenate all DataFrames into a single DataFrame.
                        df = pl.concat(list_df, how="vertical")

            # Handle the concatenated DataFrame.
            self.work_done(df)