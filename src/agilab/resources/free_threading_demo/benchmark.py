"""Bounded stdlib-only child orchestration; no timed results are cached."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import tempfile
import threading
import time

from free_threading_core import (MODES, image_digest, integer, reduce_tiles,
                                 tile_plan, validate_mode, validate_parameters, verify_runtime)

LABELS = {
    "gil_on_threads": "GIL-on threads · same free-threaded build",
    "gil_off_threads": "GIL-off threads · AGILAB auto",
    "gil_on_processes": "GIL-on processes · spawn",
}
_LOCK = threading.Lock()
CHILD_TIMEOUT = 15.0
TOTAL_TIMEOUT = 50.0


class BusyError(RuntimeError):
    pass


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def _cgroup_limits():
    """Read v1/v2 CPU quotas at the process's cgroup and its ancestors."""
    limits = []
    memberships = [line.split(":", 2) for line in _read("/proc/self/cgroup").splitlines()]
    for line in _read("/proc/self/mountinfo").splitlines():
        fields = line.split()
        try:
            sep = fields.index("-")
            kind, options = fields[sep + 1], fields[sep + 3]
            root, mount = fields[3], fields[4]
        except (ValueError, IndexError):
            continue
        if kind not in ("cgroup", "cgroup2"):
            continue
        if kind == "cgroup" and "cpu" not in options.split(","):
            continue
        for entry in memberships:
            if len(entry) != 3:
                continue
            _, controllers, member = entry
            if kind == "cgroup2" and controllers or kind == "cgroup" and "cpu" not in controllers.split(","):
                continue
            relative = member[len(root):].lstrip("/") if member.startswith(root) else member.lstrip("/")
            base = Path(mount)
            current = base / relative
            while current == base or base in current.parents:
                try:
                    if kind == "cgroup2":
                        quota, period = _read(current / "cpu.max").split()
                    else:
                        quota = _read(current / "cpu.cfs_quota_us")
                        period = _read(current / "cpu.cfs_period_us")
                    if quota != "max" and float(quota) > 0 and float(period) > 0:
                        limits.append(float(quota) / float(period))
                except (ValueError, ZeroDivisionError):
                    pass
                if current == base:
                    break
                current = current.parent
    return limits


def effective_cpus():
    limits = {"os.cpu_count": os.cpu_count() or 1}
    if hasattr(os, "process_cpu_count"):
        limits["os.process_cpu_count"] = os.process_cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        try:
            limits["affinity"] = len(os.sched_getaffinity(0))
        except OSError:
            pass
    for key in ("CPU_CORES", "SPACE_CPU_CORES"):
        if key in os.environ:
            try:
                value = float(os.environ[key])
                if not math.isfinite(value) or value <= 0:
                    raise ValueError
                limits[key] = value
            except ValueError as exc:
                raise ValueError(f"{key} must contain a positive finite CPU allowance") from exc
    quotas = _cgroup_limits()
    if quotas:
        limits["cgroup_quota"] = min(quotas)
    allowance = min(limits.values())
    return {"effective_cpus": max(1, min(8, math.floor(allowance))),
            "cpu_allowance": allowance, "limits": limits, "app_cap": 8}


def interpreter():
    selected = os.environ.get("AGILAB_FREE_THREADING_PYTHON") or shutil.which("python3.14t")
    found = shutil.which(selected) if selected else None
    if not found:
        raise RuntimeError("Free-threaded Python is missing. Set AGILAB_FREE_THREADING_PYTHON "
                           "to an installed python3.14t executable; timings cannot be simulated.")
    return found


def child_environment(mode, workers):
    validate_mode(mode)
    integer("workers", workers, 1, 8)
    env = {k: v for k, v in os.environ.items()
           if k != "PYTHON_GIL" and not k.startswith("AGILAB_POOL_")}
    env.update(AGILAB_POOL_EXECUTOR=MODES[mode][1], AGILAB_POOL_MAX_WORKERS=str(workers),
               PYTHONDONTWRITEBYTECODE="1")
    return env


@contextmanager
def benchmark_lock():
    """Serialize sessions and server processes on this host, outside the bundle."""
    if os.name != "posix":
        raise RuntimeError("This runner requires POSIX process groups and file locking.")
    import fcntl
    if not _LOCK.acquire(blocking=False):
        raise BusyError("CPU lab is busy with another analysis. Try again after it finishes.")
    descriptor = None
    try:
        path = Path(tempfile.gettempdir()) / f"agilab-free-threading-{os.getuid()}.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BusyError("CPU lab is busy with another analysis. Try again after it finishes.") from exc
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        _LOCK.release()


def _kill_group(process, sig):
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def _stop_child(process):
    # New sessions make this group task-owned. Kill the group even if the leader
    # has already exited, because descendants may still hold its output pipes.
    _kill_group(process, signal.SIGTERM)
    try:
        process.communicate(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    finally:
        _kill_group(process, signal.SIGKILL)
        process.communicate(timeout=2)
        process.wait(timeout=2)


def _communicate(command, payload, env, timeout):
    begun = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="free-threading-child-") as scratch:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, env=env,
                                   cwd=scratch, start_new_session=True)
        try:
            stdout, stderr = process.communicate(payload, timeout=timeout)
        except BaseException:
            _stop_child(process)
            raise
        elapsed = time.perf_counter() - begun
        if process.returncode:
            raise RuntimeError("Benchmark child failed. Check AGILAB_FREE_THREADING_PYTHON and "
                               "its free-threaded build/GIL support. " + stderr[-1800:])
    return stdout, elapsed


