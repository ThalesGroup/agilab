"""Bounded, incremental redaction for locally owned agent subprocesses."""

from __future__ import annotations

import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from typing import Callable

from agilab.security.secret_uri import redact_text

MAX_LOG_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024


def capture_command(
    command: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout: float,
    stdout_path: Path,
    stderr_path: Path,
    redact: bool = True,
    max_log_bytes: int = MAX_LOG_BYTES,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Capture bounded redacted prefixes without buffering the process output.

    Entire logical lines are redacted together. Oversized lines are omitted,
    so a secret split across read chunks cannot leak a suffix. Only this
    invocation's child/process group is signalled, while it is still owned.
    """
    if type(max_log_bytes) is not int or max_log_bytes < 1024:
        raise ValueError("max_log_bytes must be an integer >= 1024")
    stop = threading.Event()
    statistics: dict[str, dict[str, object]] = {}
    errors: list[BaseException] = []

    def drain(pipe, path: Path, name: str) -> None:
        observed = written = omitted_lines = 0
        pending = bytearray()
        skipping = False
        capped = False
        complete = False
        bearer_pending = False
        try:
            os.set_blocking(pipe.fileno(), False)
            with path.open("wb") as output:

                def emit(raw: bytes) -> None:
                    nonlocal written, capped, bearer_pending
                    text = raw.decode("utf-8", "replace")
                    if redact:
                        redacted = (
                            redact_text("Bearer " + text)[7:]
                            if bearer_pending
                            else redact_text(text)
                        )
                        bearer_pending = (bearer_pending and not text.strip()) or bool(
                            re.search(r"\bBearer\s*$", text, re.IGNORECASE)
                        )
                        data = redacted.encode("utf-8")
                    else:
                        data = text.encode("utf-8")
                    # Do not split a UTF-8 or redaction marker at the cap.
                    if written + len(data) <= max_log_bytes and not capped:
                        output.write(data)
                        written += len(data)
                    else:
                        capped = True

                while not stop.is_set():
                    try:
                        chunk = os.read(pipe.fileno(), 8192)
                    except BlockingIOError:
                        stop.wait(0.01)
                        continue
                    if not chunk:
                        complete = True
                        break
                    observed += len(chunk)
                    for piece in chunk.splitlines(keepends=True):
                        newline = piece.endswith((b"\n", b"\r"))
                        if not skipping:
                            pending.extend(piece)
                            if len(pending) > MAX_LINE_BYTES:
                                pending.clear()
                                skipping = True
                                omitted_lines += 1
                                emit(b"[AGILAB: oversized output line omitted]\n")
                                # A discarded line could end in a Bearer prefix.
                                bearer_pending = True
                        if newline:
                            if not skipping:
                                emit(bytes(pending))
                            pending.clear()
                            skipping = False
                if pending and not skipping:
                    # A stopped stream may end in half a secret: discard it.
                    if complete:
                        emit(bytes(pending))
                    else:
                        omitted_lines += 1
                output.flush()
                os.fsync(output.fileno())
        except BaseException as exc:
            errors.append(exc)
        finally:
            pipe.close()
            statistics[name] = {
                "observed_bytes": observed,
                "stored_bytes": written,
                "oversized_lines": omitted_lines,
                "limit_bytes": max_log_bytes,
                "truncated": capped or bool(omitted_lines) or not complete,
                "stream_complete": complete,
            }

    def terminate_owned(proc) -> None:
        if proc.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:  # Windows: the launched process; no claim about grandchildren.
            proc.kill()

    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    threads = [
        threading.Thread(target=drain, args=(proc.stdout, stdout_path, "stdout")),
        threading.Thread(target=drain, args=(proc.stderr, stderr_path, "stderr")),
    ]
    deadline = time.monotonic() + timeout
    reason = None
    try:
        for thread in threads:
            thread.start()
        while proc.poll() is None:
            if errors:
                raise errors[0]
            if cancelled is not None and cancelled():
                reason = "cancelled"
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            time.sleep(0.02)
    finally:
        terminate_owned(proc)
        proc.wait()
        # A descendant can keep inherited pipes open after the parent exits.
        # Stop readers cooperatively rather than blocking on those descendants.
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=max(0, min(0.5, deadline - time.monotonic())))
        if any(thread.is_alive() for thread in threads) and reason is None:
            reason = "timeout" if time.monotonic() >= deadline else "incomplete_output"
        stop.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join()
    if errors:
        raise errors[0]
    return {
        "returncode": (
            124
            if reason == "timeout"
            else 130
            if reason == "cancelled"
            else 125
            if reason
            else proc.returncode
        ),
        "process_returncode": proc.returncode,
        "termination": reason,
        "streams": statistics,
    }
