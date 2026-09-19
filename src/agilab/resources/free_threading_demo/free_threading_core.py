"""Exact original AGILAB Mandelbrot kernel and stdlib-only pool adapter.

Original AGILAB notebook created September 19, 2026. BSD-3-Clause; see LICENSE.
Run this module only in an isolated benchmark child, never in a UI process.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import signal
import struct
import sys
import sysconfig
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import agilab_pool as pool

MODES = {
    "gil_on_threads": (1, "thread"),
    "gil_off_threads": (0, "auto"),
    "gil_on_processes": (1, "process"),
}


def integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def validate_parameters(width, height, iterations, workers=1, tile_rows=3):
    integer("width", width, 2, 384)
    integer("height", height, 2, 256)
    integer("iterations", iterations, 1, 300)
    integer("workers", workers, 1, 8)
    integer("tile_rows", tile_rows, 2, 4)


def validate_mode(mode):
    if type(mode) is not str or mode not in MODES:
        raise ValueError("Unknown mode; choose " + ", ".join(MODES))


def row_counts(width, height, iterations, start, stop):
    pixels = []
    for y in range(start, stop):
        cy = -1.2 + 2.4 * y / (height - 1)
        for x in range(width):
            cx = -2.0 + 3.0 * x / (width - 1)
            z = 0j
            c = complex(cx, cy)
            count = 0
            while count < iterations and z.real*z.real + z.imag*z.imag <= 4.0:
                z = z*z + c
                count += 1
            pixels.append(count)
    return pixels


def reference_image(width=96, height=64, iterations=100):
    validate_parameters(width, height, iterations)
    return row_counts(width, height, iterations, 0, height)


def tile_plan(width, height, iterations, tile_rows=3):
    validate_parameters(width, height, iterations, tile_rows=tile_rows)
    # Bit-reversal order distributes expensive central rows among contiguous
    # batches used by the unchanged AGILAB engine, independent of pool width.
    tiles = [(i, y, min(y + tile_rows, height), width, height, iterations)
             for i, y in enumerate(range(0, height, tile_rows))]
    bits = max(1, (len(tiles) - 1).bit_length())
    return tuple(sorted(tiles, key=lambda t: int(f"{t[0]:0{bits}b}"[::-1], 2)))


def image_digest(counts):
    return hashlib.sha256(b"".join(struct.pack(">H", n) for n in counts)).hexdigest()


def runtime_state():
    checker = getattr(sys, "_is_gil_enabled", None)
    return {"free_threaded_build": sysconfig.get_config_var("Py_GIL_DISABLED") == 1,
            "gil_enabled": checker() if checker else None,
            "version": sys.version, "implementation": sys.implementation.name}


def verify_runtime(state, mode):
    if not state["free_threaded_build"] or state["gil_enabled"] is not bool(MODES[mode][0]):
        raise RuntimeError("Requires a free-threaded Python build with the requested actual GIL state. "
                           "Set AGILAB_FREE_THREADING_PYTHON to a working python3.14t executable.")


def compute_tile(item):
    tile_id, start, stop, width, height, iterations = item
    begun = time.monotonic_ns()
    counts = row_counts(width, height, iterations, start, stop)
    ended = time.monotonic_ns()
    return [{"tile": tile_id, "row_start": start, "row_stop": stop,
             "counts": counts, "start_ns": begun, "end_ns": ended,
             "pid": os.getpid(), "thread_id": threading.get_native_id(),
             "gil_enabled": sys._is_gil_enabled()}]


def reduce_tiles(records, plan):
    expected = {t[0]: t for t in plan}
    found = {}
    for record in records:
        idx = record.get("tile")
        if type(idx) is not int or idx not in expected or idx in found:
            raise ValueError("Duplicate or unknown tile in engine reduction")
        _, start, stop, width, _, iterations = expected[idx]
        if (record.get("row_start"), record.get("row_stop")) != (start, stop):
            raise ValueError("Mismatched tile rows")
        counts = record.get("counts")
        if (not isinstance(counts, list) or len(counts) != width * (stop - start)
                or any(type(n) is not int or not 0 <= n <= iterations for n in counts)):
            raise ValueError("Incomplete or invalid tile pixels")
        if any(type(record.get(k)) is not int for k in ("start_ns", "end_ns", "pid", "thread_id")):
            raise ValueError("Invalid worker timeline")
        if record["end_ns"] < record["start_ns"] or record["pid"] <= 0:
            raise ValueError("Invalid worker timeline interval")
        found[idx] = record
    if found.keys() != expected.keys():
        raise ValueError("Incomplete tile coverage")
    ordered = sorted(found.values(), key=lambda r: r["row_start"])
    return [n for r in ordered for n in r["counts"]]


def spawn_executor(**kwargs):
    return ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn"), **kwargs)


def concat_labeled(frames, labels):
    return [dict(row, engine_label=label) for frame, label in zip(frames, labels) for row in frame]


HOOKS = pool.PoolFrameHooks(
    family="MandelbrotListWorker", executor_kind="process", executor_factory=spawn_executor,
    is_frame=lambda value: isinstance(value, list), is_empty=lambda value: not value,
    concat_labeled=concat_labeled, empty_frame=list,
)


@dataclass(frozen=True)
class WorkerConfig:
    plan: tuple
    width: int


class MandelbrotWorker:
    """Tasks read immutable items only; work_done runs in the collecting parent."""
    _worker_id = 0
    pool_vars = None
    work_pool = staticmethod(compute_tile)

    def __init__(self, plan, workers, mono=False):
        self.config = WorkerConfig(plan, workers)
        self.args = {"pool_max_workers": workers}
        self._mode = 0 if mono else 1
        self.records = None
        self.counts = None

    def pool_init(self, _):
        pass  # Deliberately no shared application writes in thread initializers.

    def work_init(self):
        pass

    def stop(self):
        pass

    def _exec_multi_process(self, plan, metadata):
        pool.exec_multi_process(self, plan, metadata, HOOKS)

    def _exec_mono_process(self, plan, metadata):
        pool.exec_mono_process(self, plan, metadata, HOOKS)

    def work_done(self, records):
        self.counts = reduce_tiles(records, self.config.plan)
        self.records = records


def execute(width, height, iterations, workers, mode, tile_rows=3, mono=False):
    validate_parameters(width, height, iterations, workers, tile_rows)
    validate_mode(mode)
    before = runtime_state()
    verify_runtime(before, mode)
    if os.environ.get("AGILAB_POOL_EXECUTOR") != MODES[mode][1]:
        raise RuntimeError("Child executor environment does not match the requested mode")
    plan = tile_plan(width, height, iterations, tile_rows)
    worker = MandelbrotWorker(plan, workers, mono)
    _, backend = pool.resolve_executor(HOOKS)
    actual_width = 1 if mono else pool.resolve_pool_width([len(plan)], worker.args, executor_kind=backend)
    origin_ns = time.monotonic_ns()
    engine_seconds = pool.run_works(worker, [[plan]], None)
    after = runtime_state()
    verify_runtime(after, mode)
    if any(r["gil_enabled"] is not bool(MODES[mode][0]) for r in worker.records):
        raise RuntimeError("A task ran with an unexpected GIL state")
    return {"mode": mode, "workers": workers, "actual_workers": actual_width,
            "observed_workers": len({(r["pid"], r["thread_id"]) for r in worker.records}),
            "backend": "mono" if mono else backend, "before": before, "after": after,
            "engine_seconds": engine_seconds, "origin_ns": origin_ns,
            "digest": image_digest(worker.counts), "records": worker.records,
            "parameters": {"width": width, "height": height, "iterations": iterations,
                           "tile_rows": tile_rows}, "tile_plan": plan}


def _terminate(signum, frame):
    raise SystemExit(128 + signum)


def main():
    signal.signal(signal.SIGTERM, _terminate)
    request = json.loads(sys.stdin.read(4096))
    if not isinstance(request, dict) or set(request) != {"width", "height", "iterations", "workers", "mode"}:
        raise ValueError("Expected only width, height, iterations, workers and mode")
    print(json.dumps(execute(**request), allow_nan=False))


if __name__ == "__main__":
    main()
