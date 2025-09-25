import os
import sys
import signal
import logging
from pathlib import Path
from tempfile import gettempdir
import shutil
import subprocess
import zipfile
import platform
import threading
import time
import faulthandler
from typing import Any

USAGE = """
Usage: python cli.py <cmd> [arg]

Commands:
  kill [exclude_pids]      Kill processes, excluding comma-separated PIDs (optional)
  clean <wenv_path>        Clean the given wenv directory
  unzip <wenv_path>        Unzip resources into the given wenv directory
  threaded                 Run the Python threads test
  platform                 Show Python platform/version info

Examples:
  python cli.py kill
  python cli.py kill 1234,5678
  python cli.py clean /path/to/wenv
  python cli.py unzip /path/to/wenv
  python cli.py threaded
  python cli.py platform
"""

PS_TIMEOUT = float(os.environ.get("CLI_PS_TIMEOUT", "0.35"))

TASKLIST_TIMEOUT = float(os.environ.get("CLI_TASKLIST_TIMEOUT", "0.6"))

POLL_INTERVAL = float(os.environ.get("CLI_POLL_INTERVAL", "0.02"))

GRACE_TOTAL = float(os.environ.get("CLI_GRACE_TOTAL", "0.30"))

FREETHREADED_THRESHOLD = float(os.environ.get("CLI_FREETHREADED_THRESHOLD", "0.80"))

BASELINE_TARGET_S = float(os.environ.get("CLI_BASELINE_TARGET_S", "0.15"))

logger = logging.getLogger(__name__)

def clean(*args: Any, **kwargs: Any) -> Any: ...

def get_processes_containing(*args: Any, **kwargs: Any) -> Any: ...

def get_child_pids(*args: Any, **kwargs: Any) -> Any: ...

def _is_alive(*args: Any, **kwargs: Any) -> Any: ...

def kill_pids(*args: Any, **kwargs: Any) -> Any: ...

def _poll_until_dead(*args: Any, **kwargs: Any) -> Any: ...

def kill(*args: Any, **kwargs: Any) -> Any: ...

def unzip(*args: Any, **kwargs: Any) -> Any: ...

def _busy_work(*args: Any, **kwargs: Any) -> Any: ...

def _time_busy(*args: Any, **kwargs: Any) -> Any: ...

def _choose_iters(*args: Any, **kwargs: Any) -> Any: ...

def threaded(*args: Any, **kwargs: Any) -> Any: ...

def test_python_threads(*args: Any, **kwargs: Any) -> Any: ...

def python_version(*args: Any, **kwargs: Any) -> Any: ...
