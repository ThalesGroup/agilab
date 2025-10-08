import asyncio
import logging
import os
import runpy
import warnings
from IPython.lib import backgroundjobs as bg
from dask.distributed import Client
from agi_env import AgiEnv, normalize_path
from managers import AGI
from typing import Any

logger = logging.getLogger(__name__)

def main(*args: Any, **kwargs: Any) -> Any: ...
