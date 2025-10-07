"""Color-aware logging helpers used across AGILab components."""

import logging
import os
import threading
from pathlib import Path
import re
import sys

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
    """Inject the originating class name into log records when available."""

    def filter(self, record):
        try:
            frame = sys._getframe(0)
            while frame:
                code = frame.f_code
                if code.co_filename == record.pathname and code.co_name == record.funcName:
                    if 'self' in frame.f_locals:
                        record.classname = frame.f_locals['self'].__class__.__name__
                    else:
                        record.classname = record.module or record.pathname
                    break
                frame = frame.f_back
            else:
                record.classname = '<no-class>'
        except Exception:
            record.classname = '<no-class>'
        return True

class MaxLevelFilter(logging.Filter):
    """Filter out records whose severity exceeds ``max_level``."""

    def __init__(self, max_level):
        self.max_level = max_level

    def filter(self, record):
        return record.levelno <= self.max_level

class LogFormatter(logging.Formatter):
    """Formatter that adds colours and collapses build-tool noise when quiet."""

    def __init__(self, *args, verbose=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbose = verbose

    def format(self, record):
        level_color = COLORS["level"].get(record.levelname, "")
        levelname = level_color

        #Virtual Environment (if any)
        venv = sys.prefix
        venv_str = COLORS["classname"] + "<unknown>" + RESET
        if venv:
            venv_str = (venv.split("\\")[-2] if os.name == "nt" else venv.split("/")[-2])

        # Classname / function (collapse to just 'build.py' if the source file is build.py)
        className = getattr(record, "classname", record.name)
        functionName = getattr(record, "funcName", record.funcName)
        try:
            filename = os.path.basename(getattr(record, "pathname", "")) or f"{record.module}.py"
        except Exception:
            filename = f"{getattr(record, 'module', '<?>')}.py"
        if (filename == "build.py" or "setuptools" in getattr(record, "pathname", "")
                or "distutils" in getattr(record, "pathname", "")):
            if self.verbose < 2:
                return ""
            functionName_str =  "build.py" + RESET
        else:
            functionName_str = className + "." + functionName + RESET

        # Message
        message = COLORS["msg"] + record.getMessage() + RESET
        if not hasattr(record, "subprocess"):
            return levelname + venv_str + '.' + functionName_str + ' ' + message
        return f"{message}"

class AgiLogger:
    """Thread-safe wrapper around ``logging`` configuration for AGILab."""

    _lock = threading.Lock()
    _configured = False
    _base_name = "agilab"

    @classmethod
    def configure(cls, *,
                  verbose: int | None = None,
                  base_name: str | None = None,
                  force: bool = False) -> logging.Logger:
        """Initialise root logging handlers and return the base package logger."""

        with cls._lock:
            if cls._configured and not force:
                return logging.getLogger(base_name or cls._base_name)

            alog = logging.getLogger("asyncssh")
            alog.setLevel(logging.WARNING)  # or logging.ERROR to hide warnings too
            alog.propagate = False  # don't bubble up to the root handlers
            alog.addHandler(logging.NullHandler())  # optional: ensures no handler = no outp

            if base_name:
                cls._base_name = base_name

            if verbose is None:
                verbose = 0
            cls.verbose = verbose

            # Configure ROOT so direct logging.info(...) calls are captured.
            root = logging.getLogger()
            root.setLevel(logging.INFO)

            for handler in root.handlers[:]:
                root.removeHandler(handler)

            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setLevel(logging.INFO)
            stdout_handler.setFormatter(LogFormatter(verbose=verbose, datefmt="%H:%M:%S"))
            stdout_handler.addFilter(ClassNameFilter())
            stdout_handler.addFilter(MaxLevelFilter(logging.WARNING))

            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(logging.ERROR)
            stderr_handler.setFormatter(LogFormatter(verbose=verbose, datefmt="%H:%M:%S"))
            stderr_handler.addFilter(ClassNameFilter())

            root.addHandler(stdout_handler)
            root.addHandler(stderr_handler)

            # Expose a base package logger; child loggers will propagate to ROOT.
            pkg_logger = logging.getLogger(cls._base_name)
            pkg_logger.setLevel(logging.INFO)
            pkg_logger.propagate = True

            cls._configured = True
            return pkg_logger

    @classmethod
    def get_logger(cls, name: str | None = None) -> logging.Logger:
        """Return a child logger of the AGILab base logger."""

        base = logging.getLogger(cls._base_name)
        return base

    @classmethod
    def set_level(cls, level: int) -> None:
        """Update the root logger level."""

        logging.getLogger().setLevel(level)

    @staticmethod
    def decolorize(s: str) -> str:
        """Strip ANSI colour codes from ``s``."""

        return ANSI_SGR_RE.sub('', s)
