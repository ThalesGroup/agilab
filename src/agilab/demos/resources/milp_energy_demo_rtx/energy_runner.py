"""Parallel benchmark runner for the modular-unit-commitment MILP scenarios.

``run_benchmark`` solves a batch of scenarios twice so an independent validator
can compare a real serial run against a real parallel one:

* ``sequential`` - every scenario is solved, one at a time, in this process.
* ``parallel``   - the same scenarios are solved across ``workers`` real OS
  child processes (each with its own PID). The children are launched together
  and held at a ready barrier until every worker has finished importing; the
  parent then releases all assignments at once, so with ``workers >= 2`` at
  least two solves are genuinely in flight at the same time.

Every row records the worker PID together with monotonic start/stop timestamps
(``time.monotonic`` is system-wide, so the values are comparable across
processes) and the full :func:`energy_core.solve_scenario` result, which means
each row passes exactly the same physics checks as a single standalone solve.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

from energy_core import solve_scenario

# Child-process entry point. The parent launches
#   <venv python> -c "import energy_runner as _e; _e._worker_main()"
# with the project directory as the working directory (and injected into
# ``sys.path``), so the worker can import ``energy_core`` just like the parent.
_WORKER_BOOT = "import energy_runner as _e; _e._worker_main()"


def _worker_main() -> int:
    """Solve the assigned scenarios in this child process and report rows.

    Handshake: the worker prints a single ``READY`` line and flushes once its
    imports are done, then blocks reading the assignment payload from stdin.
    The parent only sends payloads after *every* worker is ready, which is what
    makes the solves start (and therefore overlap) at the same instant.
    """
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    payload = json.loads(sys.stdin.read())
    rows = []
    for case, settings in payload["assignments"]:
        start = time.monotonic()
        result = solve_scenario(settings)
        end = time.monotonic()
        rows.append(
            {
                "case": int(case),
                "pid": os.getpid(),
                "start_monotonic": start,
                "end_monotonic": end,
                "result": result,
            }
        )
    json.dump({"rows": rows}, sys.stdout, allow_nan=False)
    sys.stdout.flush()
    return 0


def _solve_sequential(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Solve ``batch`` one scenario at a time in the current process."""
    wall_start = time.monotonic()
    rows = []
    for case, settings in enumerate(batch):
        start = time.monotonic()
        result = solve_scenario(settings)
        end = time.monotonic()
        rows.append(
            {
                "case": case,
                "pid": os.getpid(),
                "start_monotonic": start,
                "end_monotonic": end,
                "result": result,
            }
        )
    wall_seconds = time.monotonic() - wall_start
    engine_seconds = sum(
        row["end_monotonic"] - row["start_monotonic"] for row in rows
    )
    return {
        "batch": list(batch),
        "rows": rows,
        "wall_seconds": wall_seconds,
        "engine_seconds": engine_seconds,
    }


