"""Color-aware logging helpers used across AGILab components."""

import logging
import os
import threading
from pathlib import Path
import re
import sys
from typing import Any

RESET = "\033[0m"

COLORS = {
    "time": "\033[90m",       # bright black / gray
    "level": {
        "DEBUG": "\033[36m",  # cyan
        "INFO": "\033[32m",   # green
        "WARNING": "\033[33m",# yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[41m" # red background
    },
    "classname": "\033[35m",  # magenta
    "msg": "\033[39m"         # white
}

ANSI_SGR_RE = re.compile(r'\x1b\[[0-9;]*m')

class ClassNameFilter(logging.Filter):
    def filter(self, *args: Any, **kwargs: Any) -> Any: ...

class MaxLevelFilter(logging.Filter):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def filter(self, *args: Any, **kwargs: Any) -> Any: ...

class LogFormatter(logging.Formatter):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def format(self, *args: Any, **kwargs: Any) -> Any: ...

class AgiLogger:
    def configure(cls, *args: Any, **kwargs: Any) -> Any: ...
    def get_logger(cls, *args: Any, **kwargs: Any) -> Any: ...
    def set_level(cls, *args: Any, **kwargs: Any) -> Any: ...
    def decolorize(*args: Any, **kwargs: Any) -> Any: ...
