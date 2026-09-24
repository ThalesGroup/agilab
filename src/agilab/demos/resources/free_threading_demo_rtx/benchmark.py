"""Subprocess-orchestrated benchmark for the free-threading lab.

Runs the full six-case matrix (3 execution modes x worker counts {1, N}) as
separate free-threaded CPython child processes, enforces per-child and total
timeouts (terminating the whole process group on timeout), returns the full
measured payload, and writes ``results.json`` as the deterministic evidence
artifact (the wall-clock measurements stay in the returned payload, which the
UI renders and downloads).

Every measured case runs in the SAME free-threaded build; modes differ only
by the GIL flag (``-X gil=1|0``) and the AGILAB pool backend (forced thread
pool, auto backend, forced spawn process pool). Nothing is simulated and
ordinary Python is never substituted.

The returned payload carries the measurement contract: one record per
(mode, workers, repeat) in ``runs`` with the real tile records (row spans,
worker identities, start/end intervals), GIL state captured before/after and
per task, engine and wall intervals, plus per-(mode, role) ``summary``
medians computed with ``statistics.median`` over the measured wall seconds.

Usage:
    python benchmark.py --width 192 --height 128 --iterations 160 \
        --workers 4 --repeats 2 --tile-rows 4 --out results.json
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import platform
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

import free_threading_core as core
from free_threading_core import (
    DEFAULT_HEIGHT,
    DEFAULT_ITERATIONS,
    DEFAULT_REPEATS,
    DEFAULT_WIDTH,
    MAX_WORKERS,
    MODES,
    MODE_LABELS,
    TILE_ROWS_MAX,
    FreeThreadingInterpreterError,
)

LOCK_FILENAME = ".benchmark.lock"

# Contract-facing mode identifiers (underscores) per execution mode.
MODE_KEYS = {
    core.MODE_GIL_ON_THREADS: "gil_on_threads",
    core.MODE_GIL_OFF_THREADS: "gil_off_threads",
    core.MODE_GIL_ON_PROCESSES: "gil_on_processes",
}
KEY_TO_MODE = {key: mode for mode, key in MODE_KEYS.items()}
ROLE_BASELINE = "baseline"
ROLE_WIDE = "wide"

# Keys that the child process's per-tile reports include but that are not part
# of the measurement contract (the child does not emit per-tile counts; the
# full image is verified via the digest and the serial reference instead).
_TILE_CONTRACT_KEYS = ("row_start", "row_end", "rows", "start", "end", "pid", "thread")


def effective_cpus() -> dict:
    """Effective CPU count used to cap worker counts (from the core allowance)."""
    return {"effective_cpus": core.effective_cpu_allowance()}


def _acquire_lock(root: str):
    """Serialize simultaneous benchmark runs; returns an open lock file handle."""
    lock_path = os.path.join(root, LOCK_FILENAME)
    handle = open(lock_path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _release_lock(handle) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _terminate_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _probe_interpreter_startup(python: str) -> float | None:
    """Measure one free-threaded interpreter startup (honest overhead data)."""
    try:
        start = time.monotonic()
        subprocess.run([python, "-c", "pass"], capture_output=True, timeout=30, check=False)
        return time.monotonic() - start
    except (subprocess.TimeoutExpired, OSError):
        return None


def _median(values: list[float]) -> float:
    if not values:
        raise ValueError("median of empty list")
    return statistics.median(values)


def _run_one_case(
    python: str,
    params: dict,
    mode: str,
    workers: int,
    repeats: int,
    child_timeout: float,
    source_root: str,
) -> dict:
    """Run one (mode, workers) case in a separate free-threaded child process.

    ``source_root`` is the immutable directory that actually contains
    ``free_threading_core`` and the supplied ``agilab_pool``; it is used as the
    child's working directory so ``-m free_threading_core`` resolves even though
    the child environment scrubs ``PYTHONPATH``.  Mutable runtime state (locks)
    lives elsewhere and is intentionally not passed in here.
    """
    argv = core.child_argv(python, params, mode, workers, repeats)
    env = core.child_env(mode)
    start = time.monotonic()
    proc = subprocess.Popen(
        argv,
        env=env,
        cwd=source_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        proc_stdout, proc_stderr = proc.communicate(timeout=child_timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_group(proc)
        return {
            "mode": mode,
            "status": "timeout",
            "error": f"child exceeded {child_timeout:.1f}s and was terminated (process group)",
        }
    wall = time.monotonic() - start
    if proc.returncode != 0:
        _terminate_process_group(proc)
        return {
            "mode": mode,
            "status": "error",
            "error": f"child exited {proc.returncode}: {proc_stderr.strip()[:800]}",
        }
    try:
        payload = json.loads(proc_stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return {
            "mode": mode,
            "status": "error",
            "error": f"child produced no valid JSON: {exc}; stderr: {proc_stderr.strip()[:400]}",
        }
    if not payload.get("ok"):
        return {
            "mode": mode,
            "status": "error",
            "error": payload.get("error", "child reported failure"),
        }

    repeats_out = []
    for rep in payload["repeats"]:
        engine_time = float(rep["engine_seconds"])
        engine_wall = float(rep["engine_wall_seconds"])
        if engine_time <= 0.0 or engine_wall <= 0.0:
            raise ValueError("engine reported a non-positive measured time")
        tiles = rep["tiles"]
        if not tiles:
            raise ValueError("child reported no tile records")
        records = []
        identities = set()
        for tile in tiles:
            rec_start = float(tile["start"])
            rec_end = float(tile["end"])
            pid = int(tile["pid"])
            thread_id = int(tile["thread"])
            record = {
                key: tile[key] for key in _TILE_CONTRACT_KEYS if key in tile
            }
            record["start"] = rec_start
            record["end"] = rec_end
            record["duration_seconds"] = rec_end - rec_start
            record["pid"] = pid
            record["thread_id"] = thread_id
            # Per-task GIL observations captured inside the actual worker that
            # ran the tile (runtime_before/runtime_after), not a copy of the
            # coordinator-level probe.
            record["runtime_before"] = tile["runtime_before"]
            record["runtime_after"] = tile["runtime_after"]
            record["counts"] = list(tile["counts"])
            records.append(record)
            identities.add((pid, thread_id))
        # The engine's own measured bounds (captured around run_works in the
        # child) are preserved verbatim: no min/max envelope reconstruction,
        # no division of a grouped duration into fake repeats.
        engine_start = float(rep["engine_start"])
        engine_end = float(rep["engine_end"])
        if engine_end <= engine_start:
            raise ValueError("engine reported a non-positive measured interval")
        # Per-repeat wall time is the real measured wall interval from the
        # child (the engine's own wall clock for in-process thread modes, the
        # measured tile envelope in spawn-process mode). Never a division of a
        # grouped duration into fake repeats.
        wall_seconds = float(rep["wall_seconds"]) if "wall_seconds" in rep else engine_wall
        repeats_out.append(
            {
                "repeat": int(rep["repeat"]),
                "mode": MODE_KEYS[mode],
                "mode_label": MODE_LABELS[mode],
                "workers": workers,
                "status": "ok",
                "records": records,
                "tiles": records,
                "actual_workers": len(identities),
                "pool_width": int(rep["engine_width"]),
                "engine_backend": rep["engine_backend"],
                "engine_seconds": engine_time,
                "engine_wall_seconds": engine_wall,
                "engine_start": engine_start,
                "engine_end": engine_end,
                "wall_seconds": wall_seconds,
                "digest": rep["digest"],
                "before": payload["gil_before"],
                "after": payload["gil_after"],
            }
        )

    digests = {rep["digest"] for rep in repeats_out}
    if len(digests) != 1:
        raise ValueError(f"digest mismatch across repeats in {mode}: {sorted(digests)}")
    engine_times = [rep["engine_seconds"] for rep in repeats_out]
    pixels = params["width"] * params["height"]
    median_engine = _median(engine_times)
    return {
        "mode": mode,
        "status": "ok",
        "workers": workers,
        "mode_label": MODE_LABELS[mode],
        "repeats": repeats_out,
        "digest": next(iter(digests)),
        "same_as_serial_reference": bool(payload["same_as_serial_reference"]),
        "engine_backend": repeats_out[0]["engine_backend"],
        "engine_width": repeats_out[0]["pool_width"],
        "median_engine_seconds": median_engine,
        "median_wall_seconds": _median([rep["wall_seconds"] for rep in repeats_out]),
        "dispatch_overhead_seconds": max(0.0, wall - median_engine),
        "throughput_pixels_per_s": pixels / median_engine if median_engine > 0 else None,
    }


def deterministic_evidence(results: dict) -> dict:
    """Project the measured payload onto the replay-stable scientific evidence.

    The ``results.json`` artifact is imported by the workflow verifier after the
    notebook run and compared for equality, so it must reproduce exactly for any
    two runs of the same workload and configuration.  This keeps only the
    run-independent scientific projection: workload/configuration, interpreter
    build facts (no executable path), mode/role/workers, engine backend, the
    ordered actual pixel counts and digests, the same-work and serial-reference
    verification, and the observed per-task GIL flags (no executable path).

    Every run-specific identity and measurement is dropped at every nested
    level: PIDs/thread ids, timestamps and intervals, tile timelines, engine
    widths, startup probes, medians, throughput, dispatch overhead, speedups and
    total wall time.  The full measured payload is left untouched in the
    in-memory return value that the UI renders and downloads; only this
    projection written to disk is deterministic.
    """
    hardware = {
        "effective_cpu_allowance": results["hardware"]["effective_cpu_allowance"],
    }
    evidence = {
        "app": results["app"],
        "source_credit": results["source_credit"],
        "free_threading_docs": results["free_threading_docs"],
        "python_build": results["python_build"],
        "interpreter": {
            "version": results["interpreter"]["version"],
            "free_threaded_build": results["interpreter"]["free_threaded_build"],
            "py_gil_disabled_build": results["interpreter"]["py_gil_disabled_build"],
        },
        "hardware": hardware,
        "params": results["params"],
        "digest": results["digest"],
        "same_work": results["same_work"],
        "same_work_verified": results["same_work_verified"],
        "same_as_serial_reference": results["same_as_serial_reference"],
        "runs": [],
        "summary": [],
        "notes": results["notes"],
    }

    for run in results.get("runs", []):
        records = []
        for record in run.get("records", []):
            records.append(
                {
                    "row_start": record["row_start"],
                    "row_end": record["row_end"],
                    "rows": record["rows"],
                    "counts": list(record["counts"]),
                    "runtime_before": record["runtime_before"],
                    "runtime_after": record["runtime_after"],
                }
            )
        records.sort(key=lambda record: record["row_start"])
        evidence["runs"].append(
            {
                "mode": run["mode"],
                "mode_label": run["mode_label"],
                "workers": run["workers"],
                "repeat": run["repeat"],
                "role": run["role"],
                "status": run["status"],
                "records": records,
                "digest": run["digest"],
            }
        )

    for entry in results.get("summary", []):
        evidence["summary"].append(
            {
                "mode": entry["mode"],
                "role": entry["role"],
                "workers": entry["workers"],
                "engine_backend": entry["engine_backend"],
            }
        )

    return evidence


def run_benchmark(
    width: int,
    height: int,
    iterations: int,
    workers: int,
    repeats: int,
    tile_rows: int = TILE_ROWS_MAX,
    child_timeout: float = 60.0,
    total_timeout: float = 180.0,
    root: str | None = None,
    out_path: str | None = None,
    progress_cb=None,
) -> dict:
    """Run all six cases, compute speedups, and write results.json.

    ``progress_cb(done, total, label)`` is invoked after each case finishes.
    The returned payload carries ``runs`` (one record per mode/worker/repeat)
    and ``summary`` (per mode/role medians and speedups) exactly as measured.
    """
    # Mutable runtime state (the lock) stays in the caller-supplied temp root,
    # while child processes are launched from the immutable source directory so
    # ``-m free_threading_core`` and the supplied ``agilab_pool`` stay importable.
    source_root = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(root or source_root)
    params = core.validate_params(
        width, height, iterations, workers, repeats, tile_rows, child_timeout, total_timeout
    )
    python, probe = core.resolve_free_threading_python()
    allowance = core.effective_cpu_allowance()
    if params["workers"] > allowance:
        raise ValueError(
            f"workers={params['workers']} exceeds the effective CPU allowance {allowance}"
        )

    lock = _acquire_lock(root)
    if lock is None:
        raise RuntimeError(
            "another benchmark run is already in progress; try again shortly"
        )
    started = time.monotonic()
    deadline = started + total_timeout
    cases: list[dict] = []
    # Two distinct measurement slots per mode (baseline and wide) even when the
    # requested width is 1, so both roles are always measured and summarized.
    case_slots = [
        (ROLE_BASELINE, 1),
        (ROLE_WIDE, params["workers"]),
    ]
    total_cases = len(MODES) * len(case_slots)
    startup_probe = _probe_interpreter_startup(python)

    def _report(done: int, label: str) -> None:
        if progress_cb is not None:
            progress_cb(done, total_cases, label)

    try:
        done = 0
        for mode in MODES:
            for case_role, case_workers in case_slots:
                # The slot role is carried into every repeat of the case, so
                # baseline/wide stay distinct measurement slots even when both
                # use one worker (N == 1).
                label = f"{MODE_LABELS[mode]} · {case_workers} worker(s)"
                if time.monotonic() >= deadline and cases:
                    cases.append(
                        {
                            "mode": mode,
                            "workers": case_workers,
                            "role": case_role,
                            "status": "skipped",
                            "error": f"total budget {total_timeout:.0f}s exhausted before this case",
                        }
                    )
                else:
                    cases.append(
                        _run_one_case(
                            python, params, mode, case_workers, repeats, child_timeout, source_root
                        )
                    )
                    cases[-1]["role"] = case_role
                done += 1
                _report(done, label)
    finally:
        _release_lock(lock)

    ok_cases = [case for case in cases if case["status"] == "ok"]
    if len(ok_cases) != len(cases):
        failed = [
            f"{case['mode']} w={case.get('workers', '?')}: {case.get('error', case['status'])}"
            for case in cases
            if case["status"] != "ok"
        ]
        raise RuntimeError("benchmark incomplete: " + "; ".join(failed))

    digests = {case["digest"] for case in ok_cases}
    same_work = len(digests) == 1
    same_as_serial = all(case["same_as_serial_reference"] for case in ok_cases)
    if not same_work:
        raise RuntimeError(f"digest mismatch across modes: {sorted(digests)}")

    # Flatten one run record per (mode, workers, repeat) in measured order.
    runs: list[dict] = []
    for case in ok_cases:
        role = case["role"]
        for rep in case["repeats"]:
            runs.append(dict(rep, role=role))

    # Per (mode, role) summary: exact statistics.median over the measured
    # per-repeat wall seconds; speedup = baseline median / group median.
    summary: list[dict] = []
    speedups: dict[str, dict] = {}
    for mode in MODES:
        for role in (ROLE_BASELINE, ROLE_WIDE):
            group = [r for r in runs if r["mode"] == MODE_KEYS[mode] and r["role"] == role]
            if not group:
                raise RuntimeError(f"missing measured runs for {mode} role {role}")
            median_wall = statistics.median(r["wall_seconds"] for r in group)
            baseline = [r for r in runs if r["mode"] == MODE_KEYS[mode] and r["role"] == ROLE_BASELINE]
            baseline_median = statistics.median(r["wall_seconds"] for r in baseline)
            workers = group[0]["workers"]
            summary.append(
                {
                    "mode": MODE_KEYS[mode],
                    "role": role,
                    "workers": workers,
                    "repeats": len(group),
                    "engine_backend": group[0]["engine_backend"],
                    "pool_width": group[0]["pool_width"],
                    "wall_seconds": median_wall,
                    "speedup": baseline_median / median_wall if median_wall > 0 else None,
                }
            )
        baseline_runs = [r for r in runs if r["mode"] == MODE_KEYS[mode] and r["role"] == ROLE_BASELINE]
        wide_runs = [r for r in runs if r["mode"] == MODE_KEYS[mode] and r["role"] == ROLE_WIDE]
        speedups[mode] = {
            "baseline_workers": 1,
            "baseline_median_seconds": statistics.median(r["engine_seconds"] for r in baseline_runs),
            "workers": params["workers"],
            "wide_median_seconds": statistics.median(r["engine_seconds"] for r in wide_runs),
            "speedup": (
                statistics.median(r["engine_seconds"] for r in baseline_runs)
                / statistics.median(r["engine_seconds"] for r in wide_runs)
                if wide_runs
                and statistics.median(r["engine_seconds"] for r in wide_runs) > 0
                else None
            ),
        }

    notes = []
    if params["workers"] == 1:
        notes.append(
            "Scaling is unavailable on this machine: only 1 effective CPU is "
            "allowed, so the wide and baseline cases are identical."
        )
    notes.append(
        "Speedups are medians over repeats, relative to each mode's one-worker "
        "baseline in the same free-threaded build."
    )

    hardware = {
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "process_cpu_count": getattr(os, "process_cpu_count", lambda: None)(),
        "affinity_size": len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        "effective_cpu_allowance": allowance,
        "space_cpu_cores": os.environ.get("SPACE_CPU_CORES", ""),
    }
    results = {
        "app": core.APP_TITLE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_credit": core.SOURCE_CREDIT,
        "free_threading_docs": core.FREE_THREADING_DOCS,
        "python_build": probe["version"],
        "interpreter": {
            "executable": python,
            "version": probe["version"],
            "free_threaded_build": probe["free_threaded_build"],
            "py_gil_disabled_build": probe["py_gil_disabled_build"],
        },
        "hardware": hardware,
        "params": {
            "width": params["width"],
            "height": params["height"],
            "iterations": params["iterations"],
            "workers": params["workers"],
            "repeats": repeats,
            "tile_rows": tile_rows,
            "child_timeout": child_timeout,
            "total_timeout": total_timeout,
        },
        "interpreter_startup_probe_seconds": startup_probe,
        "runs": runs,
        "cases": cases,
        "summary": summary,
        "digest": next(iter(digests)),
        "same_work": same_work,
        "same_work_verified": same_work,
        "same_as_serial_reference": same_as_serial,
        "speedups": speedups,
        "total_seconds": round(time.monotonic() - started, 3),
        "notes": notes,
    }
    if out_path:
        artifact_dir = os.path.dirname(os.path.abspath(out_path))
        os.makedirs(artifact_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"results": deterministic_evidence(results)}, fh, indent=2)
    payload = {"results": results}
    for key in ("runs", "summary", "digest", "same_work_verified", "hardware", "python_build"):
        payload[key] = results[key]
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Free-threading lab benchmark")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--tile-rows", type=int, default=TILE_ROWS_MAX)
    parser.add_argument("--child-timeout", type=float, default=60.0)
    parser.add_argument("--total-timeout", type=float, default=180.0)
    parser.add_argument("--out", type=str, default=None)
    ns = parser.parse_args(argv)
    try:
        payload = run_benchmark(
            ns.width,
            ns.height,
            ns.iterations,
            ns.workers,
            ns.repeats,
            ns.tile_rows,
            ns.child_timeout,
            ns.total_timeout,
            out_path=ns.out,
        )
    except (ValueError, RuntimeError, FreeThreadingInterpreterError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
