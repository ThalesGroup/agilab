"""Free-threading lab kernel.

Pure-stdlib Mandelbrot escape-count workload plus an adapter that drives the
included AGILAB pool engine (``agilab_pool.py``, an unchanged copy of the
AGILAB ``worker_pool_support`` module) for dispatch and reduction.

The measured work always runs in a separate free-threaded CPython process
selected by ``AGILAB_FREE_THREADING_PYTHON`` (default: ``shutil.which`` of
``python3.14t``). This module is both a library (imported by ``benchmark.py``,
``app.py`` and the tests) and a CLI (``python free_threading_core.py ...``)
that a benchmark child executes to perform one (mode, workers) benchmark case.

Source credit: adapted from the original AGILAB free-threading notebook,
created September 19, 2026 (AGILAB contributors, BSD-3-Clause). See the
Python free-threading docs:
https://docs.python.org/3.14/howto/free-threading-python.html
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import threading
import time

import agilab_pool

APP_TITLE = "Free-threading lab"
SOURCE_CREDIT = (
    "Adapted from the original AGILAB free-threading notebook, created "
    "September 19, 2026 (AGILAB contributors, BSD-3-Clause; see LICENSE). "
    "Free-threading background: "
    "https://docs.python.org/3.14/howto/free-threading-python.html"
)
FREE_THREADING_DOCS = "https://docs.python.org/3.14/howto/free-threading-python.html"
FREE_THREADING_PYTHON_ENV = "AGILAB_FREE_THREADING_PYTHON"

MAX_WIDTH = 384
MAX_HEIGHT = 256
MAX_ITERATIONS = 300
MAX_WORKERS = 8
MIN_REPEATS = 1
MAX_REPEATS = 3
DEFAULT_WIDTH = 192
DEFAULT_HEIGHT = 128
DEFAULT_ITERATIONS = 160
DEFAULT_REPEATS = 2
TILE_ROWS_MIN = 2
TILE_ROWS_MAX = 4

MODE_GIL_ON_THREADS = "gil-on-threads"
MODE_GIL_OFF_THREADS = "gil-off-threads"
MODE_GIL_ON_PROCESSES = "gil-on-processes"
MODES = (MODE_GIL_ON_THREADS, MODE_GIL_OFF_THREADS, MODE_GIL_ON_PROCESSES)

MODE_LABELS = {
    MODE_GIL_ON_THREADS: "GIL-on threads (same free-threaded build, -X gil=1, forced thread pool)",
    MODE_GIL_OFF_THREADS: "GIL-off threads (free-threaded build, -X gil=0, AGILAB auto backend)",
    MODE_GIL_ON_PROCESSES: "GIL-on processes (same free-threaded build, -X gil=1, forced spawn process pool)",
}

_SCRUBBED_ENV_PREFIXES = ("AGILAB_POOL_",)
_SCRUBBED_ENV_EXACT = ("PYTHON_GIL", "PYTHONPATH")


class FreeThreadingInterpreterError(RuntimeError):
    """Raised when no usable free-threaded interpreter is available."""


def _strict_int(name: str, value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
    if not (minimum <= value <= maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def _strict_float(name: str, value: object, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if not (minimum <= value <= maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def validate_params(
    width: object,
    height: object,
    iterations: object,
    workers: object,
    repeats: object = DEFAULT_REPEATS,
    tile_rows: object = TILE_ROWS_MAX,
    child_timeout: object = 60.0,
    total_timeout: object = 180.0,
) -> dict:
    """Strictly validate all user-controllable inputs before anything launches.

    Rejects bools, zero/negative values, NaN/inf and out-of-range values.
    """
    return {
        "width": _strict_int("width", width, minimum=1, maximum=MAX_WIDTH),
        "height": _strict_int("height", height, minimum=1, maximum=MAX_HEIGHT),
        "iterations": _strict_int("iterations", iterations, minimum=1, maximum=MAX_ITERATIONS),
        "workers": _strict_int("workers", workers, minimum=1, maximum=MAX_WORKERS),
        "repeats": _strict_int("repeats", repeats, minimum=MIN_REPEATS, maximum=MAX_REPEATS),
        "tile_rows": _strict_int(
            "tile_rows", tile_rows, minimum=TILE_ROWS_MIN, maximum=TILE_ROWS_MAX
        ),
        "child_timeout": _strict_float("child_timeout", child_timeout, minimum=1.0, maximum=600.0),
        "total_timeout": _strict_float("total_timeout", total_timeout, minimum=1.0, maximum=3600.0),
    }


def validate_mode(mode: object) -> str:
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}, got {mode!r}")
    return mode


def reference_image(width: int, height: int, iterations: int) -> list[int]:
    """Serial reference Mandelbrot escape counts (original notebook algorithm).

    Fixed bounds x in [-2, 1], y in [-1.2, 1.2]; row-major pixel order.
    """
    pixels = []
    for y in range(height):
        cy = -1.2 + 2.4 * y / (height - 1)
        for x in range(width):
            cx = -2.0 + 3.0 * x / (width - 1)
            z = 0j
            c = complex(cx, cy)
            count = 0
            while count < iterations and z.real * z.real + z.imag * z.imag <= 4.0:
                z = z * z + c
                count += 1
            pixels.append(count)
    return pixels


def _row_counts(width: int, height: int, y: int, iterations: int) -> list[int]:
    cy = -1.2 + 2.4 * y / (height - 1)
    row = []
    for x in range(width):
        cx = -2.0 + 3.0 * x / (width - 1)
        z = 0j
        c = complex(cx, cy)
        count = 0
        while count < iterations and z.real * z.real + z.imag * z.imag <= 4.0:
            z = z * z + c
            count += 1
        row.append(count)
    return row


def make_tiles(height: int, tile_rows: int) -> list[tuple[int, int]]:
    """Split the image into ``tile_rows`` contiguous row tiles (2-4)."""
    if not (TILE_ROWS_MIN <= tile_rows <= TILE_ROWS_MAX):
        raise ValueError(f"tile_rows must be between {TILE_ROWS_MIN} and {TILE_ROWS_MAX}")
    rows_per_tile = math.ceil(height / tile_rows)
    tiles = []
    for start in range(0, height, rows_per_tile):
        tiles.append((start, min(start + rows_per_tile, height)))
    return tiles


def interleave_tiles(tiles: list[tuple[int, int]], workers: int) -> list[list[tuple[int, int]]]:
    """Deterministic round-robin partition of tiles into ``workers`` buckets."""
    buckets: list[list[tuple[int, int]]] = [[] for _ in range(max(1, workers))]
    for position, tile in enumerate(tiles):
        buckets[position % max(1, workers)].append(tile)
    return buckets


def compute_tile(params: dict, tile: tuple[int, int]) -> dict:
    """Compute one row tile. No mutable shared state; returns a plain record.

    The GIL state is sampled inside the actual worker (right before and right
    after the timed tile work) so the per-task runtime_before/runtime_after
    observations are real measurements from the executor that ran the tile,
    not a copy of a coordinator-level probe.
    """
    width = params["width"]
    height = params["height"]
    iterations = params["iterations"]
    runtime_before = gil_state()
    start = time.monotonic()
    counts: list[int] = []
    for y in range(tile[0], tile[1]):
        counts.extend(_row_counts(width, height, y, iterations))
    end = time.monotonic()
    runtime_after = gil_state()
    return {
        "row_start": tile[0],
        "row_end": tile[1],
        "rows": tile[1] - tile[0],
        "counts": counts,
        "start": start,
        "end": end,
        "pid": os.getpid(),
        "thread": threading.get_ident(),
        "runtime_before": runtime_before,
        "runtime_after": runtime_after,
    }


def digest_of_counts(counts: list[int]) -> str:
    return hashlib.sha256(json.dumps(counts, separators=(",", ":")).encode("utf-8")).hexdigest()


def reduce_tiles(records: list[dict], width: int, height: int) -> dict:
    """Stitch tile records back into full row-major pixel order.

    Verifies every tile occurs exactly once and spans the whole image.
    """
    spans = sorted((rec["row_start"], rec["row_end"]) for rec in records)
    covered: list[int] = []
    for start, end in spans:
        covered.extend(range(start, end))
    if covered != list(range(height)):
        raise ValueError("tile records do not cover the image exactly once")
    if len(spans) != len(records):
        raise ValueError("duplicate tile records")
    pixels = [0] * (width * height)
    for rec in records:
        offset = rec["row_start"] * width
        chunk = rec["counts"]
        if len(chunk) != rec["rows"] * width:
            raise ValueError("tile count length mismatch")
        pixels[offset : offset + len(chunk)] = chunk
    return {"pixels": pixels, "digest": digest_of_counts(pixels)}


def _is_list(value) -> bool:
    return isinstance(value, list)


def _is_empty_list(value) -> bool:
    return len(value) == 0


def _concat_labeled(frames, labels):
    out = []
    for frame in frames:
        out.extend(frame)
    return out


def _empty_list():
    return []


def _spawn_process_executor_factory(max_workers, initializer, initargs):
    """Force the spawn start method (no fork) for the process pool."""
    import multiprocessing
    from concurrent.futures.process import ProcessPoolExecutor

    return ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=initializer,
        initargs=initargs,
        mp_context=multiprocessing.get_context("spawn"),
    )


def build_hooks(mode: str) -> agilab_pool.PoolFrameHooks:
    """Build the PoolFrameHooks for a mode.

    Thread modes use ``executor_kind='thread'``; the AGILAB engine's
    free-threading auto-switch (process families on a GIL-off build become a
    thread pool) is exercised by the GIL-off mode. Process mode forces the
    spawn process pool.
    """
    mode = validate_mode(mode)
    if mode == MODE_GIL_ON_PROCESSES:
        return agilab_pool.PoolFrameHooks(
            family="free-threading-lab",
            executor_kind="process",
            executor_factory=_spawn_process_executor_factory,
            is_frame=_is_list,
            is_empty=_is_empty_list,
            concat_labeled=_concat_labeled,
            empty_frame=_empty_list,
        )
    import concurrent.futures

    return agilab_pool.PoolFrameHooks(
        family="free-threading-lab",
        executor_kind="thread",
        executor_factory=concurrent.futures.ThreadPoolExecutor,
        is_frame=_is_list,
        is_empty=_is_empty_list,
        concat_labeled=_concat_labeled,
        empty_frame=_empty_list,
    )


class MandelbrotTileWorker:
    """Picklable module-level worker adapter for the AGILAB pool engine.

    Carries only plain data (dict params, tile list) so it pickles cleanly
    into spawn children. Threads never share mutable application state: each
    work item is an independent tile computed from immutable inputs, and only
    the parent process collects results.
    """

    def __init__(self, params: dict, tiles: list[tuple[int, int]], mode: str, workers: int):
        self.params = dict(params)
        self.tiles = list(tiles)
        self.mode = mode
        self.workers = workers
        self._worker_id = 0
        self._mode = 1  # AGILAB in-worker pool bit
        self._work_done_chunk = 0
        self.args = {"pool_max_workers": workers}
        self.pool_vars = {"mode": mode, "workers": workers}
        self.hooks = build_hooks(mode)
        self.tile_records: list[dict] = []
        self.engine_backend = None
        self.engine_width = None

    # -- engine protocol ---------------------------------------------------
    def work_init(self) -> None:
        self.tile_records = []

    def pool_init(self, pool_vars) -> None:
        self.pool_vars = dict(pool_vars) if isinstance(pool_vars, dict) else {}

    def work_pool(self, item) -> list:
        row_start, row_end = item
        return [compute_tile(self.params, (row_start, row_end))]

    def work_done(self, df) -> None:
        if df:
            self.tile_records.extend(df)

    def stop(self) -> None:
        pass

    def _exec_multi_process(self, workers_plan, workers_plan_metadata) -> None:
        """Pool path: delegate to the AGILAB engine's shared pool executor."""
        executor_factory, executor_kind = agilab_pool.resolve_executor(self.hooks)
        if executor_factory is None:
            import concurrent.futures

            executor_factory = concurrent.futures.ThreadPoolExecutor
        chunks = agilab_pool.select_worker_chunks(self, workers_plan)
        chunk_lengths = [len(chunk) for chunk in chunks]
        width = agilab_pool.resolve_pool_width(
            chunk_lengths, self.args, executor_kind=executor_kind
        )
        self.engine_backend = executor_kind
        self.engine_width = width
        agilab_pool.exec_multi_process(self, workers_plan, workers_plan_metadata, self.hooks)

    def _exec_mono_process(self, workers_plan, workers_plan_metadata) -> None:
        self.engine_backend = "mono"
        self.engine_width = 1
        agilab_pool.exec_mono_process(self, workers_plan, workers_plan_metadata, self.hooks)


