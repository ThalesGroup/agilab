"""pandas_worker Framework Callback Functions Module
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
    BaseWorker from node import BaseWorker.node"""

import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time
from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker
import pandas as pd
import logging
from typing import Any

logger = logging.getLogger(__name__)

class PandasWorker(BaseWorker):
    def work_pool(self, *args: Any, **kwargs: Any) -> Any: ...
    def work_done(self, *args: Any, **kwargs: Any) -> Any: ...
    def works(self, *args: Any, **kwargs: Any) -> Any: ...
    def _exec_multi_process(self, *args: Any, **kwargs: Any) -> Any: ...
    def _exec_mono_process(self, *args: Any, **kwargs: Any) -> Any: ...
