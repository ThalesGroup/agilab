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
RECORD_FILENAME_FALLBACK_EXCEPTIONS = (OSError, TypeError, ValueError)


def _record_filename(record: logging.LogRecord) -> str:
    try:
        return os.path.basename(getattr(record, "pathname", "")) or f"{record.module}.py"
    except RECORD_FILENAME_FALLBACK_EXCEPTIONS:
        return f"{getattr(record, 'module', '<?>')}.py"


def _is_build_noise_record(record: logging.LogRecord) -> bool:
    filename = _record_filename(record)
    pathname = getattr(record, "pathname", "")
    return (
        filename == "build.py"
        or "setuptools" in pathname
        or "distutils" in pathname
    )


def _is_same_log_record_file(
    frame_path: str,
    record_path: str,
    *,
    samefile_fn=os.path.samefile,
    basename_fn=os.path.basename,
) -> bool:
    if frame_path == record_path:
        return True

    try:
        if samefile_fn(frame_path, record_path):
            return True
    except OSError:
        pass

    return basename_fn(frame_path) == basename_fn(record_path)


def _resolve_record_classname(record: logging.LogRecord) -> str:
    try:
        record_path = os.path.normcase(os.path.realpath(record.pathname))
        frame = sys._getframe(0)
        while frame:
            code = frame.f_code
            frame_path = os.path.normcase(os.path.realpath(code.co_filename))
            if _is_same_log_record_file(frame_path, record_path) and code.co_name == record.funcName:
                if 'self' in frame.f_locals:
                    return frame.f_locals['self'].__class__.__name__
                return record.module or record.pathname
            frame = frame.f_back
    except Exception:
        return '<no-class>'
    return '<no-class>'


def _render_log_message(record: logging.LogRecord) -> str:
    try:
        return record.getMessage()
    except RecursionError:
        msg_obj = getattr(record, "msg", None)
        return f"<log-message-recursion type={type(msg_obj).__name__}>"
    except Exception as exc:  # pragma: no cover - defensive formatting guard
        msg_obj = getattr(record, "msg", None)
        return f"<log-message-format-error type={type(msg_obj).__name__} error={exc}>"


def _render_venv_label(prefix: str, *, os_name: str) -> str:
    if not prefix:
        return COLORS["classname"] + "<unknown>" + RESET
    parts = prefix.split("\\") if os_name == "nt" else prefix.split("/")
    return parts[-2] if len(parts) >= 2 else prefix


def _render_record_origin(record: logging.LogRecord) -> str:
    class_name = getattr(record, "classname", record.name)
    function_name = getattr(record, "funcName", record.funcName)
    if _is_build_noise_record(record):
        return "build.py" + RESET
    return class_name + "." + function_name + RESET


def _build_stream_handler(
    stream,
    *,
    level: int,
    verbose: int,
    add_max_level_filter: bool = False,
) -> logging.StreamHandler:
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    handler.setFormatter(LogFormatter(verbose=verbose, datefmt="%H:%M:%S"))
    handler.addFilter(ClassNameFilter())
    handler.addFilter(BuildNoiseFilter(verbose=verbose))
    if add_max_level_filter:
        handler.addFilter(MaxLevelFilter(logging.WARNING))
    return handler

class ClassNameFilter(logging.Filter):
    """Inject the originating class name into log records when available."""

    def filter(self, record):
        record.classname = _resolve_record_classname(record)
        return True

class MaxLevelFilter(logging.Filter):
    """Filter out records whose severity exceeds ``max_level``."""

    def __init__(self, max_level):
        self.max_level = max_level

    def filter(self, record):
        return record.levelno <= self.max_level


class BuildNoiseFilter(logging.Filter):
    """Drop build-tool records entirely when running in quiet mode."""

    def __init__(self, verbose: int = 0):
        self.verbose = verbose

    def filter(self, record):
        return self.verbose >= 2 or not _is_build_noise_record(record)

class LogFormatter(logging.Formatter):
    """Formatter that adds colours and collapses build-tool noise when quiet."""

    def __init__(self, *args, verbose=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbose = verbose

    def format(self, record):
        level_color = COLORS["level"].get(record.levelname, "")
        levelname = level_color

        venv_str = _render_venv_label(sys.prefix, os_name=os.name)
        functionName_str = _render_record_origin(record)
        message = COLORS["msg"] + _render_log_message(record) + RESET
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

            stdout_handler = _build_stream_handler(
                sys.stdout,
                level=logging.INFO,
                verbose=verbose,
                add_max_level_filter=True,
            )
            stderr_handler = _build_stream_handler(
                sys.stderr,
                level=logging.ERROR,
                verbose=verbose,
            )

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
