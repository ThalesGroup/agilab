"""Atomic local file-write helpers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import BinaryIO, Callable


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
        os.replace(tmp_path, output_path)
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
