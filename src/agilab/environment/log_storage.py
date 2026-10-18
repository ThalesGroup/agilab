"""Streaming gzip storage for human-readable AGILAB logs.

Writers keep the full log; UI and developer summaries can read bounded views.
Only live readers opt in to accepting an unfinished final gzip stream.
"""

from __future__ import annotations

import codecs
import gzip
import io
import threading
import zlib
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

LOG_COMPRESSION_LEVEL = 1
LOG_CHUNK_BYTES = 64 * 1024
_APPEND_LOCK = threading.Lock()


def is_compressed_log(path: Path) -> bool:
    return path.name.lower().endswith(".log.gz")


def open_log(path: Path, mode: str = "rt") -> TextIO:
    """Open a UTF-8 log, retaining plaintext compatibility for existing paths."""
    if is_compressed_log(path):
        return gzip.open(
            path,
            mode,
            encoding="utf-8",
            errors="replace",
            compresslevel=LOG_COMPRESSION_LEVEL,
        )
    return path.open(mode, encoding="utf-8", errors="replace")


def append_log_text(path: Path, text: str) -> None:
    """Serialize callbacks and finish each append, including its gzip trailer."""
    with _APPEND_LOCK:
        if is_compressed_log(path):
            with path.open("ab") as raw:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=raw,
                    compresslevel=LOG_COMPRESSION_LEVEL,
                ) as stream:
                    stream.write(text.encode("utf-8", errors="replace"))
        else:
            with open_log(path, "at") as stream:
                stream.write(text)


def iter_log_bytes(path: Path, *, allow_incomplete: bool = False) -> Iterator[bytes]:
    """Read bounded chunks; CRC/format errors always propagate.

    A flushed writer has published data before writing its final gzip trailer.
    Live views may stop at that unfinished tail. Strict readers require a
    complete archive, including its checksum.
    """
    opener = gzip.open if is_compressed_log(path) else Path.open
    with opener(path, "rb") as stream:
        while True:
            try:
                chunk = stream.read1(LOG_CHUNK_BYTES)
            except gzip.BadGzipFile as exc:
                # CPython treats a one-byte gzip magic prefix as bad format.
                # Only a live view accepts that exact unfinished-header case.
                if allow_incomplete and exc.args == (
                    f"Not a gzipped file ({bytes([0x1F])!r})",
                ):
                    return
                raise
            except zlib.error as exc:
                raise gzip.BadGzipFile(f"Invalid compressed log: {exc}") from exc
            except EOFError:
                if allow_incomplete:
                    return
                raise
            if not chunk:
                return
            yield chunk


def _text_chunks(path: Path, *, allow_incomplete: bool) -> Iterator[str]:
    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder("utf-8")("replace"),
        translate=True,
    )
    for chunk in iter_log_bytes(path, allow_incomplete=allow_incomplete):
        yield decoder.decode(chunk)
    yield decoder.decode(b"", final=True)


def read_log_text(path: Path, *, allow_incomplete: bool = False) -> str:
    return "".join(_text_chunks(path, allow_incomplete=allow_incomplete))


def iter_log_lines(
    path: Path,
    *,
    allow_incomplete: bool = False,
    max_line_chars: int | None = None,
) -> Iterator[str]:
    """Stream lines, optionally bounding each rendered line, never the archive."""
    if max_line_chars is not None and max_line_chars <= 0:
        raise ValueError("max_line_chars must be positive")
    pending = ""
    clipped = False
    for chunk in _text_chunks(path, allow_incomplete=allow_incomplete):
        for part in chunk.splitlines(keepends=True):
            body = part.rstrip("\r\n")
            if max_line_chars is None:
                pending += body
            else:
                remaining = max(max_line_chars - len(pending), 0)
                pending += body[:remaining]
                clipped |= len(body) > remaining
            if part.endswith(("\n", "\r")):
                yield pending + (
                    " ... [line clipped; full content in log]" if clipped else ""
                )
                pending = ""
                clipped = False
    if pending or clipped:
        yield pending + (" ... [line clipped; full content in log]" if clipped else "")


def tail_log_lines(path: Path, *, max_lines: int = 200) -> list[str]:
    if max_lines <= 0:
        return []
    return list(
        deque(
            iter_log_lines(path, allow_incomplete=True, max_line_chars=4096),
            maxlen=max_lines,
        )
    )


def log_tail_bytes(path: Path, *, max_bytes: int) -> tuple[str, bool]:
    """Bound decompressed preview memory, independently of compressed file size."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    tail = bytearray()
    total = 0
    for chunk in iter_log_bytes(path, allow_incomplete=True):
        total += len(chunk)
        tail.extend(chunk)
        if len(tail) > max_bytes:
            del tail[:-max_bytes]
    return tail.decode("utf-8", errors="replace"), total > max_bytes
