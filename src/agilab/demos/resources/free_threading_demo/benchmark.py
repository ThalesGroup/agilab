"""benchmark.py – Free-threading lab orchestrator.

Orchestrates the adjacent free_threading_core.py in isolated child process
groups. Standard library only. No shell, no eval/exec, no networking.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Module-level serialisation lock
# ---------------------------------------------------------------------------

_benchmark_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CORE_FILENAME = "free_threading_core.py"
_CHILD_TIMEOUT = 30.0
_TOTAL_TIMEOUT = 150.0
_MAX_WORKERS = 8
_KILL_GRACE = 0.25  # seconds between SIGTERM and SIGKILL

# Mode → (-X gil value, AGILAB_POOL_EXECUTOR value)
_MODE_CONFIG = {
    "gil_on_threads": ("1", "thread"),
    "gil_off_threads": ("0", "auto"),
    "gil_on_processes": ("1", "process"),
}

_ROLES = ("baseline", "parallel")
_MODES = ("gil_on_threads", "gil_off_threads", "gil_on_processes")


# ---------------------------------------------------------------------------
# effective_cpus
# ---------------------------------------------------------------------------

def effective_cpus() -> dict:
    """Return a JSON-safe dict with effective_cpus (int 1..8) and observed caps."""
    caps: dict[str, Any] = {}

    # Host CPU count (informational only, not the allowed count)
    host_cpus = os.cpu_count()
    if host_cpus is not None:
        caps["host_cpu_count"] = host_cpus

    # os.process_cpu_count (Python 3.13+)
    proc_cpus: Optional[int] = None
    if hasattr(os, "process_cpu_count"):
        try:
            proc_cpus = os.process_cpu_count()
            caps["process_cpu_count"] = proc_cpus
        except (OSError, ValueError):
            pass

    # os.sched_getaffinity (Linux)
    affinity_cpus: Optional[int] = None
    if hasattr(os, "sched_getaffinity"):
        try:
            mask = os.sched_getaffinity(0)
            affinity_cpus = len(mask)
            caps["sched_affinity"] = affinity_cpus
        except (OSError, AttributeError):
            pass

    # cgroup v2: /sys/fs/cgroup/cpu.max
    cgroup_v2_cpus: Optional[float] = None
    try:
        with open("/sys/fs/cgroup/cpu.max", "r") as f:
            parts = f.read().split()
        if len(parts) >= 2 and parts[0] != "max":
            quota = int(parts[0])
            period = int(parts[1])
            if period > 0 and quota > 0:
                cgroup_v2_cpus = quota / period
                caps["cgroup_v2_cpu_max"] = f"{quota}/{period}"
    except (OSError, ValueError, IndexError):
        pass

    # cgroup v1: /sys/fs/cgroup/cpu/cpu.cfs_quota_us + cpu.cfs_period_us
    cgroup_v1_cpus: Optional[float] = None
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r") as f:
            quota = int(f.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r") as f:
            period = int(f.read().strip())
        if quota > 0 and period > 0:
            cgroup_v1_cpus = quota / period
            caps["cgroup_v1_cfs"] = f"{quota}/{period}"
    except (OSError, ValueError):
        pass

    # CPU_CORES environment variable
    env_cpus: Optional[int] = None
    cpu_cores_env = os.environ.get("CPU_CORES")
    if cpu_cores_env is not None:
        try:
            val = int(cpu_cores_env)
            if val > 0:
                env_cpus = val
                caps["cpu_cores_env"] = val
        except ValueError:
            pass

    # Determine effective: minimum of all available constraints, floor to int, clamp [1, 8]
    candidates: list[float] = []
    if host_cpus is not None and host_cpus > 0:
        candidates.append(float(host_cpus))
    if proc_cpus is not None and proc_cpus > 0:
        candidates.append(float(proc_cpus))
    if affinity_cpus is not None and affinity_cpus > 0:
        candidates.append(float(affinity_cpus))
    if cgroup_v2_cpus is not None and cgroup_v2_cpus > 0:
        candidates.append(cgroup_v2_cpus)
    if cgroup_v1_cpus is not None and cgroup_v1_cpus > 0:
        candidates.append(cgroup_v1_cpus)
    if env_cpus is not None and env_cpus > 0:
        candidates.append(float(env_cpus))

    if candidates:
        effective = max(1, min(int(math.floor(min(candidates))), _MAX_WORKERS))
    else:
        effective = 1

    caps["effective_cpus"] = effective
    return caps


# ---------------------------------------------------------------------------
# find_free_threading_python
# ---------------------------------------------------------------------------

def _probe_interpreter(resolved: str, timeout: float) -> dict:
    """Probe a resolved interpreter in a sanitized child process. Returns info dict."""
    probe_code = (
        "import json,sys,sysconfig;"
        "print(json.dumps({"
        "'free_threaded_build':bool(sysconfig.get_config_var('Py_GIL_DISABLED')),"
        "'gil_enabled':bool(sys._is_gil_enabled()),"
        "'version':sys.version"
        "}))"
    )
    env = dict(os.environ)
    env.pop("PYTHON_GIL", None)
    for k in [k for k in env if k.startswith("AGILAB_POOL_")]:
        del env[k]
    try:
        proc = subprocess.Popen(
            [resolved, "-X", "gil=0", "-c", probe_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Failed to launch interpreter {resolved!r}: {exc}"
        ) from exc

    pgid = proc.pid
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc, pgid)
        raise RuntimeError(
            f"Interpreter probe timed out for {resolved!r}"
        ) from None
    except BaseException:
        _kill_process_group(proc, pgid)
        raise
    finally:
        _kill_process_group(proc, pgid)

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Interpreter probe failed (rc={proc.returncode}) for {resolved!r}: {err_text}"
        )

    try:
        info = json.loads(stdout.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Interpreter probe returned malformed JSON: {exc}"
        ) from exc

    if not info.get("free_threaded_build"):
        raise RuntimeError(
            f"Resolved interpreter {resolved!r} is NOT a free-threaded build "
            f"(Py_GIL_DISABLED={info.get('free_threaded_build')}). "
            "A standard CPython build cannot be used for this lab."
        )

    return info


def find_free_threading_python() -> str:
    """Resolve the free-threaded Python executable.

    Checks AGILAB_FREE_THREADING_PYTHON env var first, then shutil.which('python3.14t').
    Probes the resolved interpreter in a bounded child process to verify it is
    a free-threaded build. Raises actionable errors on failure.
    """
    _ensure_process_group_support()

    candidate: Optional[str] = None

    env_val = os.environ.get("AGILAB_FREE_THREADING_PYTHON")
    if env_val:
        candidate = env_val
    else:
        candidate = shutil.which("python3.14t")

    if candidate is None:
        raise RuntimeError(
            "No free-threaded Python found. Set AGILAB_FREE_THREADING_PYTHON "
            "to the path of a free-threaded (python3.14t) interpreter, or "
            "ensure 'python3.14t' is on PATH."
        )

    resolved = str(Path(candidate).resolve())
    if not os.path.isfile(resolved) or not os.access(resolved, os.X_OK):
        raise RuntimeError(
            f"AGILAB_FREE_THREADING_PYTHON or resolved path {resolved!r} "
            "is not an executable file."
        )

    _probe_interpreter(resolved, timeout=10.0)
    return resolved


# ---------------------------------------------------------------------------
# Process group cleanup helpers
# ---------------------------------------------------------------------------

def _kill_process_group(proc: subprocess.Popen, pgid: int) -> None:
    """Terminate and reap a child process group with bounded SIGTERM then SIGKILL.

    pgid is the owned group id (== proc.pid when start_new_session=True).
    Never returns early just because the leader exited; cleans the group
    independently of leader liveness.
    """
    own_pgid: Optional[int] = None
    try:
        own_pgid = os.getpgid(0)
    except OSError:
        pass

    if pgid > 0 and (own_pgid is None or pgid != own_pgid):
        # SIGTERM to the group
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        # Bounded grace: check group existence via killpg(pgid, 0)
        deadline = time.monotonic() + _KILL_GRACE
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except (OSError, ProcessLookupError):
                break
            time.sleep(0.05)

        # SIGKILL group if still exists
        try:
            os.killpg(pgid, 0)
            os.killpg(pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    # Bounded reap of leader
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Failed to reap child process (pid={proc.pid}) after SIGKILL; "
            "process may be stuck in uninterruptible state."
        )


def _ensure_process_group_support() -> None:
    """Raise an actionable error if process-group cleanup cannot be guaranteed."""
    if not hasattr(os, "killpg") or not hasattr(os, "getpgid"):
        raise RuntimeError(
            "This platform does not support process-group signals "
            "(os.killpg/os.getpgid unavailable). Cannot guarantee safe "
            "cleanup of spawned worker processes. Use a POSIX system "
            "(Linux, macOS, BSD) for this benchmark."
        )


# ---------------------------------------------------------------------------
# Child launch
# ---------------------------------------------------------------------------

def _build_child_env(mode: str) -> dict[str, str]:
    """Build a private environment for the child: remove PYTHON_GIL and all
    AGILAB_POOL_* keys, then set AGILAB_POOL_EXECUTOR appropriately."""
    env = dict(os.environ)
    # Remove PYTHON_GIL
    env.pop("PYTHON_GIL", None)
    # Remove all AGILAB_POOL_* keys
    keys_to_remove = [k for k in env if k.startswith("AGILAB_POOL_")]
    for k in keys_to_remove:
        del env[k]
    # Set the executor
    _, executor_val = _MODE_CONFIG[mode]
    env["AGILAB_POOL_EXECUTOR"] = executor_val
    return env


def _launch_child(
    interpreter: str,
    core_path: str,
    mode: str,
    params: dict,
    cwd: str,
    timeout: float,
) -> tuple[dict, float]:
    """Launch one child case. Returns (result_dict, wall_seconds).

    Raises on timeout or non-zero exit.
    """
    gil_flag, _ = _MODE_CONFIG[mode]
    argv = [interpreter, "-X", f"gil={gil_flag}", core_path, "--case", json.dumps(params)]
    env = _build_child_env(mode)

    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to launch child: {exc}") from exc

    pgid = proc.pid
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc, pgid)
        wall = time.monotonic() - t0
        raise RuntimeError(
            f"Child timed out after {timeout:.1f}s (mode={mode})."
        ) from None
    except BaseException:
        _kill_process_group(proc, pgid)
        raise
    finally:
        _kill_process_group(proc, pgid)

    wall = time.monotonic() - t0

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Child exited with rc={proc.returncode} (mode={mode}): {err_text[:1000]}"
        )

    # Parse JSON from stdout
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    if not stdout_text:
        raise RuntimeError(f"Child produced no stdout (mode={mode})")

    try:
        result = json.loads(stdout_text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Child produced malformed JSON (mode={mode}): {exc}. "
            f"Raw: {stdout_text[:500]!r}"
        ) from exc

    # Reject NaN/Infinity
    _reject_nonfinite(result)

    return result, wall


def _reject_nonfinite(obj: Any) -> None:
    """Recursively reject NaN and Infinity in a JSON-parsed structure."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"Non-finite value in child result: {obj!r}")
    elif isinstance(obj, dict):
        for v in obj.values():
            _reject_nonfinite(v)
    elif isinstance(obj, list):
        for v in obj:
            _reject_nonfinite(v)


