# BSD 3-Clause License
#
# [License Text Remains Unchanged]
#
# (Include the full BSD 3-Clause License text here)

"""

data_worker Framework Callback Functions Module
===============================================

This module provides the `PolarsWorker` class, which extends the foundational
functionalities of `BaseWorker` for processing data using a thread pool or
single-threaded approaches. The pool path deliberately uses threads rather
than processes: polars releases the GIL in its native kernels, so threads
parallelise IO/native work without process spawn and pickling costs.

Classes:
    PolarsWorker: Worker class for data processing tasks.

External Libraries:
    concurrent.futures.ThreadPoolExecutor
    pathlib.Path
    polars as pl
    BaseWorker from node import BaseWorker


"""

# External Libraries:
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agi_node.agi_dispatcher import BaseWorker
from agi_node.agi_dispatcher import worker_pool_support

import polars as pl
import logging
logger = logging.getLogger(__name__)


def _thread_pool_factory(*, max_workers, initializer, initargs):
    """Build the thread pool for the pool execution path.

    ``ThreadPoolExecutor`` is resolved through this module's global namespace
    so tests can monkeypatch ``polars_worker.ThreadPoolExecutor``.
    """
    return ThreadPoolExecutor(
        max_workers=max_workers,
        initializer=initializer,
        initargs=initargs,
    )


def _concat_labeled(frames, labels):
    """Label each frame with its worker_id and concatenate vertically."""
    labeled = [
        frame.with_columns(pl.lit(label).alias("worker_id"))
        for frame, label in zip(frames, labels)
    ]
    return pl.concat(labeled, how="vertical")


_POLARS_POOL_HOOKS = worker_pool_support.PoolFrameHooks(
    family="PolarsWorker",
    executor_kind="thread",
    executor_factory=_thread_pool_factory,
    is_frame=lambda result: isinstance(result, pl.DataFrame),
    is_empty=lambda df: df.is_empty(),
    concat_labeled=_concat_labeled,
    empty_frame=pl.DataFrame,
)

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

    def work_pool(self, x: any = None) -> pl.DataFrame:  # ty: ignore[invalid-type-form]
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
        return self._actual_work_pool(x)  # ty: ignore[unresolved-attribute]

    def work_done(self, df: pl.DataFrame = None) -> None:  # ty: ignore[invalid-parameter-default]
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
        # work_done is called once per work chunk; suffix subsequent chunks so
        # they do not overwrite the first chunk's output file.
        chunk_index = getattr(self, "_work_done_chunk", 0)
        self._work_done_chunk = chunk_index + 1
        output_filename = (
            f"{self._worker_id}_output"
            if chunk_index == 0
            else f"{self._worker_id}_output_{chunk_index}"
        )

        if output_format == "parquet":
            output_path = Path(self.data_out) / f"{output_filename}.parquet"
            df.write_parquet(output_path)
        elif output_format == "csv":
            output_path = Path(self.data_out) / f"{output_filename}.csv"
            df.write_csv(output_path)
        else:
            raise ValueError("Unsupported output format")

    def works(self, workers_plan: any, workers_plan_metadata: any) -> float:  # ty: ignore[invalid-type-form]
        """
        Executes worker tasks based on the distribution tree.

        Args:
            workers_plan (any): Distribution tree structure.
            workers_plan_metadata (any): Additional information about the workers.

        Returns:
            float: Execution time of this works() call in seconds.
        """
        return worker_pool_support.run_works(self, workers_plan, workers_plan_metadata)

    def _exec_multi_process(self, workers_plan: any, workers_plan_metadata: any) -> None:  # ty: ignore[invalid-type-form]
        """
        Executes tasks with a thread pool shared across all plan chunks.

        Args:
            workers_plan (any): Distribution tree structure.
            workers_plan_metadata (any): Additional information about the workers.
        """
        worker_pool_support.exec_multi_process(
            self, workers_plan, workers_plan_metadata, _POLARS_POOL_HOOKS
        )

    def _exec_mono_process(self, workers_plan: any, workers_plan_metadata: any) -> None:  # ty: ignore[invalid-type-form]
        """
        Executes tasks in single-threaded mode.

        Args:
            workers_plan (any): Distribution tree structure.
            workers_plan_metadata (any): Additional information about the workers.
        """
        worker_pool_support.exec_mono_process(
            self, workers_plan, workers_plan_metadata, _POLARS_POOL_HOOKS
        )
