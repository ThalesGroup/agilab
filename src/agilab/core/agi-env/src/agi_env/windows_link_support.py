"""Windows link and privilege helpers used by AGILAB environment setup."""

from __future__ import annotations

import ctypes as _ctypes
import subprocess
from ctypes import wintypes as _wintypes
from pathlib import Path


def has_admin_rights(*, ctypes_module=_ctypes):
    """Return whether the current Windows process has administrative rights."""

    try:
        return ctypes_module.windll.shell32.IsUserAnAdmin()
    except (AttributeError, OSError, RuntimeError):
        return False


def create_junction_windows(
    source: Path,
    dest: Path,
    *,
    logger=None,
    check_call=subprocess.check_call,
) -> bool:
    """Create a directory junction on Windows without requiring admin rights."""

    try:
        check_call(["cmd", "/c", "mklink", "/J", str(dest), str(source)])
        if logger:
            logger.info(f"Created junction: {dest} -> {source}")
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        if logger:
            logger.error(f"Failed to create junction. Error: {exc}")
        return False


def create_symlink_windows(
    source: Path,
    dest: Path,
    *,
    has_admin_rights_fn,
    logger=None,
    ctypes_module=_ctypes,
    wintypes_module=_wintypes,
) -> None:
    """Create a Windows directory symbolic link when privileges allow it."""

    create_symbolic_link = ctypes_module.windll.kernel32.CreateSymbolicLinkW
    create_symbolic_link.restype = wintypes_module.BOOL
    create_symbolic_link.argtypes = [
        wintypes_module.LPCWSTR,
        wintypes_module.LPCWSTR,
        wintypes_module.DWORD,
    ]

    symbolic_link_flag_directory = 0x1

    if not has_admin_rights_fn():
        if logger:
            logger.info(
                "Creating symbolic links on Windows requires administrative privileges or Developer Mode enabled."
            )
        return

    success = create_symbolic_link(str(dest), str(source), symbolic_link_flag_directory)
    if success:
        if logger:
            logger.info(f"Created symbolic link for .venv: {dest} -> {source}")
    else:
        error_code = ctypes_module.GetLastError()
        if logger:
            logger.info(
                f"Failed to create symbolic link for .venv. Error code: {error_code}"
            )
