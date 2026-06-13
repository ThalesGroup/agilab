# BSD 3-Clause License
#
# [License Text Remains Unchanged]
#
# (Include the full BSD 3-Clause License text here)

"""

pandas_worker Framework Callback Functions Module
==================================================

This module provides the `PandasWorker` class, which extends the foundational
functionalities of `BaseWorker` for processing data using multiprocessing or
single-threaded approaches with pandas.

Classes:
    PandasWorker: Worker class for data processing tasks using pandas.

Internal Libraries:
    os

External Libraries:
    concurrent.futures.ProcessPoolExecutor
    pathlib.Path
    pandas as pd
    BaseWorker from node import BaseWorker.node

"""

# External Libraries:
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from agi_node.agi_dispatcher import BaseWorker
from agi_node.agi_dispatcher import worker_pool_support

import pandas as pd
import logging
logger = logging.getLogger(__name__)


def _process_pool_factory(*, max_workers, initializer, initargs):
    """Build the process pool for the pool execution path.

    ``ProcessPoolExecutor`` is resolved through this module's global namespace
    so tests can monkeypatch ``pandas_worker.ProcessPoolExecutor``. The start
    method defaults to ``spawn`` (deterministic across platforms) and can be
    switched to ``forkserver`` via ``AGILAB_POOL_START_METHOD`` on POSIX; the
    pandas/numpy preload only matters for ``forkserver``.
    """
    return ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=initializer,
        initargs=initargs,
        mp_context=worker_pool_support.resolve_process_pool_context(
            preload=("pandas", "numpy")
        ),
    )


def _concat_labeled(frames, labels):
    """Concatenate frames and add the worker_id column in one allocation."""
    df = pd.concat(list(frames), axis=0, ignore_index=True)
    df["worker_id"] = np.repeat(
        np.asarray(list(labels), dtype=object),
        [len(frame) for frame in frames],
    )
    return df


_PANDAS_POOL_HOOKS = worker_pool_support.PoolFrameHooks(
    family="PandasWorker",
    executor_kind="process",
    executor_factory=_process_pool_factory,
    is_frame=lambda result: isinstance(result, pd.DataFrame),
    is_empty=lambda df: df.empty,
    concat_labeled=_concat_labeled,
    empty_frame=pd.DataFrame,
)

class PandasWorker(BaseWorker):
    """
    PandasWorker Class
    --------------------

    Inherits from ``BaseWorker`` to provide extended data processing functionalities using pandas.

    Attributes:
        verbose (int): Verbosity level for logging.
        data_out (str): Path to the output directory.
        worker_id (int): Identifier for the worker instance.
        args (dict): Configuration arguments for the worker.
    """

    def work_pool(self, x: any = None) -> pd.DataFrame:  # ty: ignore[invalid-type-form]
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
        return self._actual_work_pool(x)  # ty: ignore[unresolved-attribute]

    def work_done(self, df: pd.DataFrame = None) -> None:  # ty: ignore[invalid-parameter-default]
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
        # work_done is called once per work chunk; suffix subsequent chunks so
        # they do not overwrite the first chunk's output file.
        chunk_index = getattr(self, "_work_done_chunk", 0)
        self._work_done_chunk = chunk_index + 1
        output_filename = (
            f"{self._worker_id}_output"
            if chunk_index == 0
            else f"{self._worker_id}_output_{chunk_index}"
        )
        output_path = Path(self.data_out) / f"{output_filename}"

        if output_format == "parquet":
            df.to_parquet(output_path.with_suffix(".parquet"))
        elif output_format == "csv":
            df.to_csv(output_path.with_suffix(".csv"), index=False)
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
        Executes tasks with a process pool shared across all plan chunks.

        Args:
            workers_plan (any): Distribution tree structure.
            workers_plan_metadata (any): Additional information about the workers.
        """
        worker_pool_support.exec_multi_process(
            self, workers_plan, workers_plan_metadata, _PANDAS_POOL_HOOKS
        )

    def _exec_mono_process(self, workers_plan: any, workers_plan_metadata: any) -> None:  # ty: ignore[invalid-type-form]
        """
        Executes tasks in single-threaded mode.

        Args:
            workers_plan (any): Distribution tree structure.
            workers_plan_metadata (any): Additional information about the workers.
        """
        worker_pool_support.exec_mono_process(
            self, workers_plan, workers_plan_metadata, _PANDAS_POOL_HOOKS
        )
