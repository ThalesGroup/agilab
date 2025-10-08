import os
import sys
import warnings
import logging
from pathlib import Path
from typing import List, Tuple
from pydantic import BaseModel
import env
import py7zr
from dag_worker import DagWorker
from typing import Any

logger = logging.getLogger(__name__)

class DagArgs(BaseModel):
    ...

class DagAppWorker(DagWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def pool_init(*args: Any, **kwargs: Any) -> Any: ...
    def work(self) -> Any: ...
    def stop(self) -> Any: ...
    def build_distribution(self) -> Any: ...