def validate_result(result, width, height, iterations, workers, mode):
    if result.get("mode") != mode or result.get("workers") != workers:
        raise ValueError("Mismatched mode or worker count")
    expected_parameters = {"width": width, "height": height, "iterations": iterations, "tile_rows": 3}
    if result.get("parameters") != expected_parameters:
        raise ValueError("Mismatched workload parameters")
    plan = tile_plan(width, height, iterations)
    if result.get("tile_plan") != [list(item) for item in plan]:
        raise ValueError("Mismatched tile plan")
    for key in ("before", "after"):
        verify_runtime(result[key], mode)
    if result["before"] != result["after"]:
        raise ValueError("Runtime build/GIL changed during execution")
    expected_backend = "process" if mode == "gil_on_processes" else "thread"
    if not result.get("backend", "").startswith(expected_backend):
        raise ValueError("Unexpected AGILAB backend")
    integer("actual_workers", result["actual_workers"], 1, workers)
    counts = reduce_tiles(result["records"], plan)
    if image_digest(counts) != result.get("digest"):
        raise ValueError("Mismatched complete-image digest")
    for record in result["records"]:
        if record.get("gil_enabled") is not bool(MODES[mode][0]):
            raise ValueError("Unexpected worker GIL state")
    for key in ("engine_seconds", "wall_seconds"):
        number = result[key]
        if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
            raise ValueError("Invalid measured timing")
    if result["engine_seconds"] > result["wall_seconds"]:
        raise ValueError("Engine time exceeds end-to-end measurement")
    return counts


def run_case(width, height, iterations, workers, mode, timeout=CHILD_TIMEOUT):
    validate_parameters(width, height, iterations, workers)
    validate_mode(mode)
    _validate_timeout(timeout, CHILD_TIMEOUT)
    if workers > effective_cpus()["effective_cpus"]:
        raise ValueError("Requested workers exceed the effective CPU allowance")
    # Disable site initialization and Python environment injection: the measured
    # interpreter imports only this adapter, the pool engine and the stdlib.
    command = [interpreter(), "-B", "-E", "-S", "-X", f"gil={MODES[mode][0]}",
               str(Path(__file__).with_name("free_threading_core.py").resolve())]
    payload = json.dumps(dict(width=width, height=height, iterations=iterations, workers=workers, mode=mode))
    try:
        output, elapsed = _communicate(command, payload, child_environment(mode, workers), timeout)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Benchmark child timed out; its process group was terminated and reaped.") from exc
    result = json.loads(output)
    result["wall_seconds"] = elapsed
    validate_result(result, width, height, iterations, workers, mode)
    return result


def _validate_timeout(value, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"timeout must be a positive finite number <= {maximum}")


def run_benchmark(width=192, height=128, iterations=160, workers=2, repeats=2,
                  progress=None, total_timeout=TOTAL_TIMEOUT):
    validate_parameters(width, height, iterations, workers)
    integer("repeats", repeats, 1, 3)
    _validate_timeout(total_timeout, TOTAL_TIMEOUT)
    hardware = effective_cpus()
    if workers > hardware["effective_cpus"]:
        raise ValueError("Requested workers exceed the effective CPU allowance")
    with benchmark_lock():
        started = time.monotonic()
        runs = []
        digest = version = None
        # Rotate mode order each repeat to reduce systematic order bias.
        modes = list(MODES)
        for repeat in range(repeats):
            for mode in modes[repeat % 3:] + modes[:repeat % 3]:
                cases = [("baseline", 1), ("scaled", workers)]
                if repeat % 2:
                    cases.reverse()
                for role, count in cases:
                    remaining = total_timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise TimeoutError("Total analysis time budget exhausted")
                    run = run_case(width, height, iterations, count, mode, min(CHILD_TIMEOUT, remaining))
                    if time.monotonic() - started > total_timeout:
                        raise TimeoutError("Total analysis time budget exhausted")
                    if digest is None:
                        digest, version = run["digest"], run["before"]["version"]
                    if run["digest"] != digest or run["before"]["version"] != version:
                        raise ValueError("Same-work verification failed: image or Python build differs")
                    run.update(repeat=repeat + 1, role=role)
                    runs.append(run)
                    if progress:
                        progress(len(runs), 6 * repeats, f"{LABELS[mode]} · {count} worker(s)")
        summaries = []
        for mode in MODES:
            baseline = [r for r in runs if r["mode"] == mode and r["role"] == "baseline"]
            base_wall = statistics.median(r["wall_seconds"] for r in baseline)
            base_engine = statistics.median(r["engine_seconds"] for r in baseline)
            for role in ("baseline", "scaled"):
                group = [r for r in runs if r["mode"] == mode and r["role"] == role]
                wall = statistics.median(r["wall_seconds"] for r in group)
                engine = statistics.median(r["engine_seconds"] for r in group)
                summaries.append({"mode": mode, "label": LABELS[mode], "role": role,
                                  "workers": group[0]["actual_workers"], "wall_seconds": wall,
                                  "engine_seconds": engine, "speedup": base_wall / wall,
                                  "engine_speedup": base_engine / engine,
                                  "pixels_per_second": width * height / wall})
        return {"scope": "local CPU scaling", "created_utc": datetime.now(timezone.utc).isoformat(),
                "parameters": dict(width=width, height=height, iterations=iterations,
                                   workers=workers, repeats=repeats),
                "hardware": hardware, "same_work_verified": True, "digest": digest,
                "python_build": version, "runs": runs, "summary": summaries,
                "total_seconds": time.monotonic() - started}
