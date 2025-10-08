"""Fireducks worker implementation.

The :class:`FireducksWorker` bridges AGILab's worker lifecycle with the
`fireducks` dataframe engine.  It extends :class:`PandasWorker` so that existing
pipelines can progressively adopt FireDucks without rewriting the surrounding
infrastructure.  Results returned from ``work_pool`` or passed to ``work_done``
may be native FireDucks objects, pandas DataFrames, or any object exposing a
``to_pandas``/``to_df`` conversion method."""

from __future__ import annotations
import logging
from typing import Any
import pandas as pd
from agi_node.pandas_worker import PandasWorker

logger = logging.getLogger(__name__)

class FireducksWorker(PandasWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def _ensure_pandas(*args: Any, **kwargs: Any) -> Any: ...
    def work_pool(self, *args: Any, **kwargs: Any) -> Any: ...
    def work_done(self, *args: Any, **kwargs: Any) -> Any: ...