# ---------------------------------------------------------------------------
# Validation of child results
# ---------------------------------------------------------------------------

def _validate_child_result(
    result: dict,
    expected_params: dict,
    expected_mode: str,
    expected_interpreter_version: str,
    expected_free_threaded: bool,
    expected_gil: bool,
    expected_tiles: list[dict],
    expected_width: int,
    expected_height: int,
    expected_iterations: int,
    wall_seconds: float,
) -> None:
    """Validate a child result dict against expectations. Raises on failure."""

    # Same input params
    for key in ("width", "height", "iterations", "workers", "mode"):
        if result.get(key) != expected_params[key]:
            raise RuntimeError(
                f"Child result param mismatch: {key}={result.get(key)!r} "
                f"expected {expected_params[key]!r}"
            )

    # Free-threaded build
    before = result.get("before", {})
    after = result.get("after", {})
    if before.get("free_threaded_build") is not expected_free_threaded:
        raise RuntimeError(
            f"free_threaded_build mismatch: {before.get('free_threaded_build')!r}"
        )
    if after.get("free_threaded_build") is not expected_free_threaded:
        raise RuntimeError(
            f"free_threaded_build (after) mismatch: {after.get('free_threaded_build')!r}"
        )
    if before.get("free_threaded_build") != after.get("free_threaded_build"):
        raise RuntimeError("free_threaded_build changed during execution")

    # GIL state
    if before.get("gil_enabled") is not expected_gil:
        raise RuntimeError(
            f"GIL state (before) mismatch: {before.get('gil_enabled')!r} expected {expected_gil!r}"
        )
    if after.get("gil_enabled") is not expected_gil:
        raise RuntimeError(
            f"GIL state (after) mismatch: {after.get('gil_enabled')!r} expected {expected_gil!r}"
        )
    if before.get("gil_enabled") != after.get("gil_enabled"):
        raise RuntimeError("GIL state changed during execution")

    # Interpreter version
    if before.get("version") != expected_interpreter_version:
        raise RuntimeError(
            f"Interpreter version mismatch: {before.get('version')!r} "
            f"expected {expected_interpreter_version!r}"
        )

    # Tile coverage
    records = result.get("records", [])
    if not isinstance(records, list) or not records:
        raise RuntimeError("Child result has no records")

    tile_ids = [r.get("tile_id") for r in records]
    expected_tile_ids = {t["tile_id"] for t in expected_tiles}
    if len(tile_ids) != len(set(tile_ids)):
        raise RuntimeError("Duplicate tile_ids in child records")
    if set(tile_ids) != expected_tile_ids:
        missing = expected_tile_ids - set(tile_ids)
        extra = set(tile_ids) - expected_tile_ids
        raise RuntimeError(f"Tile mismatch: missing={missing}, extra={extra}")

    # Row coverage
    rows_covered: list[int] = []
    tile_map = {t["tile_id"]: t for t in expected_tiles}
    for r in records:
        rs = r.get("row_start")
        rp = r.get("row_stop")
        if not isinstance(rs, int) or not isinstance(rp, int):
            raise RuntimeError(f"Invalid row bounds in record: {rs!r}, {rp!r}")
        if rs < 0 or rp > expected_height or rs >= rp:
            raise RuntimeError(f"Invalid row range [{rs}, {rp})")
        exp_tile = tile_map[r["tile_id"]]
        if rs != exp_tile["row_start"] or rp != exp_tile["row_stop"]:
            raise RuntimeError(
                f"Tile {r['tile_id']}: row bounds [{rs},{rp}) != "
                f"expected [{exp_tile['row_start']},{exp_tile['row_stop']})"
            )
        rows_covered.extend(range(rs, rp))
    if sorted(rows_covered) != list(range(expected_height)):
        raise RuntimeError("Row coverage incomplete or overlapping")

    # Counts validity
    for r in records:
        counts = r.get("counts", [])
        expected_len = (r["row_stop"] - r["row_start"]) * expected_width
        if len(counts) != expected_len:
            raise RuntimeError(
                f"Tile {r['tile_id']}: counts length {len(counts)} != {expected_len}"
            )
        for c in counts:
            if not isinstance(c, int) or isinstance(c, bool) or c < 0 or c > expected_iterations:
                raise RuntimeError(f"Tile {r['tile_id']}: invalid count {c!r}")

    # PID and thread_id
    for r in records:
        pid = r.get("pid")
        tid = r.get("thread_id")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise RuntimeError(f"Tile {r['tile_id']}: invalid pid {pid!r}")
        if not isinstance(tid, int) or isinstance(tid, bool) or tid <= 0:
            raise RuntimeError(f"Tile {r['tile_id']}: invalid thread_id {tid!r}")

    # Timestamps: finite, positive duration, within engine bracket
    engine_start = result.get("engine_start")
    engine_end = result.get("engine_end")
    if not isinstance(engine_start, (int, float)) or not isinstance(engine_end, (int, float)):
        raise RuntimeError("engine_start/engine_end not numeric")
    if not math.isfinite(engine_start) or not math.isfinite(engine_end):
        raise RuntimeError("engine_start/engine_end not finite")
    if engine_end <= engine_start:
        raise RuntimeError("engine_end <= engine_start")

    tol = 1e-6
    for r in records:
        s = r.get("start")
        e = r.get("end")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            raise RuntimeError(f"Tile {r['tile_id']}: non-numeric timestamps")
        if not math.isfinite(s) or not math.isfinite(e):
            raise RuntimeError(f"Tile {r['tile_id']}: non-finite timestamps")
        if e - s <= 0:
            raise RuntimeError(f"Tile {r['tile_id']}: non-positive duration")
        if s < engine_start - tol or e > engine_end + tol:
            raise RuntimeError(
                f"Tile {r['tile_id']}: timestamps [{s},{e}] outside engine bracket "
                f"[{engine_start},{engine_end}]"
            )

    # engine_seconds: finite, positive, <= wall_seconds
    engine_seconds = result.get("engine_seconds")
    if not isinstance(engine_seconds, (int, float)) or isinstance(engine_seconds, bool):
        raise RuntimeError("engine_seconds not numeric")
    if not math.isfinite(engine_seconds) or engine_seconds <= 0:
        raise RuntimeError(f"engine_seconds not finite/positive: {engine_seconds!r}")
    # actual_workers: strict positive integer
    actual_workers = result.get("actual_workers")
    if not isinstance(actual_workers, int) or isinstance(actual_workers, bool) or actual_workers < 1:
        raise RuntimeError(f"actual_workers invalid: {actual_workers!r}")

    # pool_width: strict positive integer
    pool_width = result.get("pool_width")
    if not isinstance(pool_width, int) or isinstance(pool_width, bool) or pool_width < 1:
        raise RuntimeError(f"pool_width invalid: {pool_width!r}")

    # engine_seconds tighter bounds (checked after digest recomputation below)
    if engine_seconds > wall_seconds + 1e-6:
        raise RuntimeError(
            f"engine_seconds ({engine_seconds:.6f}) > wall_seconds ({wall_seconds:.6f}) + 1e-6"
        )
    if engine_seconds > (engine_end - engine_start) + 1e-6:
        raise RuntimeError(
            f"engine_seconds ({engine_seconds:.6f}) > engine_end-engine_start ({engine_end - engine_start:.6f}) + 1e-6"
        )

    # digest: non-empty string, 64 hex chars
    digest = result.get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RuntimeError(f"digest invalid: {digest!r}")

    # Recompute SHA256 from full ordered counts using fixed 3-digit encoding
    import hashlib
    h = hashlib.sha256()
    for r in sorted(records, key=lambda rec: rec["row_start"]):
        for c in r["counts"]:
            h.update(f"{c:03d}".encode("ascii"))
    recomputed = h.hexdigest()
    if recomputed != digest:
        raise RuntimeError(
            f"Digest mismatch: recomputed={recomputed[:16]}... child={digest[:16]}..."
        )
    ref_digest = _compute_reference_digest(expected_width, expected_height, expected_iterations)
    if recomputed != ref_digest:
        raise RuntimeError(
            f"Digest mismatch vs reference: recomputed={recomputed[:16]}... ref={ref_digest[:16]}..."
        )

    # before == after dict
    if before != after:
        raise RuntimeError(f"before/after dicts differ: before={before!r} after={after!r}")

    # Each record runtime_before == runtime_after == before
    for r in records:
        rb = r.get("runtime_before")
        ra = r.get("runtime_after")
        if rb != before or ra != before:
            raise RuntimeError(
                f"Tile {r['tile_id']}: runtime_before/after mismatch"
            )

    # gil_before/gil_after exact expected bool per record
    for r in records:
        if r.get("gil_before") is not expected_gil:
            raise RuntimeError(
                f"Tile {r['tile_id']}: gil_before={r.get('gil_before')!r} expected {expected_gil!r}"
            )
        if r.get("gil_after") is not expected_gil:
            raise RuntimeError(
                f"Tile {r['tile_id']}: gil_after={r.get('gil_after')!r} expected {expected_gil!r}"
            )

    # backend check (top-level result field)
    _BACKEND_LABELS = {
        "gil_on_threads": "thread (forced by env)",
        "gil_off_threads": "thread (free-threaded interpreter)",
        "gil_on_processes": "process",
    }
    expected_backend = _BACKEND_LABELS[expected_mode]
    if result.get("backend") != expected_backend:
        raise RuntimeError(
            f"backend mismatch: {result.get('backend')!r} expected {expected_backend!r}"
        )

    # actual_workers == len(distinct(pid, thread_id))
    distinct = set()
    for r in records:
        distinct.add((r["pid"], r["thread_id"]))
    if actual_workers != len(distinct):
        raise RuntimeError(
            f"actual_workers={actual_workers} != len(distinct(pid,tid))={len(distinct)}"
        )
    if not (1 <= actual_workers <= pool_width):
        raise RuntimeError(
            f"actual_workers={actual_workers} not in [1, pool_width={pool_width}]"
        )
    expected_workers = expected_params["workers"]
    if not (1 <= pool_width <= expected_workers):
        raise RuntimeError(
            f"pool_width={pool_width} not in [1, expected_workers={expected_workers}]"
        )

    # Process mode: distinct PIDs identity; thread mode: one PID
    pids = {r["pid"] for r in records}
    if expected_mode == "gil_on_processes":
        if len(pids) != actual_workers:
            raise RuntimeError(
                f"Process mode: distinct PIDs={len(pids)} != actual_workers={actual_workers}"
            )
    else:
        if len(pids) != 1:
            raise RuntimeError(
                f"Thread mode: expected 1 PID, got {len(pids)}"
            )

    # engine_seconds tighter bounds
    if engine_seconds > wall_seconds + 1e-6:
        raise RuntimeError(
            f"engine_seconds ({engine_seconds:.6f}) > wall_seconds ({wall_seconds:.6f}) + 1e-6"
        )
    if engine_seconds > (engine_end - engine_start) + 1e-6:
        raise RuntimeError(
            f"engine_seconds ({engine_seconds:.6f}) > engine_end-engine_start ({engine_end - engine_start:.6f}) + 1e-6"
        )