def gil_state() -> dict:
    """Report the interpreter build and the actual GIL state right now."""
    checker = getattr(sys, "_is_gil_enabled", None)
    try:
        gil_enabled = bool(checker()) if callable(checker) else None
    except Exception:
        gil_enabled = None
    return {
        "py_gil_disabled_build": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "gil_enabled": gil_enabled,
        "version": sys.version.split()[0],
        "free_threaded_build": "free-threading" in sys.version,
        "executable": sys.executable,
    }


def build_plan(params: dict, workers: int) -> tuple[list[tuple[int, int]], list]:
    """Build the engine plan for one child process.

    The child runs a single dispatcher worker (``_worker_id=0``); the AGILAB
    pool executor fans the tile work items out across the pool width. Tiles
    are submitted in the deterministic round-robin interleave order so the
    same work is dispatched identically for every (mode, workers) case.
    """
    tiles = make_tiles(params["height"], params["tile_rows"])
    buckets = interleave_tiles(tiles, workers)
    ordered = [tile for bucket in buckets for tile in bucket]
    # Plan shape: workers_plan[worker_id] -> list of chunks; each chunk is a
    # list of work items (tiles) that work_pool() processes one by one.
    workers_plan = [[list(ordered)]]
    return tiles, workers_plan


def run_case(params: dict, mode: str, workers: int, repeats: int) -> dict:
    """Run one (mode, workers) case in-process: ``repeats`` engine runs.

    Each repeat reports the engine's own measured start/end bounds and wall
    duration (captured around ``run_works``), the real per-tile records
    (including the worker's own runtime_before/runtime_after GIL observations
    and the computed pixel counts), and the verified digest. Every repeat is
    measured as a real wall interval with its own monotonic clock reads;
    nothing is derived by dividing a grouped duration into fake repeats.
    """
    mode = validate_mode(mode)
    tiles, workers_plan = build_plan(params, workers)
    repeat_reports = []
    for repeat in range(repeats):
        worker = MandelbrotTileWorker(params, tiles, mode, workers)
        engine_start = time.monotonic()
        engine_time = agilab_pool.run_works(worker, workers_plan, None)
        engine_end = time.monotonic()
        wall_seconds = engine_end - engine_start
        reduced = reduce_tiles(worker.tile_records, params["width"], params["height"])
        repeat_reports.append(
            {
                "repeat": repeat,
                "engine_seconds": engine_time,
                "engine_wall_seconds": wall_seconds,
                "engine_start": engine_start,
                "engine_end": engine_end,
                "wall_seconds": wall_seconds,
                "digest": reduced["digest"],
                "pixels": reduced["pixels"],
                "tiles": [
                    {
                        "row_start": rec["row_start"],
                        "row_end": rec["row_end"],
                        "rows": rec["rows"],
                        "counts": rec["counts"],
                        "start": rec["start"],
                        "end": rec["end"],
                        "duration_seconds": rec["end"] - rec["start"],
                        "pid": rec["pid"],
                        "thread": rec["thread"],
                        "runtime_before": rec["runtime_before"],
                        "runtime_after": rec["runtime_after"],
                    }
                    for rec in worker.tile_records
                ],
                "engine_backend": worker.engine_backend,
                "engine_width": worker.engine_width,
            }
        )
    digests = {rep["digest"] for rep in repeat_reports}
    if len(digests) != 1:
        raise ValueError("digest mismatch across repeats")
    reference = reference_image(params["width"], params["height"], params["iterations"])
    same_as_serial = digests == {digest_of_counts(reference)}
    return {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "workers": workers,
        "tiles": [{"row_start": t[0], "row_end": t[1]} for t in tiles],
        "repeats": repeat_reports,
        "digest": next(iter(digests)),
        "same_as_serial_reference": same_as_serial,
    }


