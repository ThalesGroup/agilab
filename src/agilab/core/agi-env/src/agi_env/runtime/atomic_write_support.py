"""Atomic local file-write helpers."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import BinaryIO, Callable, TypeVar


_T = TypeVar("_T")
_WINDOWS_FILE_SHARING_RETRY_TIMEOUT_SECONDS = 0.5
_WINDOWS_FILE_SHARING_RETRY_INTERVAL_SECONDS = 0.01
FILE_LOCK_TIMEOUT_SECONDS = 5.0
FILE_LOCK_RETRY_INTERVAL_SECONDS = 0.05


def _is_windows() -> bool:
    return os.name == "nt"


def run_with_windows_file_sharing_retry(
    operation: Callable[[], _T],
    *,
    timeout_seconds: float = _WINDOWS_FILE_SHARING_RETRY_TIMEOUT_SECONDS,
    retry_interval_seconds: float = _WINDOWS_FILE_SHARING_RETRY_INTERVAL_SECONDS,
) -> _T:
    """Run a file operation through Windows' transient sharing-denial window.

    Replacing a file on Windows can briefly make the destination reject new opens,
    while an external reader can likewise make ``os.replace`` reject publication.
    Retry only that platform-specific ``PermissionError`` for a bounded interval;
    all other failures retain their original behavior.
    """

    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    if retry_interval_seconds <= 0:
        raise ValueError("retry_interval_seconds must be positive")

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return operation()
        except PermissionError:
            if not _is_windows():
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(retry_interval_seconds, remaining))


def acquire_bounded_file_lock(
    handle: BinaryIO,
    lock_path: Path,
    *,
    timeout_seconds: float = FILE_LOCK_TIMEOUT_SECONDS,
    retry_interval_seconds: float = FILE_LOCK_RETRY_INTERVAL_SECONDS,
) -> None:
    """Acquire an advisory file lock without allowing a session to hang forever."""

    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    if retry_interval_seconds <= 0:
        raise ValueError("retry_interval_seconds must be positive")

    if _is_windows():  # pragma: no cover - exercised on Windows CI
        import msvcrt

        if lock_path.stat().st_size == 0:
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())

        def _try_lock() -> None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    else:
        import fcntl

        def _try_lock() -> None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            _try_lock()
            return
        except OSError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out waiting for AGILAB file lock {lock_path}. "
                    "Another session may still be updating this file; retry after it finishes."
                ) from exc
            time.sleep(min(retry_interval_seconds, remaining))


def release_file_lock(handle: BinaryIO) -> None:
    """Release a lock acquired by :func:`acquire_bounded_file_lock`."""

    if _is_windows():  # pragma: no cover - exercised on Windows CI
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_bytes(
    path: str | Path,
    write_fn: Callable[[BinaryIO], None],
) -> None:
    """Write ``path`` via a same-directory temp file and ``os.replace``."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            write_fn(handle)
            handle.flush()
            os.fsync(handle.fileno())
        run_with_windows_file_sharing_retry(lambda: os.replace(tmp_path, output_path))
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically write text to ``path``."""

    atomic_write_bytes(path, lambda handle: handle.write(text.encode(encoding)))
