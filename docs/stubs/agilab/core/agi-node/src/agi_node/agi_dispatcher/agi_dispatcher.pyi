"""Dispatch helpers for coordinating AGILab worker execution."""

import getpass
import io
import importlib
import os
import shutil
import sys
import stat
import tempfile
import time
import subprocess
import warnings
import traceback
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from types import SimpleNamespace
import numpy as np
from distutils.sysconfig import get_python_lib
import psutil
import humanize
import datetime
import logging
import socket
from copy import deepcopy
from agi_env import AgiEnv, normalize_path
from .base_worker import BaseWorker

logger = logging.getLogger(__name__)

workers_default = {socket.gethostbyname("localhost"): 1}

class WorkDispatcher:
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def _convert_functions_to_names(*args: Any, **kwargs: Any) -> Any: ...
    def _do_distrib(*args: Any, **kwargs: Any) -> Any: ...
    def _onerror(*args: Any, **kwargs: Any) -> Any: ...
    def make_chunks(*args: Any, **kwargs: Any) -> Any: ...
    def _make_chunks_optimal(*args: Any, **kwargs: Any) -> Any: ...
    def _make_chunks_fastest(*args: Any, **kwargs: Any) -> Any: ...
    def _load_module(*args: Any, **kwargs: Any) -> Any: ...