def effective_cpu_allowance() -> int:
    """Cap the worker count by affinity, cgroup quota, SPACE_CPU_CORES and
    os.cpu_count()/os.process_cpu_count(), at most MAX_WORKERS."""
    candidates = []
    try:
        candidates.append(len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    try:
        raw = open("/sys/fs/cgroup/cpu.max").read().strip().split()
        if raw and raw[0] != "max":
            candidates.append(max(1, math.floor(int(raw[0]) / int(raw[1]))))
    except (OSError, ValueError, IndexError):
        pass
    try:
        quota = int(open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read().strip())
        if quota > 0:
            period = int(open("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read().strip())
            candidates.append(max(1, quota // period))
    except (OSError, ValueError):
        pass
    space_cores = os.environ.get("SPACE_CPU_CORES", "").strip()
    if space_cores.isdigit() and int(space_cores) > 0:
        candidates.append(int(space_cores))
    for counter in (getattr(os, "process_cpu_count", None), os.cpu_count):
        try:
            value = counter() if callable(counter) else None
        except (AttributeError, OSError):
            value = None
        if value:
            candidates.append(int(value))
    if not candidates:
        return 1
    return max(1, min(min(candidates), MAX_WORKERS))


def child_env(mode: str) -> dict:
    """Private child environment: scrub inherited GIL/pool knobs, then set
    exactly the mode flags needed. The UI never mutates the global env."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_SCRUBBED_ENV_PREFIXES) and k not in _SCRUBBED_ENV_EXACT
    }
    env["PYTHONHASHSEED"] = "0"
    env["PYTHON_GIL"] = "0" if mode == MODE_GIL_OFF_THREADS else "1"
    return env


def child_argv(
    free_threading_python: str, params: dict, mode: str, workers: int, repeats: int
) -> list:
    gil_flag = "0" if mode == MODE_GIL_OFF_THREADS else "1"
    return [
        free_threading_python,
        "-X",
        f"gil={gil_flag}",
        "-m",
        "free_threading_core",
        "--mode", mode,
        "--width", str(params["width"]),
        "--height", str(params["height"]),
        "--iterations", str(params["iterations"]),
        "--workers", str(workers),
        "--repeats", str(repeats),
        "--tile-rows", str(params["tile_rows"]),
    ]


def probe_free_threading_python(candidate: str) -> dict:
    """Verify a candidate interpreter is a real free-threaded build."""
    probe = (
        "import json,sys,sysconfig;"
        "print(json.dumps({'ok':True,"
        "'py_gil_disabled_build':bool(sysconfig.get_config_var('Py_GIL_DISABLED')),"
        "'gil_enabled':(sys._is_gil_enabled() if hasattr(sys,'_is_gil_enabled') else None),"
        "'version':sys.version.split()[0],"
        "'free_threaded_build':'free-threading' in sys.version,"
        "'executable':sys.executable}))"
    )
    completed = subprocess.run(
        [candidate, "-c", probe],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise FreeThreadingInterpreterError(
            f"Free-threaded interpreter failed to run: {candidate!r}: "
            f"{completed.stderr.strip()[:300]}"
        )
    info = json.loads(completed.stdout.strip().splitlines()[-1])
    if not info.get("ok") or not info.get("free_threaded_build"):
        raise FreeThreadingInterpreterError(
            f"Interpreter {candidate!r} is not a free-threaded build "
            f"(version: {info.get('version')!r}). Install a free-threaded CPython "
            f"(e.g. python3.14t) or point {FREE_THREADING_PYTHON_ENV} at one. "
            "This app never falls back to ordinary Python."
        )
    return info


def resolve_free_threading_python() -> tuple[str, dict]:
    """Locate and validate the free-threaded interpreter.

    Order: $AGILAB_FREE_THREADING_PYTHON, then shutil.which('python3.14t').
    A missing or non-free-threaded interpreter is an actionable error;
    timings are never simulated and never run on ordinary Python.
    """
    candidate = os.environ.get(FREE_THREADING_PYTHON_ENV, "").strip()
    if not candidate:
        candidate = shutil.which("python3.14t") or ""
    if not candidate:
        raise FreeThreadingInterpreterError(
            f"No free-threaded Python found. Set {FREE_THREADING_PYTHON_ENV} to a "
            "free-threaded CPython (python3.14t) executable. This app refuses to "
            "simulate timings or silently switch to ordinary Python."
        )
    if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
        raise FreeThreadingInterpreterError(
            f"{FREE_THREADING_PYTHON_ENV} points at {candidate!r}, which is not an "
            "executable file. Point it at a free-threaded CPython (python3.14t)."
        )
    return candidate, probe_free_threading_python(candidate)


def render_preview_png(pixels: list[int], width: int, height: int, iterations: int) -> bytes:
    """Deterministic PNG of the escape-count field (stdlib zlib/struct only).

    Colour: log-scale escape shading, black for full-iteration (interior)
    pixels. Pure function of (pixels, width, height, iterations).
    """
    import struct
    import zlib

    norm = math.log10(float(iterations + 1))
    table = []
    for count in range(iterations + 1):
        if count >= iterations:
            table.append((8, 10, 14))
        else:
            t = math.log10(count + 1) / norm
            r = int(255 * (0.08 + 0.92 * t) ** 1.6)
            g = int(255 * (0.10 + 0.85 * t) ** 2.2)
            b = int(255 * (0.35 + 0.65 * t) ** 1.1)
            table.append((min(255, r), min(255, g), min(255, b)))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        base = y * width
        for x in range(width):
            raw.extend(table[pixels[base + x]])

    def chunk(tag, payload):
        block = tag + payload
        return struct.pack(">I", len(payload)) + block + struct.pack(">I", zlib.crc32(block))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Free-threading lab benchmark child")
    parser.add_argument("--mode", required=True, choices=list(MODES))
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--tile-rows", type=int, default=TILE_ROWS_MAX)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    ns = _parse_args(argv)
    params = validate_params(
        ns.width, ns.height, ns.iterations, ns.workers, ns.repeats, ns.tile_rows
    )
    state_before = gil_state()
    report = run_case(params, ns.mode, ns.workers, ns.repeats)
    state_after = gil_state()
    out = {
        "ok": True,
        "mode": ns.mode,
        "mode_label": MODE_LABELS[ns.mode],
        "params": params,
        "workers": ns.workers,
        "tiles": report["tiles"],
        "digest": report["digest"],
        "same_as_serial_reference": report["same_as_serial_reference"],
        "repeats": [
            {
                "repeat": rep["repeat"],
                "engine_seconds": rep["engine_seconds"],
                "engine_wall_seconds": rep["engine_wall_seconds"],
                "engine_start": rep["engine_start"],
                "engine_end": rep["engine_end"],
                "wall_seconds": rep["wall_seconds"],
                "digest": rep["digest"],
                "engine_backend": rep["engine_backend"],
                "engine_width": rep["engine_width"],
                "tiles": rep["tiles"],
            }
            for rep in report["repeats"]
        ],
        "gil_before": state_before,
        "gil_after": state_after,
        "same_work": len({rep["digest"] for rep in report["repeats"]}) == 1,
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
