import getpass
import glob
import os
import re
import shutil
import subprocess
import traceback
import warnings
from datetime import datetime as dt
from pathlib import Path
import logging
from types import SimpleNamespace
from agi_env import normalize_path
from agi_node.polars_worker import PolarsWorker
from agi_node.agi_dispatcher import BaseWorker
import polars as pl
from geopy.distance import geodesic
from typing import Any

logger = logging.getLogger(__name__)

class _MutableNamespace(SimpleNamespace):
    def __getitem__(self, *args: Any, **kwargs: Any) -> Any: ...
    def __setitem__(self, *args: Any, **kwargs: Any) -> Any: ...

class FlightWorker(PolarsWorker):
    def preprocess_df(self, *args: Any, **kwargs: Any) -> Any: ...
    def calculate_speed(self, *args: Any, **kwargs: Any) -> Any: ...
    def start(self) -> Any: ...
    def work_init(self) -> Any: ...
    def pool_init(self, *args: Any, **kwargs: Any) -> Any: ...
    def work_pool(self, *args: Any, **kwargs: Any) -> Any: ...
    def work_done(self, *args: Any, **kwargs: Any) -> Any: ...
    def stop(self) -> Any: ...
