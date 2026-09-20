"""free_threading_core.py – Free-threading lab worker adapter and public API.

Implements the exact AGILAB Mandelbrot scalar algorithm, tile planning,
pool-engine delegation via agilab_pool, and the run_case orchestration.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sys
import sysconfig
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Sequence

import agilab_pool
from agilab_pool import PoolFrameHooks, run_works

# ---------------------------------------------------------------------------
# Public: reference_image
# ---------------------------------------------------------------------------

def reference_image(width: int, height: int, iterations: int) -> list[int]:
    """Compute the exact Mandelbrot image as a row-major list of iteration counts."""
    _validate_int(width, "width", 2, 384)
    _validate_int(height, "height", 2, 256)
    _validate_int(iterations, "iterations", 1, 300)
    counts: list[int] = []
    for y in range(height):
        for x in range(width):
            z = 0j
            c = complex(-2 + 3 * x / (width - 1), -1.2 + 2.4 * y / (height - 1))
            count = 0
            while count < iterations and z.real * z.real + z.imag * z.imag <= 4:
                z = z * z + c
                count += 1
            counts.append(count)
    return counts


# ---------------------------------------------------------------------------
# Public: image_digest
# ---------------------------------------------------------------------------

def image_digest(counts: list[int]) -> str:
    """Stable SHA-256 hex digest of the complete row-major image.

    Each count is encoded as a fixed-width decimal string (up to 300 fits in
    3 digits) so the digest is deterministic and independent of int repr.
    """
    h = hashlib.sha256()
    for c in counts:
        _validate_int(c, "count", 0, 300)
        h.update(f"{c:03d}".encode("ascii"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Public: make_tiles
# ---------------------------------------------------------------------------

def make_tiles(width: int, height: int) -> list[dict]:
    """Deterministic tile list: two rows per tile, final tile may be shorter.

    Even-indexed and odd-indexed tiles are interleaved for load balance.
    """
    _validate_int(width, "width", 2, 384)
    _validate_int(height, "height", 2, 256)
    tiles: list[dict] = []
    tile_id = 0
    for row_start in range(0, height, 2):
        row_stop = min(row_start + 2, height)
        tiles.append({"tile_id": tile_id, "row_start": row_start, "row_stop": row_stop})
        tile_id += 1
    return tiles[::2] + tiles[1::2]


# ---------------------------------------------------------------------------
# Public: runtime_info
# ---------------------------------------------------------------------------

def runtime_info() -> dict:
    return {
        "free_threaded_build": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "gil_enabled": bool(sys._is_gil_enabled()),
        "version": sys.version,
    }


# ---------------------------------------------------------------------------
# Module-level picklable worker adapter
# ---------------------------------------------------------------------------

class _MandelbrotWorker:
    """Minimal picklable worker adapter for the agilab_pool engine."""

    def __init__(self, width: int, height: int, iterations: int, workers: int):
        self._worker_id = 0
        self._mode = 1  # pool bit
        self._work_done_chunk = 0
        self._width = width
        self._height = height
        self._iterations = iterations
        self._workers = workers
        self.args = {"pool_max_workers": workers, "pool_item_timeout": 10}
        self._collected_frames: list[Any] = []
        self._collected_labels: list[str] = []

    # -- engine-required methods --

    def work_init(self) -> None:
        self._collected_frames = []
        self._collected_labels = []

    def pool_init(self, pool_vars: Any) -> None:
        pass

    def get_pool_vars(self) -> Any:
        return None

    @property
    def pool_vars(self) -> Any:
        return None

    def work_pool(self, item: dict) -> list[dict]:
        """Compute one tile; return a one-record list frame."""
        tile_id = item["tile_id"]
        row_start = item["row_start"]
        row_stop = item["row_stop"]
        w = self._width
        h = self._height
        iters = self._iterations

        info_before = runtime_info()
        start = time.perf_counter()
        counts: list[int] = []
        for y in range(row_start, row_stop):
            for x in range(w):
                z = 0j
                c = complex(-2 + 3 * x / (w - 1), -1.2 + 2.4 * y / (h - 1))
                count = 0
                while count < iters and z.real * z.real + z.imag * z.imag <= 4:
                    z = z * z + c
                    count += 1
                counts.append(count)
        end = time.perf_counter()
        info_after = runtime_info()

        record = {
            "tile_id": tile_id,
            "row_start": row_start,
            "row_stop": row_stop,
            "counts": counts,
            "pid": os.getpid(),
            "thread_id": thread_id(),
            "start": start,
            "end": end,
            "gil_before": info_before["gil_enabled"],
            "gil_after": info_after["gil_enabled"],
            "runtime_before": info_before,
            "runtime_after": info_after,
        }
        return [record]

    def work_done(self, df: Any) -> None:
        self._collected_frames.append(df)
        self._work_done_chunk += 1

    def stop(self) -> None:
        pass

    # -- engine delegation --

    def _exec_multi_process(self, workers_plan: Any, workers_plan_metadata: Any) -> None:
        hooks = _build_hooks()
        agilab_pool.exec_multi_process(self, workers_plan, workers_plan_metadata, hooks)

    def _exec_mono_process(self, workers_plan: Any, workers_plan_metadata: Any) -> None:
        hooks = _build_hooks()
        agilab_pool.exec_mono_process(self, workers_plan, workers_plan_metadata, hooks)

    # -- result collection --

    def collected(self) -> list[Any]:
        return self._collected_frames


def thread_id() -> int:
    """Return a stable thread identifier (threading.get_ident)."""
    import threading
    return threading.get_ident()


# ---------------------------------------------------------------------------
# Module-level frame hooks (picklable)
# ---------------------------------------------------------------------------

def _is_frame(obj: Any) -> bool:
    return isinstance(obj, list) and len(obj) > 0 and all(isinstance(r, dict) for r in obj)


def _is_empty(obj: Any) -> bool:
    return isinstance(obj, list) and len(obj) == 0


def _concat_labeled(frames: Sequence[Any], labels: Sequence[str]) -> list[dict]:
    out: list[dict] = []
    for frame, label in zip(frames, labels):
        for rec in frame:
            r = dict(rec)
            r["_label"] = label
            out.append(r)
    return out


def _empty_frame() -> list:
    return []


def _process_pool_factory(max_workers: int, initializer: Callable | None = None, initargs: tuple = ()) -> ProcessPoolExecutor:
    ctx = multiprocessing.get_context("spawn")
    return ProcessPoolExecutor(max_workers=max_workers, initializer=initializer, initargs=initargs, mp_context=ctx)


def _build_hooks() -> PoolFrameHooks:
    return PoolFrameHooks(
        family="mandelbrot",
        executor_kind="process",
        executor_factory=_process_pool_factory,
        is_frame=_is_frame,
        is_empty=_is_empty,
        concat_labeled=_concat_labeled,
        empty_frame=_empty_frame,
    )


# ---------------------------------------------------------------------------
# Public: run_case
# ---------------------------------------------------------------------------

def run_case(
    width: int,
    height: int,
    iterations: int,
    workers: int,
    mode: str,
) -> dict:
    """Execute one benchmark case and return the result dict."""

    # --- validate inputs ---
    _validate_int(width, "width", 2, 384)
    _validate_int(height, "height", 2, 256)
    _validate_int(iterations, "iterations", 1, 300)
    _validate_int(workers, "workers", 1, 8)

    valid_modes = ("gil_on_threads", "gil_off_threads", "gil_on_processes")
    if mode not in valid_modes:
        raise ValueError(f"mode must be one of {valid_modes}, got {mode!r}")

    # --- validate runtime state ---
    info_before = runtime_info()
    _check_runtime(mode, info_before)

    # --- validate backend via engine (no global env mutation) ---
    hooks = _build_hooks()
    _, resolved_kind = agilab_pool.resolve_executor(hooks)

    expected_kind = "thread" if mode in ("gil_on_threads", "gil_off_threads") else "process"
    if expected_kind == "thread" and "thread" not in resolved_kind:
        raise RuntimeError(f"Expected thread backend, engine resolved {resolved_kind!r}")
    if expected_kind == "process" and "process" not in resolved_kind:
        raise RuntimeError(f"Expected process backend, engine resolved {resolved_kind!r}")

    # --- build tiles and plan ---
    tiles = make_tiles(width, height)
    # Plan: one partition containing all tiles as chunks
    workers_plan = [[tiles]]
    workers_plan_metadata = None

    # --- create worker ---
    worker = _MandelbrotWorker(width, height, iterations, workers)

    # --- execute with bracketed timing ---
    engine_start = time.perf_counter()
    engine_seconds = run_works(worker, workers_plan, workers_plan_metadata)
    engine_end = time.perf_counter()

    # --- post-run runtime check ---
    info_after = runtime_info()
    _check_runtime(mode, info_after)
    if info_before["gil_enabled"] != info_after["gil_enabled"]:
        raise RuntimeError("GIL state changed during execution")
    if info_before["free_threaded_build"] != info_after["free_threaded_build"]:
        raise RuntimeError("Free-threaded build flag changed during execution")

    # --- collect records from worker frames ---
    records: list[dict] = []
    for frame in worker.collected():
        if isinstance(frame, list):
            records.extend(frame)

    # --- validate records ---
    _validate_records(records, tiles, width, height, iterations, mode, info_before, engine_seconds, engine_start, engine_end)

    # --- derive image and digest from worker results ---
    records.sort(key=lambda r: r["row_start"])
    image: list[int] = []
    for rec in records:
        image.extend(rec["counts"])

    if len(image) != width * height:
        raise RuntimeError(f"Image length {len(image)} != expected {width * height}")

    digest = image_digest(image)

    # --- actual workers: distinct (pid, thread_id) pairs ---
    seen: set[tuple[int, int]] = set()
    for rec in records:
        seen.add((rec["pid"], rec["thread_id"]))
    actual_workers = len(seen)

    # --- pool width ---
    pool_width = agilab_pool.resolve_pool_width([len(tiles)], worker.args, executor_kind=resolved_kind)

    return {
        "width": width,
        "height": height,
        "iterations": iterations,
        "mode": mode,
        "workers": workers,
        "actual_workers": actual_workers,
        "pool_width": pool_width,
        "backend": resolved_kind,
        "before": info_before,
        "after": info_after,
        "engine_seconds": engine_seconds,
        "engine_start": engine_start,
        "engine_end": engine_end,
        "records": records,
        "digest": digest,
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_int(value: Any, name: str, lo: int, hi: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a strict integer, got {type(value).__name__}")
    if not (lo <= value <= hi):
        raise ValueError(f"{name} must be in [{lo}, {hi}], got {value}")


def _check_runtime(mode: str, info: dict) -> None:
    # All three modes require a free-threaded build
    if not info["free_threaded_build"]:
        raise RuntimeError(f"Mode {mode!r} requires a free-threaded build")
    if mode == "gil_off_threads":
        if info["gil_enabled"]:
            raise RuntimeError("Mode gil_off_threads requires GIL disabled")
    elif mode == "gil_on_threads":
        if info["gil_enabled"] is False:
            raise RuntimeError("Mode gil_on_threads requires GIL enabled")
    elif mode == "gil_on_processes":
        if info["gil_enabled"] is False:
            raise RuntimeError("Mode gil_on_processes requires GIL enabled")


def _validate_records(
    records: list[dict],
    tiles: list[dict],
    width: int,
    height: int,
    iterations: int,
    mode: str,
    info_before: dict,
    engine_seconds: float,
    engine_start: float,
    engine_end: float,
) -> None:
    import math

    if not records:
        raise RuntimeError("No records returned from workers")

    # Validate engine_seconds is finite and positive
    if not math.isfinite(engine_seconds) or engine_seconds <= 0:
        raise RuntimeError(f"engine_seconds must be finite and positive, got {engine_seconds!r}")

    # Validate engine bracket is finite and positive interval
    if not math.isfinite(engine_start) or not math.isfinite(engine_end):
        raise RuntimeError(f"engine_start/engine_end must be finite, got {engine_start!r}/{engine_end!r}")
    if engine_end <= engine_start:
        raise RuntimeError(f"engine_end must be > engine_start, got {engine_start!r}/{engine_end!r}")

    # Check for missing or duplicate tiles
    tile_ids = [r["tile_id"] for r in records]
    expected_ids = {t["tile_id"] for t in tiles}
    if len(tile_ids) != len(set(tile_ids)):
        raise RuntimeError("Duplicate tile_ids in records")
    if set(tile_ids) != expected_ids:
        missing = expected_ids - set(tile_ids)
        extra = set(tile_ids) - expected_ids
        raise RuntimeError(f"Tile mismatch: missing={missing}, extra={extra}")

    # Build tile lookup for strict row-bound validation
    tile_map = {t["tile_id"]: t for t in tiles}

    # Check row coverage: no overlaps, complete
    rows_covered: list[int] = []
    for r in records:
        rs, rp = r["row_start"], r["row_stop"]
        if rs < 0 or rp > height or rs >= rp:
            raise RuntimeError(f"Invalid row range [{rs}, {rp})")
        # Strict: record row bounds must match the requested tile's exact interval
        expected_tile = tile_map[r["tile_id"]]
        if rs != expected_tile["row_start"] or rp != expected_tile["row_stop"]:
            raise RuntimeError(
                f"Tile {r['tile_id']}: row bounds [{rs}, {rp}) do not match "
                f"requested [{expected_tile['row_start']}, {expected_tile['row_stop']})"
            )
        rows_covered.extend(range(rs, rp))
    if sorted(rows_covered) != list(range(height)):
        raise RuntimeError("Row coverage is incomplete or overlapping")

    # Check counts validity
    for r in records:
        expected_len = (r["row_stop"] - r["row_start"]) * width
        if len(r["counts"]) != expected_len:
            raise RuntimeError(
                f"Tile {r['tile_id']}: counts length {len(r['counts'])} != {expected_len}"
            )
        for c in r["counts"]:
            if not isinstance(c, int) or isinstance(c, bool) or c < 0 or c > iterations:
                raise RuntimeError(f"Tile {r['tile_id']}: invalid count value {c!r}")

    # Check per-worker GIL consistency and runtime snapshots
    expected_gil = info_before["gil_enabled"]
    for r in records:
        if r["gil_before"] != expected_gil or r["gil_after"] != expected_gil:
            raise RuntimeError(
                f"Tile {r['tile_id']}: GIL state mismatch "
                f"(before={r['gil_before']}, after={r['gil_after']}, expected={expected_gil})"
            )
        # Runtime snapshots must equal the parent's info_before
        rb = r.get("runtime_before")
        ra = r.get("runtime_after")
        if rb != info_before:
            raise RuntimeError(f"Tile {r['tile_id']}: runtime_before != info_before")
        if ra != info_before:
            raise RuntimeError(f"Tile {r['tile_id']}: runtime_after != info_before")

    # Validate PID and thread_id are positive integers
    for r in records:
        pid = r["pid"]
        tid = r["thread_id"]
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise RuntimeError(f"Tile {r['tile_id']}: invalid pid {pid!r}")
        if not isinstance(tid, int) or isinstance(tid, bool) or tid <= 0:
            raise RuntimeError(f"Tile {r['tile_id']}: invalid thread_id {tid!r}")

    # Check timestamps: finite, positive duration, within engine bracket
    tol = 1e-6
    for r in records:
        s, e = r["start"], r["end"]
        if not math.isfinite(s) or not math.isfinite(e):
            raise RuntimeError(f"Tile {r['tile_id']}: non-finite timestamps")
        if e - s <= 0:
            raise RuntimeError(f"Tile {r['tile_id']}: non-positive duration")
        if s < engine_start - tol or e > engine_end + tol:
            raise RuntimeError(
                f"Tile {r['tile_id']}: timestamps [{s}, {e}] outside engine bracket "
                f"[{engine_start}, {engine_end}]"
            )

    # Validate digest counts are strict integers in 0..300
    for r in records:
        for c in r["counts"]:
            if not isinstance(c, int) or isinstance(c, bool) or c < 0 or c > 300:
                raise RuntimeError(f"Tile {r['tile_id']}: count {c!r} out of [0, 300]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Free-threading lab case runner")
    parser.add_argument("--case", required=True, help="JSON parameter object")
    cli_args = parser.parse_args()

    try:
        params = json.loads(cli_args.case)
        allowed_keys = {"width", "height", "iterations", "workers", "mode"}
        if set(params.keys()) != allowed_keys:
            extra = set(params.keys()) - allowed_keys
            missing = allowed_keys - set(params.keys())
            raise ValueError(f"CLI JSON keys must be exactly {sorted(allowed_keys)}; extra={extra}, missing={missing}")
        result = run_case(
            width=params["width"],
            height=params["height"],
            iterations=params["iterations"],
            workers=params["workers"],
            mode=params["mode"],
        )
        print(json.dumps(result, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, allow_nan=False), file=sys.stderr)
        sys.exit(1)