def _solve_parallel(
    batch: list[dict[str, Any]], workers: int
) -> dict[str, Any]:
    """Solve ``batch`` across ``workers`` real child processes."""
    workers = max(1, int(workers))
    project_dir = os.path.dirname(os.path.abspath(__file__))

    # Interleave the scenarios across workers (case % workers) so the demand
    # multipliers are spread evenly and every worker has real work to do.
    chunks: list[list[list[Any]]] = [[] for _ in range(workers)]
    for case, settings in enumerate(batch):
        chunks[case % workers].append([case, settings])

    env = dict(os.environ)
    env["PYTHONPATH"] = (
        project_dir + os.pathsep + env["PYTHONPATH"]
        if env.get("PYTHONPATH")
        else project_dir
    )

    wall_start = time.monotonic()

    # Launch every child first so they all begin importing at the same instant.
    # Only stderr is drained in a thread (its log volume can exceed the pipe
    # buffer); stdout is read directly by the parent because the worker's
    # output - one READY line plus a small JSON payload - is far below the
    # buffer limit, so it can never block.
    handles: list[tuple[subprocess.Popen, list[list[Any]], list[bytes]]] = []
    for chunk in chunks:
        if not chunk:
            continue
        proc = subprocess.Popen(
            [sys.executable, "-c", _WORKER_BOOT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_dir,
            env=env,
        )
        stderr_chunks: list[bytes] = []

        def _drain_stderr(stream=proc.stderr, sink=stderr_chunks) -> None:
            for line in iter(stream.readline, b""):
                sink.append(line)
            stream.close()

        threading.Thread(target=_drain_stderr, daemon=True).start()
        handles.append((proc, chunk, stderr_chunks))

    # Ready barrier: wait until every worker has finished importing. Each
    # worker has already written its READY line (small, buffered) and is now
    # blocked on stdin, so reading the line cannot deadlock.
    for proc, chunk, _ in handles:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        if b"READY" not in line:
            proc.kill()
            raise RuntimeError(
                f"worker process {proc.pid} did not signal readiness"
            )

    # Release all assignments at once so every worker starts solving now.
    for proc, chunk, _ in handles:
        assert proc.stdin is not None
        proc.stdin.write(
            json.dumps({"assignments": chunk}, allow_nan=False).encode("utf-8")
        )
        proc.stdin.flush()
        proc.stdin.close()

    rows: list[dict[str, Any]] = []
    for proc, chunk, stderr_chunks in handles:
        assert proc.stdout is not None
        # The worker's stdout (READY line already consumed + small JSON) is far
        # below the pipe buffer, so read() cannot block; stderr is drained by
        # its own thread, so no pipe can fill and deadlock the worker.
        stdout = proc.stdout.read()
        proc.stdout.close()
        proc.wait(timeout=900)
        if proc.returncode != 0:
            stderr_text = b"".join(stderr_chunks).decode("utf-8", "replace")
            raise RuntimeError(
                f"worker process {proc.pid} exited with {proc.returncode}: "
                f"{stderr_text.strip()[:2000]}"
            )
        body = [
            line for line in stdout.splitlines() if line.strip() != b"READY"
        ]
        try:
            decoded = json.loads(b"".join(body).decode("utf-8"))
            rows.extend(decoded["rows"])
        except Exception as exc:
            raise RuntimeError(
                f"could not parse output of worker process {proc.pid}: {exc}"
            ) from exc
    rows.sort(key=lambda row: row["case"])
    wall_seconds = time.monotonic() - wall_start
    engine_seconds = sum(
        row["end_monotonic"] - row["start_monotonic"] for row in rows
    )
    return {
        "batch": list(batch),
        "rows": rows,
        "wall_seconds": wall_seconds,
        "engine_seconds": engine_seconds,
    }


def _results_match(
    sequential: dict[str, Any], parallel: dict[str, Any]
) -> bool:
    """True if both runs produced identical per-case solver outcomes."""
    if len(sequential["rows"]) != len(parallel["rows"]):
        return False
    seq_by_case = {row["case"]: row["result"] for row in sequential["rows"]}
    par_by_case = {row["case"]: row["result"] for row in parallel["rows"]}
    if set(seq_by_case) != set(par_by_case):
        return False
    for case in seq_by_case:
        if seq_by_case[case] != par_by_case[case]:
            return False
    return True


def run_benchmark(
    batch: list[dict[str, Any]], workers: int
) -> dict[str, Any]:
    """Solve ``batch`` serially and in parallel; return a comparable report.

    The returned mapping has ``sequential``, ``parallel`` and ``comparison``
    blocks. ``sequential``/``parallel`` each carry the shared ``batch``, one
    row per scenario (``case``, ``pid``, ``start_monotonic``,
    ``end_monotonic``, ``result``), and positive ``wall_seconds`` /
    ``engine_seconds``. ``comparison["matches"]`` is true when the serial and
    parallel runs produced identical per-case results.
    """
    sequential = _solve_sequential(batch)
    parallel = _solve_parallel(batch, workers)
    comparison = {
        "matches": _results_match(sequential, parallel),
        "sequential_wall_seconds": sequential["wall_seconds"],
        "parallel_wall_seconds": parallel["wall_seconds"],
    }
    return {
        "sequential": sequential,
        "parallel": parallel,
        "comparison": comparison,
    }
