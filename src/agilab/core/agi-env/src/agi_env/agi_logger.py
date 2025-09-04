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
    "msg": "\033[97m"         # white
}
ANSI_SGR_RE = re.compile(r'\x1b\[[0-9;]*m')

class ClassNameFilter(logging.Filter):
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

class LogFormatter(logging.Formatter):
    def __init__(self, *args, verbose=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbose = verbose

    def format(self, record):
        # Time
        # asctime = COLORS["time"] + self.formatTime(record, self.datefmt) + RESET
        # Level (color depends on level)
        level_color = COLORS["level"].get(record.levelname, "")
        levelname = level_color + record.levelname + RESET

        #Virtual Environment (if any)
        venv = os.environ.get("VIRTUAL_ENV").split("/")[-2]
        venv_str = COLORS["classname"] + venv + RESET

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
            functionName_str = COLORS["classname"] + "build.py" + RESET
        else:
            functionName_str = COLORS["classname"] + className + "." + functionName + RESET

        # Message
        message = COLORS["msg"] + record.getMessage() + RESET
        if not hasattr(record, "subprocess"):
            return f"{venv_str} | {levelname} | {functionName_str} | {message}"
        return f"{message}"

class AgiLogger:
    _lock = threading.Lock()
    _configured = False
    _base_name = "agilab"

    @classmethod
    def configure(cls, *,
                  verbose: int | None = None,
                  log_dir: str | Path | None = None,
                  base_name: str | None = None,
                  force: bool = False) -> logging.Logger:
        with cls._lock:
            if cls._configured and not force:
                return logging.getLogger(base_name or cls._base_name)

            if base_name:
                cls._base_name = base_name

            if verbose is None:
                verbose = 0
            cls._verbose = verbose
            level = logging.DEBUG if verbose > 0 else logging.INFO

            # Configure ROOT so direct logging.info(...) calls are captured.
            root = logging.getLogger()
            root.setLevel(level)

            for handler in root.handlers[:]:
                root.removeHandler(handler)

            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setLevel(level)
            stdout_handler.setFormatter(LogFormatter(verbose=verbose, datefmt="%H:%M:%S"))
            stdout_handler.addFilter(ClassNameFilter())

            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(logging.WARNING)
            stderr_handler.setFormatter(LogFormatter(verbose=verbose, datefmt="%H:%M:%S"))
            stderr_handler.addFilter(ClassNameFilter())

            root.addHandler(stdout_handler)
            root.addHandler(stderr_handler)

            # Expose a base package logger; child loggers will propagate to ROOT.
            pkg_logger = logging.getLogger(cls._base_name)
            pkg_logger.setLevel(level)
            pkg_logger.propagate = True

            cls._configured = True
            return pkg_logger

    @classmethod
    def get_logger(cls, name: str | None = None) -> logging.Logger:
        base = logging.getLogger(cls._base_name)
        return base

    @classmethod
    def set_level(cls, level: int) -> None:
        logging.getLogger().setLevel(level)

    @staticmethod
    def decolorize(s: str) -> str:
        return ANSI_SGR_RE.sub('', s)

