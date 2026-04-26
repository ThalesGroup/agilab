"""Pure path, environment, and subprocess helper functions for AGILAB.

This module intentionally avoids any GUI or AGILab singleton dependencies so it
can be reused from shared core, installers, and focused tests.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping, MutableMapping, Sequence

try:
    from pathlib import UnsupportedOperation
except ImportError:
    from io import UnsupportedOperation


LEVEL_RES = [
    re.compile(r"^\s*(?:\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+)?(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b", re.IGNORECASE),
    re.compile(r"^\s*\[\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\]\b", re.IGNORECASE),
    re.compile(r"\blevel\s*=\s*(debug|info|warning|error|critical)\b", re.IGNORECASE),
]
TIME_LEVEL_PREFIX = re.compile(
    r"^\s*(?:\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*[:-]?\s*",
    re.IGNORECASE,
)
INLINE_PATH_EXPORT = re.compile(
    r'^\s*export\s+PATH=(?P<quote>["\']?)(?P<value>.+?)(?P=quote);?(?P<rest>.*)$',
    re.DOTALL,
)
PATH_RESOLVE_EXCEPTIONS = (OSError, UnsupportedOperation)
REGEX_OPERATION_EXCEPTIONS = (re.error, TypeError, ValueError)
INLINE_EXPORT_EXCEPTIONS = (OSError, TypeError, ValueError)
_HOST_PATH_CLS = type(Path("."))


def normalize_path(path):
    """Return ``path`` coerced to a normalised string representation."""

    raw_path = "." if str(path) == "" else str(path)
    if os.name == "nt":
        try:
            candidate = _HOST_PATH_CLS(raw_path).expanduser().resolve(strict=False)
        except PATH_RESOLVE_EXCEPTIONS:
            candidate = _HOST_PATH_CLS(raw_path).expanduser()
        return str(PureWindowsPath(candidate))
    candidate = Path(raw_path)
    return str(PurePosixPath(candidate))


def fix_windows_drive(path_str: str) -> str:
    """Ensure Windows drive paths include a separator after the colon."""

    if os.name != "nt" or not isinstance(path_str, str):
        return path_str
    try:
        if re.match(r"^[A-Za-z]:(?![\\/])", path_str):
            return path_str[:2] + "\\" + path_str[2:]
    except REGEX_OPERATION_EXCEPTIONS:
        pass
    return path_str


def parse_level(line, default_level):
    """Resolve a logging level token found in ``line``."""

    for rx in LEVEL_RES:
        match = rx.search(line)
        if match:
            import logging

            return getattr(logging, match.group(1).upper(), default_level)
    return default_level


def strip_time_level_prefix(line: str) -> str:
    """Remove a ``HH:MM:SS LEVEL`` prefix commonly emitted by log handlers."""

    return TIME_LEVEL_PREFIX.sub("", line, count=1)


def is_packaging_cmd(cmd: str) -> bool:
    """Return ``True`` when ``cmd`` appears to invoke ``uv`` or ``pip``."""

    text = cmd.strip()
    return text.startswith("uv ") or text.startswith("pip ") or "uv" in text or "pip" in text


def build_subprocess_env(
    *,
    base_env: Mapping[str, str] | None = None,
    venv=None,
    pythonpath_entries: Sequence[str] | None = None,
    sys_prefix: str | Path | None = None,
) -> dict[str, str]:
    """Build an isolated subprocess environment for a target virtualenv."""

    process_env = dict(base_env or os.environ)
    process_env.pop("UV_RUN_RECURSION_DEPTH", None)

    venv_path = None
    if venv is not None:
        venv_path = Path(venv)
        if not (venv_path / "bin").exists() and venv_path.name != ".venv":
            venv_path = venv_path / ".venv"
        process_env["VIRTUAL_ENV"] = str(venv_path)
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        venv_bin = venv_path / bin_dir
        process_env["PATH"] = str(venv_bin) + os.pathsep + process_env.get("PATH", "")

    extra_paths = list(pythonpath_entries or [])
    active_prefix = Path(sys_prefix or sys.prefix).resolve()
    if venv_path and active_prefix != venv_path.resolve():
        extra_paths = []

    process_env.pop("PYTHONPATH", None)
    process_env.pop("PYTHONHOME", None)
    if extra_paths:
        process_env["PYTHONPATH"] = os.pathsep.join(extra_paths)
    return process_env


def inject_uv_preview_flag(cmd: str | None) -> str | None:
    """Inject the uv preview flag used across AGILAB subprocess calls."""

    if not isinstance(cmd, str) or "uv" not in cmd or "--preview-features" in cmd:
        return cmd
    try:
        return re.sub(
            r"(^|\s)uv(\s+)",
            r"\1uv --preview-features extra-build-dependencies \2",
            cmd,
            count=1,
        )
    except REGEX_OPERATION_EXCEPTIONS:
        return cmd


def apply_inline_path_export(cmd: str | None, process_env: MutableMapping[str, str]) -> str | None:
    """Apply a leading ``export PATH=...`` fragment directly into ``process_env``."""

    if not isinstance(cmd, str):
        return cmd

    match = INLINE_PATH_EXPORT.match(cmd)
    if not match:
        return cmd

    try:
        raw_value = os.path.expanduser(match.group("value").strip())
        current_path = process_env.get("PATH") or os.environ.get("PATH") or ""
        new_path = raw_value.replace("${PATH}", current_path).replace("$PATH", current_path)
        process_env["PATH"] = new_path
        rest = (match.group("rest") or "").lstrip(" ;")
        return rest or None
    except INLINE_EXPORT_EXCEPTIONS:
        return cmd


def last_non_empty_output_line(lines: Iterable[str | None] | None) -> str | None:
    """Return the last non-empty text line from ``lines``."""

    for line in reversed(list(lines or [])):
        if isinstance(line, str) and line.strip():
            return line.strip()
    return None


def command_failure_hint(cmd: str, lines: Iterable[str] | None = None) -> str | None:
    """Return a diagnostic hint for common dependency-install failures."""

    if "pip install" not in cmd:
        return None
    blob = "\n".join(lines or []).lower()
    network_markers = (
        "failed to establish a new connection",
        "temporary failure in name resolution",
        "nodename nor servname provided",
        "no route to host",
    )
    if any(marker in blob for marker in network_markers):
        return (
            "pip could not reach the package index (network access is required to "
            "install build dependencies such as hatchling). Pre-install those "
            "dependencies locally or enable outbound connectivity, then rerun."
        )
    return None


def format_command_failure_message(
    returncode: int,
    cmd: str,
    lines: Iterable[str | None] | None = None,
    diagnostic_hint: str | None = None,
) -> str:
    """Format a concise subprocess failure message from collected output."""

    detail = last_non_empty_output_line(lines)
    if detail:
        simplified = re.sub(r"^(?:[\w.]*?(?:Error|Exception)):\s*", "", detail)
        detail = simplified or detail
        message = f"Command failed with exit code {returncode}: {detail}"
    else:
        message = f"Command failed with exit code {returncode}: {cmd}"
    if diagnostic_hint:
        message = f"{message}\n{diagnostic_hint}"
    return message