def _compute_reference_digest(width: int, height: int, iterations: int) -> str:
    """Compute the reference Mandelbrot image digest independently."""
    import hashlib

    h = hashlib.sha256()
    for y in range(height):
        for x in range(width):
            z = 0j
            c = complex(-2 + 3 * x / (width - 1), -1.2 + 2.4 * y / (height - 1))
            count = 0
            while count < iterations and z.real * z.real + z.imag * z.imag <= 4:
                z = z * z + c
                count += 1
            h.update(f"{count:03d}".encode("ascii"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Deterministic tile plan (mirrors core.make_tiles)
# ---------------------------------------------------------------------------

def _make_tiles(width: int, height: int) -> list[dict]:
    tiles: list[dict] = []
    tile_id = 0
    for row_start in range(0, height, 2):
        row_stop = min(row_start + 2, height)
        tiles.append({"tile_id": tile_id, "row_start": row_start, "row_stop": row_stop})
        tile_id += 1
    return tiles[::2] + tiles[1::2]


# ---------------------------------------------------------------------------
# Median helper
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    if not values:
        raise ValueError("Cannot compute median of empty list")
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ---------------------------------------------------------------------------
# run_benchmark
# ---------------------------------------------------------------------------

def run_benchmark(
    width: int = 96,
    height: int = 64,
    iterations: int = 100,
    workers: int = 2,
    repeats: int = 2,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Run the full free-threading benchmark. Returns a JSON-safe dict."""

    # --- Acquire lock (fail fast) ---
    if not _benchmark_lock.acquire(blocking=False):
        raise RuntimeError(
            "Another run_benchmark call is already in progress. "
            "This function is not re-entrant; wait for it to complete."
        )

    try:
        return _run_benchmark_impl(width, height, iterations, workers, repeats, progress)
    finally:
        _benchmark_lock.release()


def _run_benchmark_impl(
    width: int,
    height: int,
    iterations: int,
    workers: int,
    repeats: int,
    progress: Optional[Callable[[int, int, str], None]],
) -> dict:
    # --- Validate inputs (strict integers, no bool) ---
    _validate_strict_int(width, "width", 2, 384)
    _validate_strict_int(height, "height", 2, 256)
    _validate_strict_int(iterations, "iterations", 1, 300)
    _validate_strict_int(workers, "workers", 1, _MAX_WORKERS)
    _validate_strict_int(repeats, "repeats", 1, 3)

    # --- Effective CPUs ---
    eff = effective_cpus()
    eff_cpus = eff["effective_cpus"]

    # Workers must not exceed effective_cpus
    if workers > eff_cpus:
        raise ValueError(
            f"workers={workers} exceeds effective_cpus={eff_cpus}. "
            f"Reduce workers or increase CPU allocation."
        )

    # --- Ensure process group support ---
    _ensure_process_group_support()

    # --- Total time budget (starts before any probe) ---
    total_deadline = time.monotonic() + _TOTAL_TIMEOUT

    # --- Find interpreter ---
    interpreter = find_free_threading_python()

    # --- Probe interpreter for version and free-threaded status ---
    remaining = total_deadline - time.monotonic() - 2.0
    if remaining <= 0:
        raise RuntimeError(
            f"Total time budget of {_TOTAL_TIMEOUT}s exhausted before probe."
        )
    probe_timeout = min(10.0, remaining)
    probe_info = _probe_interpreter(interpreter, timeout=probe_timeout)
    interpreter_version = probe_info["version"]
    free_threaded = probe_info["free_threaded_build"]

    if not free_threaded:
        raise RuntimeError("Resolved interpreter is not a free-threaded build")

    # --- Locate core ---
    core_path = str(Path(__file__).resolve().parent / _CORE_FILENAME)
    if not os.path.isfile(core_path):
        raise RuntimeError(
            f"Core module not found at {core_path!r}. "
            "Ensure free_threading_core.py is in the same directory."
        )

    # --- Compute reference digest ---
    reference_digest = _compute_reference_digest(width, height, iterations)

    # --- Tile plan ---
    tiles = _make_tiles(width, height)

    # --- Determine expected GIL per mode ---
    expected_gil = {
        "gil_on_threads": True,
        "gil_off_threads": False,
        "gil_on_processes": True,
    }

    # --- Total cases: repeats * 3 modes * 2 roles ---
    total_cases = repeats * len(_MODES) * len(_ROLES)
    completed = 0

    # --- Collect all raw results ---
    all_results: list[dict] = []

    # --- Per-run temporary directory ---
    tmp_dir = tempfile.TemporaryDirectory(prefix="agilab_bench_")
    try:
        for rep in range(repeats):
            for mode in _MODES:
                for role in _ROLES:
                    # Check time budget (reserve >=2s for cleanup)
                    remaining = total_deadline - time.monotonic() - 2.0
                    if remaining <= 0:
                        raise RuntimeError(
                            f"Total time budget of {_TOTAL_TIMEOUT}s exhausted "
                            f"before completing all cases."
                        )
                    child_timeout = min(_CHILD_TIMEOUT, remaining)

                    # Determine workers for this case
                    case_workers = 1 if role == "baseline" else workers

                    params = {
                        "width": width,
                        "height": height,
                        "iterations": iterations,
                        "workers": case_workers,
                        "mode": mode,
                    }

                    # Launch child
                    result, wall = _launch_child(
                        interpreter=interpreter,
                        core_path=core_path,
                        mode=mode,
                        params=params,
                        cwd=tmp_dir.name,
                        timeout=child_timeout,
                    )

                    # Validate
                    _validate_child_result(
                        result=result,
                        expected_params=params,
                        expected_mode=mode,
                        expected_interpreter_version=interpreter_version,
                        expected_free_threaded=True,
                        expected_gil=expected_gil[mode],
                        expected_tiles=tiles,
                        expected_width=width,
                        expected_height=height,
                        expected_iterations=iterations,
                        wall_seconds=wall,
                    )

                    # Verify digest matches reference
                    if result["digest"] != reference_digest:
                        raise RuntimeError(
                            f"Digest mismatch for mode={mode}, role={role}, "
                            f"repeat={rep}: child={result['digest'][:16]}... "
                            f"reference={reference_digest[:16]}..."
                        )

                    # Check total deadline after validation before accepting
                    if time.monotonic() >= total_deadline:
                        raise RuntimeError(
                            f"Total time budget of {_TOTAL_TIMEOUT}s exhausted "
                            f"after validation of mode={mode}, role={role}, repeat={rep}."
                        )

                    # Attach metadata
                    result["role"] = role
                    result["repeat"] = rep
                    result["wall_seconds"] = wall

                    all_results.append(result)

                    completed += 1
                    if progress is not None:
                        progress(completed, total_cases, f"{mode}/{role} rep{rep}")

    finally:
        tmp_dir.cleanup()

    # --- Build summary ---
    summary = _build_summary(all_results, workers, eff)

    # --- Same work verified ---
    digests = {r["digest"] for r in all_results}
    same_work_verified = len(digests) == 1

    # --- Scaling available ---
    scaling_available = workers > 1

    # --- Parameters ---
    parameters = {
        "width": width,
        "height": height,
        "iterations": iterations,
        "workers": workers,
        "repeats": repeats,
    }

    # --- Python build info (version string) ---
    python_build = interpreter_version

    # --- Methodology ---
    methodology = (
        "Each repeat runs three modes (gil_on_threads, gil_off_threads, gil_on_processes), "
        "each with a baseline (1 worker) and parallel (N workers) case. "
        "Cases are executed in isolated child process groups with start_new_session. "
        "The child uses the AGILAB pool engine with the specified executor. "
        "Speedup = baseline median wall / group median wall per mode. "
        "Engine speedup uses engine_seconds medians. "
        "All values are medians across repeats. Slower values are preserved as-is."
    )

    return {
        "runs": all_results,
        "summary": summary,
        "same_work_verified": same_work_verified,
        "digest": reference_digest,
        "hardware": eff,
        "python_build": python_build,
        "parameters": parameters,
        "scaling_available": scaling_available,
        "methodology": methodology,
    }


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(
    all_results: list[dict],
    requested_workers: int,
    eff: dict,
) -> list[dict]:
    """Build six summary rows (3 modes × 2 roles) using medians across repeats."""
    summary: list[dict] = []

    for mode in _MODES:
        for role in _ROLES:
            # Collect results for this mode/role across repeats
            group = [r for r in all_results if r["mode"] == mode and r["role"] == role]
            if not group:
                continue

            # Baseline for this mode (role=baseline)
            baseline_group = [r for r in all_results if r["mode"] == mode and r["role"] == "baseline"]
            baseline_wall_med = _median([r["wall_seconds"] for r in baseline_group])
            baseline_engine_med = _median([r["engine_seconds"] for r in baseline_group])

            # Group medians
            wall_med = _median([r["wall_seconds"] for r in group])
            engine_med = _median([r["engine_seconds"] for r in group])

            # Speedups
            speedup = baseline_wall_med / wall_med if wall_med > 0 else 1.0
            engine_speedup = baseline_engine_med / engine_med if engine_med > 0 else 1.0

            # Actual workers: minimum observed across repeats
            actual_workers_list = [r["actual_workers"] for r in group]
            actual_workers_min = min(actual_workers_list)

            # Pool width: from the group (should be consistent)
            pool_width = group[0]["pool_width"]

            # Workers for this role
            role_workers = 1 if role == "baseline" else requested_workers

            row = {
                "mode": mode,
                "role": role,
                "workers": role_workers,
                "actual_workers": actual_workers_min,
                "pool_width": pool_width,
                "wall_seconds": wall_med,
                "engine_seconds": engine_med,
                "speedup": speedup,
                "engine_speedup": engine_speedup,
                "observed_worker_counts": actual_workers_list,
            }
            summary.append(row)

    return summary


# ---------------------------------------------------------------------------
# Strict integer validation
# ---------------------------------------------------------------------------

def _validate_strict_int(value: Any, name: str, lo: int, hi: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a strict integer, got {type(value).__name__}")
    if not (lo <= value <= hi):
        raise ValueError(f"{name} must be in [{lo}, {hi}], got {value}")


# ---------------------------------------------------------------------------
# Module-level: no benchmark execution at import
# ---------------------------------------------------------------------------