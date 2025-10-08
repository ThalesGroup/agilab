"""data_worker Framework Callback Functions Module
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
    BaseWorker from node import BaseWorker"""

import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker
import polars as pl
import logging
from typing import Any

logger = logging.getLogger(__name__)

class PolarsWorker(BaseWorker):
    def work_pool(self, *args: Any, **kwargs: Any) -> Any: ...
    def work_done(self, *args: Any, **kwargs: Any) -> Any: ...
    def works(self, *args: Any, **kwargs: Any) -> Any: ...
    def _exec_multi_process(self, *args: Any, **kwargs: Any) -> Any: ...
    def _exec_mono_process(self, *args: Any, **kwargs: Any) -> Any: ...
