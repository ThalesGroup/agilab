#!/usr/bin/env python3
"""energy_runner.py – Bounded isolated AGILAB pool runner for PyPSA energy scenarios."""

import json
import math
import os
import signal
import sys
import time
import tempfile
import threading
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Sequence

# ---------------------------------------------------------------------------
# Core imports
# ---------------------------------------------------------------------------
from energy_core import (
    default_settings,
    validate_settings,
    solve_scenario,
    make_batch,
    cpu_limits,
)

# ---------------------------------------------------------------------------
# AGILAB pool engine imports
# ---------------------------------------------------------------------------
import agilab_pool
from agilab_pool import PoolFrameHooks, resolve_pool_width, run_works

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TOTAL_BUDGET = 150.0
_SINGLE_CHILD_TIMEOUT = 30.0
_BATCH_CHILD_TIMEOUT = 135.0
_CLEANUP_RESERVE = 2.0
_SIGTERM_GRACE = 0.25
_REAP_TIMEOUT = 1.0
_BARRIER_TIMEOUT = 20.0
_VALID_BATCH_LENGTHS = (4, 8, 12)
_MAX_WORKERS = 4

# ---------------------------------------------------------------------------
# Module-level nonblocking lock
# ---------------------------------------------------------------------------
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# AGILAB worker adapter (module-level for spawn pickling)
# ---------------------------------------------------------------------------


class _EnergyWorker:
    """Spawn-picklable worker adapter for the AGILAB pool engine."""

    def __init__(self, items: list, workers: int, pool_width: int):
        self._worker_id = 0
        self._mode = 1  # pool bit
        self._work_done_chunk = 0
        self._items = items
        self._workers = workers
        self._pool_width = pool_width
        self.args = {"pool_max_workers": workers, "pool_item_timeout": 15}
        self._collected_frames: list = []
        self._collected_labels: list = []
        self._barrier = None

    def work_init(self) -> None:
        self._collected_frames = []
        self._collected_labels = []

    def pool_init(self, pool_vars: Any) -> None:
        if self._pool_width > 1 and pool_vars is not None:
            self._barrier = pool_vars
            self._barrier.wait()

    def get_pool_vars(self) -> Any:
        return self._barrier

    @property
    def pool_vars(self) -> Any:
        return self._barrier

    def work_pool(self, item: dict) -> list:
        case_idx = item["case"]
        settings = item["settings"]
        pid = os.getpid()
        start = time.perf_counter()
        result = solve_scenario(settings)
        end = time.perf_counter()
        record = {
            "case": case_idx,
            "pid": pid,
            "start_monotonic": start,
            "end_monotonic": end,
            "result": result,
        }
        return [record]

    def work_done(self, frame: Any) -> None:
        self._collected_frames.append(frame)
        self._work_done_chunk += 1

    def stop(self) -> None:
        pass

    def _exec_multi_process(self, workers_plan: Any, workers_plan_metadata: Any) -> None:
        hooks = _build_hooks()
        agilab_pool.exec_multi_process(self, workers_plan, workers_plan_metadata, hooks)

    def _exec_mono_process(self, workers_plan: Any, workers_plan_metadata: Any) -> None:
        hooks = _build_hooks()
        agilab_pool.exec_mono_process(self, workers_plan, workers_plan_metadata, hooks)

    def collected(self) -> list:
        return self._collected_frames


# ---------------------------------------------------------------------------
# Module-level hooks (spawn-picklable)
# ---------------------------------------------------------------------------


def _process_pool_factory(max_workers: int, initializer: Callable | None = None,
                          initargs: tuple = ()) -> ProcessPoolExecutor:
    ctx = multiprocessing.get_context("spawn")
    return ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=initializer,
        initargs=initargs,
        mp_context=ctx,
    )


def _is_frame(obj: Any) -> bool:
    return isinstance(obj, list)


def _is_empty(obj: Any) -> bool:
    return not obj


def _concat_labeled(frames: Sequence, labels: Sequence) -> list:
    out = []
    for f in frames:
        if f:
            out.extend(f)
    return out


def _empty_frame() -> list:
    return []


def _build_hooks() -> PoolFrameHooks:
    return PoolFrameHooks(
        family="energy",
        executor_kind="process",
        executor_factory=_process_pool_factory,
        is_frame=_is_frame,
        is_empty=_is_empty,
        concat_labeled=_concat_labeled,
        empty_frame=_empty_frame,
    )


# ---------------------------------------------------------------------------
# Child-side execution (runs inside the isolated subprocess)
# ---------------------------------------------------------------------------


def _child_run_batch(items: list, workers: int) -> dict:
    """Execute the AGILAB pool engine on the given items with the given worker count."""
    pool_width = resolve_pool_width([len(items)], None, executor_kind="process")
    pool_width = max(1, min(pool_width, workers))

    worker = _EnergyWorker(items, workers, pool_width)
    workers_plan = [[items]]  # worker 0 gets one chunk containing all items

    # Create shared barrier for pool_width > 1 so all workers synchronize
    if pool_width > 1:
        worker._barrier = multiprocessing.get_context("spawn").Barrier(
            pool_width, timeout=_BARRIER_TIMEOUT
        )

    engine_start = time.perf_counter()
    engine_seconds = run_works(worker, workers_plan, None)
    engine_end = time.perf_counter()

    # Collect all records from work_done frames
    all_records = []
    for frame in worker.collected():
        if isinstance(frame, list):
            all_records.extend(frame)

    # Sort by case index
    all_records.sort(key=lambda r: r["case"])

    return {
        "rows": all_records,
        "workers": workers,
        "pool_width": pool_width,
        "engine_start": engine_start,
        "engine_end": engine_end,
        "engine_seconds": engine_seconds,
    }


# ---------------------------------------------------------------------------
# Child CLI entry point
# ---------------------------------------------------------------------------


def _child_main() -> None:
    """Entry point for child subprocess. Expects --single or --batch on argv."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--single", type=str, default=None, help="JSON settings for single scenario")
    parser.add_argument("--batch", type=str, default=None, help="JSON batch of settings")
    parser.add_argument("--workers", type=int, default=1, help="Worker count for batch mode")
    args = parser.parse_args()

    if args.single is not None:
        # Single scenario mode
        try:
            settings = json.loads(args.single)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"invalid settings JSON: {e}"}), file=sys.stderr)
            sys.exit(1)

        try:
            validate_settings(settings)
        except Exception as e:
            print(json.dumps({"error": f"settings validation failed: {e}"}), file=sys.stderr)
            sys.exit(1)

        items = [{"case": 0, "settings": settings}]
        result = _child_run_batch(items, 1)
        print(json.dumps(result, allow_nan=False))

    elif args.batch is not None:
        # Batch mode
        try:
            batch = json.loads(args.batch)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"invalid batch JSON: {e}"}), file=sys.stderr)
            sys.exit(1)

        if not isinstance(batch, list) or len(batch) not in _VALID_BATCH_LENGTHS:
            print(json.dumps({"error": f"batch must be list of length 4, 8, or 12"}), file=sys.stderr)
            sys.exit(1)

        if not isinstance(args.workers, int) or isinstance(args.workers, bool):
            print(json.dumps({"error": "workers must be a strict int"}), file=sys.stderr)
            sys.exit(1)
        max_w = min(_MAX_WORKERS, cpu_limits()["effective_cpus"])
        if not (1 <= args.workers <= max_w):
            print(json.dumps({"error": f"workers must be 1..{max_w}"}), file=sys.stderr)
            sys.exit(1)

        for i, s in enumerate(batch):
            try:
                validate_settings(s)
            except Exception as e:
                print(json.dumps({"error": f"batch[{i}] validation failed: {e}"}), file=sys.stderr)
                sys.exit(1)

        items = [{"case": i, "settings": s} for i, s in enumerate(batch)]
        result = _child_run_batch(items, args.workers)
        print(json.dumps(result, allow_nan=False))

    else:
        print(json.dumps({"error": "must specify --single or --batch"}), file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Parent-side: bounded subprocess lifecycle
# ---------------------------------------------------------------------------


def _build_child_env() -> dict:
    """Build private environment for child: single-threaded BLAS, process executor."""
    env = dict(os.environ)
    # Clear inherited AGILAB_POOL_* overrides
    for k in list(env.keys()):
        if k.startswith("AGILAB_POOL_"):
            del env[k]
    env["AGILAB_POOL_EXECUTOR"] = "process"
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"
    return env


def _cleanup_process_group(proc) -> None:
    """Bounded cleanup of the owned process group. Must be called in finally."""
    if proc is None:
        return
    pgid = proc.pid  # start_new_session=True means pgid == pid

    try:
        # Check if group still exists by trying to signal
        os.killpg(pgid, 0)
        group_exists = True
    except (ProcessLookupError, OSError):
        group_exists = False

    if group_exists:
        # SIGTERM to group
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

        # Wait up to 0.25s for group to die
        deadline = time.monotonic() + _SIGTERM_GRACE
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, OSError):
                break
            time.sleep(0.02)

        # Check again
        try:
            os.killpg(pgid, 0)
            still_alive = True
        except (ProcessLookupError, OSError):
            still_alive = False

        if still_alive:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    # Reap the leader
    try:
        proc.wait(timeout=_REAP_TIMEOUT)
    except Exception:
        # Leader may already be reaped or unresponsive; try kill
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=_REAP_TIMEOUT)
        except Exception:
            raise RuntimeError(f"Failed to reap child process {pgid}")


def _launch_child_safe(args: list, timeout: float, cwd: str, env: dict) -> tuple:
    """
    Launch child, return (stdout_text, wall_seconds, success).
    Wall time includes cleanup.
    """
    runner_path = os.path.abspath(__file__)
    cmd = [sys.executable, runner_path] + args

    import subprocess

    wall_start = time.perf_counter()
    proc = None
    stdout_text = ""
    success = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            stdout_text = stdout.decode("utf-8", errors="replace")
            success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            success = False
    finally:
        _cleanup_process_group(proc)

    wall_seconds = time.perf_counter() - wall_start
    return stdout_text, wall_seconds, success


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_workers(workers: Any) -> int:
    if not isinstance(workers, int) or isinstance(workers, bool):
        raise ValueError(f"workers must be a strict int, got {type(workers).__name__}")
    max_w = min(_MAX_WORKERS, cpu_limits()["effective_cpus"])
    if not (1 <= workers <= max_w):
        raise ValueError(f"workers must be in 1..{max_w}, got {workers}")
    return workers


def _validate_batch(batch: Any) -> list:
    if not isinstance(batch, list):
        raise ValueError("batch must be a list")
    if len(batch) not in _VALID_BATCH_LENGTHS:
        raise ValueError(f"batch length must be one of {_VALID_BATCH_LENGTHS}, got {len(batch)}")
    for i, s in enumerate(batch):
        validate_settings(s)
    return list(batch)


def _validate_row_record(rec: dict, expected_case: int, expected_settings: dict) -> None:
    """Validate a single row record from the child."""
    if not isinstance(rec, dict):
        raise ValueError(f"row record must be dict, got {type(rec).__name__}")

    case = rec.get("case")
    if not isinstance(case, int) or isinstance(case, bool):
        raise ValueError(f"case must be strict int, got {case!r}")
    if case != expected_case:
        raise ValueError(f"case mismatch: expected {expected_case}, got {case}")

    pid = rec.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError(f"pid must be positive int, got {pid!r}")

    sm = rec.get("start_monotonic")
    em = rec.get("end_monotonic")
    if not isinstance(sm, (int, float)) or not math.isfinite(sm):
        raise ValueError(f"start_monotonic not finite: {sm!r}")
    if not isinstance(em, (int, float)) or not math.isfinite(em):
        raise ValueError(f"end_monotonic not finite: {em!r}")
    if em <= sm:
        raise ValueError(f"solving interval non-positive: start={sm}, end={em}")

    result = rec.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"result must be dict, got {type(result).__name__}")

    # Validate result settings match expected
    res_settings = result.get("settings")
    if res_settings != expected_settings:
        raise ValueError(f"result.settings mismatch for case {case}")

    # Validate solver metadata
    solver = result.get("solver")
    if not isinstance(solver, dict):
        raise ValueError(f"solver metadata missing for case {case}")
    if solver.get("name") != "highs":
        raise ValueError(f"solver name must be 'highs', got {solver.get('name')!r}")
    threads = solver.get("threads")
    if type(threads) is not int or threads != 1:
        raise ValueError(f"solver threads must be strict int 1, got {threads!r}")


def _validate_branch(branch: dict, batch: list, workers: int) -> None:
    """Validate a full branch (sequential or parallel) result."""
    rows = branch.get("rows")
    if not isinstance(rows, list):
        raise ValueError("branch rows must be a list")
    if len(rows) != len(batch):
        raise ValueError(f"expected {len(batch)} rows, got {len(rows)}")

    # Check each row
    seen_cases = set()
    for i, rec in enumerate(rows):
        _validate_row_record(rec, i, batch[i])
        seen_cases.add(i)

    if seen_cases != set(range(len(batch))):
        raise ValueError(f"missing or duplicate cases: {seen_cases}")

    # Validate engine timing
    es = branch.get("engine_start")
    ee = branch.get("engine_end")
    esec = branch.get("engine_seconds")
    if not isinstance(es, (int, float)) or isinstance(es, bool) or not math.isfinite(es):
        raise ValueError("engine_start not finite")
    if not isinstance(ee, (int, float)) or isinstance(ee, bool) or not math.isfinite(ee):
        raise ValueError("engine_end not finite")
    if not isinstance(esec, (int, float)) or isinstance(esec, bool) or not math.isfinite(esec) or esec <= 0:
        raise ValueError(f"engine_seconds must be positive finite, got {esec!r}")

    # engine_seconds <= engine_end - engine_start (with tolerance)
    engine_span = ee - es
    if esec > engine_span + 1e-6:
        raise ValueError(f"engine_seconds={esec} > engine span={engine_span}")

    # wall_seconds: strictly finite positive, excluding bool
    ws = branch.get("wall_seconds")
    if not isinstance(ws, (int, float)) or isinstance(ws, bool) or not math.isfinite(ws) or ws <= 0:
        raise ValueError(f"wall_seconds must be strictly positive finite, got {ws!r}")

    # engine span must not exceed wall_seconds (with tiny tolerance)
    if engine_span > ws + 1e-6:
        raise ValueError(f"engine_span={engine_span} > wall_seconds={ws}")

    # All solving intervals within engine interval
    for rec in rows:
        if rec["start_monotonic"] < es - 1e-6 or rec["end_monotonic"] > ee + 1e-6:
            raise ValueError(
                f"solving interval [{rec['start_monotonic']}, {rec['end_monotonic']}]"
                f" outside engine interval [{es}, {ee}]"
            )

    # Workers and pool width
    w = branch.get("workers")
    pw = branch.get("pool_width")
    if w != workers:
        raise ValueError(f"branch workers={w} != expected {workers}")
    if not isinstance(pw, int) or isinstance(pw, bool) or pw < 1:
        raise ValueError(f"pool_width must be positive int, got {pw!r}")
    if pw > workers:
        raise ValueError(f"pool_width={pw} > workers={workers}")

    # actual_workers
    pids = set(r["pid"] for r in rows)
    actual_workers = len(pids)
    if actual_workers < 1 or actual_workers > pw:
        raise ValueError(f"actual_workers={actual_workers} outside [1, pool_width={pw}]")
    branch["actual_workers"] = actual_workers


def _validate_physics(result: dict, settings: dict) -> None:
    """Independently validate physical correctness of a solve result."""
    import numpy as np

    status = result.get("status")
    hours = settings["hours"]

    if status in ("optimal", "feasible"):
        # Must have incumbent
        solver = result.get("solver", {})
        if solver.get("incumbent") is not True:
            raise ValueError(f"status={status} but incumbent is not True")

        obj = result.get("objective")
        if not isinstance(obj, (int, float)) or not math.isfinite(obj):
            raise ValueError(f"objective not finite for status={status}: {obj!r}")

        modules = result.get("modules")
        if not isinstance(modules, int) or isinstance(modules, bool):
            raise ValueError(f"modules must be int for feasible result: {modules!r}")

        capacity = result.get("capacity_mw")
        if not isinstance(capacity, (int, float)) or not math.isfinite(capacity):
            raise ValueError(f"capacity_mw not finite: {capacity!r}")

        # Arrays
        dispatch = result.get("dispatch", [])
        active = result.get("active_modules", [])
        solar = result.get("solar", [])
        shed = result.get("shed", [])
        startup = result.get("startup", [])
        shutdown = result.get("shutdown", [])

        for name, arr in [("dispatch", dispatch), ("active_modules", active),
                          ("solar", solar), ("shed", shed), ("startup", startup),
                          ("shutdown", shutdown)]:
            if len(arr) != hours:
                raise ValueError(f"{name} length {len(arr)} != hours {hours}")
            for v in arr:
                if not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError(f"{name} contains non-finite value: {v!r}")

        dispatch_a = np.array(dispatch, dtype=float)
        active_a = np.array(active, dtype=float)
        solar_a = np.array(solar, dtype=float)
        shed_a = np.array(shed, dtype=float)
        startup_a = np.array(startup, dtype=float)
        shutdown_a = np.array(shutdown, dtype=float)

        # Reconstruct demand and solar profiles
        from energy_core import _demand_profile, _solar_profile
        demand = _demand_profile(hours, settings["demand_multiplier"])
        solar_pu = _solar_profile(hours)

        # Validate returned demand and solar_available arrays against reconstructed profiles
        demand_ret = result.get("demand", [])
        solar_avail_ret = result.get("solar_available", [])
        if len(demand_ret) != hours:
            raise ValueError(f"demand length {len(demand_ret)} != hours {hours}")
        for v in demand_ret:
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"demand contains non-finite: {v!r}")
        if len(solar_avail_ret) != hours:
            raise ValueError(f"solar_available length {len(solar_avail_ret)} != hours {hours}")
        for v in solar_avail_ret:
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"solar_available contains non-finite: {v!r}")
        solar_avail_exp = settings["solar_capacity"] * solar_pu
        tol = 1e-5
        for i in range(hours):
            if abs(demand_ret[i] - demand[i]) > tol:
                raise ValueError(f"demand[{i}]={demand_ret[i]} != expected {demand[i]}")
            if abs(solar_avail_ret[i] - solar_avail_exp[i]) > tol:
                raise ValueError(f"solar_available[{i}]={solar_avail_ret[i]} != expected {solar_avail_exp[i]}")

        # Integer checks
        tol = 1e-5
        if abs(modules - round(modules)) > tol:
            raise ValueError(f"modules={modules} not integer")
        if not np.all(np.abs(active_a - np.round(active_a)) <= tol):
            raise ValueError("active_modules not integer within tolerance")

        modules_i = int(round(modules))
        active_i = np.round(active_a).astype(int)

        # Bounds
        if modules_i < 0 or modules_i > settings["max_modules"]:
            raise ValueError(f"modules={modules_i} out of [0, {settings['max_modules']}]")
        if np.any(active_i < 0) or np.any(active_i > modules_i):
            raise ValueError("active out of [0, installed]")

        # Capacity
        expected_cap = modules_i * settings["module_mw"]
        if abs(capacity - expected_cap) > tol:
            raise ValueError(f"capacity={capacity} != modules*module_mw={expected_cap}")

        # Gas bounds
        gas_lo = settings["min_loading"] * settings["module_mw"] * active_i
        gas_hi = settings["module_mw"] * active_i
        if np.any(dispatch_a < gas_lo - tol) or np.any(dispatch_a > gas_hi + tol):
            raise ValueError("dispatch outside bounds")

        # Solar
        solar_avail = settings["solar_capacity"] * solar_pu
        if np.any(solar_a < -tol):
            raise ValueError("solar negative")
        if np.any(solar_a > solar_avail + tol):
            raise ValueError("solar exceeds available")

        # Shed
        if np.any(shed_a < -tol):
            raise ValueError("shed negative")
        if not settings["allow_shedding"] and np.any(shed_a > tol):
            raise ValueError("shedding present but not allowed")
        if np.any(shed_a > demand + tol):
            raise ValueError("shed exceeds demand")

        # Balance
        balance = dispatch_a + solar_a + shed_a - demand
        if np.max(np.abs(balance)) > tol:
            raise ValueError(f"balance residual {np.max(np.abs(balance)):.6f} exceeds tol")

        # Transitions
        exp_startup = np.zeros(hours)
        exp_shutdown = np.zeros(hours)
        prev = 0
        for i in range(hours):
            exp_startup[i] = max(active_i[i] - prev, 0)
            exp_shutdown[i] = max(prev - active_i[i], 0)
            prev = active_i[i]
        if np.max(np.abs(startup_a - exp_startup)) > tol:
            raise ValueError("startup mismatch with derived transitions")
        if np.max(np.abs(shutdown_a - exp_shutdown)) > tol:
            raise ValueError("shutdown mismatch with derived transitions")

        # Objective reconstruction
        investment = settings["investment_cost"] * expected_cap
        fuel = float(np.sum(dispatch_a * settings["marginal_cost"]))
        standby = float(np.sum(active_i * settings["standby_cost"]))
        startup_cost = float(np.sum(exp_startup * settings["startup_cost"]))
        shed_cost = float(np.sum(shed_a * 100000.0))
        total = investment + fuel + standby + startup_cost + shed_cost

        abs_tol = 1e-4
        rel_tol = 1e-7
        if abs(total - obj) > abs_tol + rel_tol * abs(obj):
            raise ValueError(
                f"objective mismatch: reconstructed={total:.6f} vs solver={obj:.6f}"
            )

    elif status == "infeasible":
        solver = result.get("solver", {})
        if solver.get("incumbent") is not False:
            raise ValueError(f"status=infeasible but incumbent is not False")
        if result.get("objective") is not None:
            raise ValueError("infeasible result must have objective=None")
        if result.get("modules") is not None:
            raise ValueError("infeasible result must have modules=None")
        if result.get("capacity_mw") is not None:
            raise ValueError("infeasible result must have capacity_mw=None")
        for name in ("dispatch", "active_modules", "solar", "shed", "startup", "shutdown"):
            arr = result.get(name, [])
            if len(arr) != 0:
                raise ValueError(f"infeasible result must have empty {name}, got len={len(arr)}")

        # Infeasible results may still contain valid demand/solar_available profiles
        from energy_core import _demand_profile, _solar_profile
        demand_ret = result.get("demand", [])
        solar_avail_ret = result.get("solar_available", [])
        if len(demand_ret) != hours:
            raise ValueError(f"infeasible demand length {len(demand_ret)} != hours {hours}")
        for v in demand_ret:
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"infeasible demand contains non-finite: {v!r}")
        if len(solar_avail_ret) != hours:
            raise ValueError(f"infeasible solar_available length {len(solar_avail_ret)} != hours {hours}")
        for v in solar_avail_ret:
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"infeasible solar_available contains non-finite: {v!r}")
        demand_exp = _demand_profile(hours, settings["demand_multiplier"])
        solar_avail_exp = settings["solar_capacity"] * _solar_profile(hours)
        tol = 1e-5
        for i in range(hours):
            if abs(demand_ret[i] - demand_exp[i]) > tol:
                raise ValueError(f"infeasible demand[{i}]={demand_ret[i]} != expected {demand_exp[i]}")
            if abs(solar_avail_ret[i] - solar_avail_exp[i]) > tol:
                raise ValueError(f"infeasible solar_available[{i}]={solar_avail_ret[i]} != expected {solar_avail_exp[i]}")

    else:
        # error or unknown status
        raise ValueError(f"unexpected status '{status}' in benchmark validation")


def _compare_results(seq_rows: list, par_rows: list, batch: list) -> bool:
    """Compare sequential and parallel results by case index."""
    if len(seq_rows) != len(par_rows):
        return False

    for i in range(len(seq_rows)):
        s_res = seq_rows[i]["result"]
        p_res = par_rows[i]["result"]

        # Same settings
        if s_res.get("settings") != p_res.get("settings"):
            return False

        # Same status
        s_status = s_res.get("status")
        p_status = p_res.get("status")
        if s_status != p_status:
            return False

        if s_status in ("optimal", "feasible"):
            s_obj = s_res.get("objective")
            p_obj = p_res.get("objective")
            if s_obj is None or p_obj is None:
                return False
            if not isinstance(s_obj, (int, float)) or not math.isfinite(s_obj):
                return False
            if not isinstance(p_obj, (int, float)) or not math.isfinite(p_obj):
                return False
            # Compatible objectives within tolerance
            abs_tol = 1e-4
            rel_tol = 1e-7
            if abs(s_obj - p_obj) > abs_tol + rel_tol * max(abs(s_obj), abs(p_obj)):
                return False
        elif s_status == "infeasible":
            if s_res.get("objective") is not None or p_res.get("objective") is not None:
                return False
        else:
            # Error or unknown: don't claim match
            return False

    return True


def _check_overlap(rows: list) -> bool:
    """Check if any two rows with different PIDs have overlapping intervals."""
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if rows[i]["pid"] != rows[j]["pid"]:
                max_start = max(rows[i]["start_monotonic"], rows[j]["start_monotonic"])
                min_end = min(rows[i]["end_monotonic"], rows[j]["end_monotonic"])
                if max_start < min_end:
                    return True
    return False


# ---------------------------------------------------------------------------
# Public API: run_scenario
# ---------------------------------------------------------------------------


def run_scenario(settings: dict) -> dict:
    """Run a single scenario in an isolated child process. Returns the result dict."""
    if not _lock.acquire(blocking=False):
        raise RuntimeError("another run_scenario/run_benchmark call is in progress")
    try:
        s = validate_settings(settings)

        budget_remaining = _TOTAL_BUDGET
        if budget_remaining <= _CLEANUP_RESERVE:
            raise RuntimeError("budget exhausted before launch")

        timeout = min(_SINGLE_CHILD_TIMEOUT, budget_remaining - _CLEANUP_RESERVE)
        if timeout <= 0:
            raise RuntimeError("budget exhausted: no time for single child")

        env = _build_child_env()
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_json = json.dumps(s, allow_nan=False)
            stdout, wall_seconds, success = _launch_child_safe(
                ["--single", settings_json], timeout, tmpdir, env
            )

        if not success:
            raise RuntimeError(f"single child failed (wall={wall_seconds:.3f}s)")

        data = json.loads(stdout)
        rows = data.get("rows", [])
        if len(rows) != 1:
            raise RuntimeError(f"expected 1 row from single child, got {len(rows)}")

        rec = rows[0]
        _validate_row_record(rec, 0, s)
        result = rec["result"]
        _validate_physics(result, s)

        return result
    finally:
        _lock.release()


# ---------------------------------------------------------------------------
# Public API: run_benchmark
# ---------------------------------------------------------------------------


def run_benchmark(batch: list, workers: int) -> dict:
    """Run sequential (1 worker) and parallel (N workers) benchmarks."""
    if not _lock.acquire(blocking=False):
        raise RuntimeError("another run_scenario/run_benchmark call is in progress")
    try:
        batch = _validate_batch(batch)
        workers = _validate_workers(workers)

        t_start = time.perf_counter()

        env = _build_child_env()

        with tempfile.TemporaryDirectory() as tmpdir:
            batch_json = json.dumps(batch, allow_nan=False)

            # --- Sequential (workers=1) ---
            remaining = _TOTAL_BUDGET - (time.perf_counter() - t_start)
            if remaining <= _CLEANUP_RESERVE:
                raise RuntimeError("budget exhausted before sequential launch")
            seq_timeout = min(_BATCH_CHILD_TIMEOUT, remaining - _CLEANUP_RESERVE)
            if seq_timeout <= 0:
                raise RuntimeError("budget exhausted: no time for sequential child")

            seq_stdout, seq_wall, seq_ok = _launch_child_safe(
                ["--batch", batch_json, "--workers", "1"], seq_timeout, tmpdir, env
            )

            if not seq_ok:
                raise RuntimeError(f"sequential child failed (wall={seq_wall:.3f}s)")

            seq_data = json.loads(seq_stdout)
            seq_data["wall_seconds"] = seq_wall

            # --- Parallel (workers=N) ---
            remaining = _TOTAL_BUDGET - (time.perf_counter() - t_start)
            if remaining <= _CLEANUP_RESERVE:
                raise RuntimeError("budget exhausted before parallel launch")
            par_timeout = min(_BATCH_CHILD_TIMEOUT, remaining - _CLEANUP_RESERVE)
            if par_timeout <= 0:
                raise RuntimeError("budget exhausted: no time for parallel child")

            par_stdout, par_wall, par_ok = _launch_child_safe(
                ["--batch", batch_json, "--workers", str(workers)], par_timeout, tmpdir, env
            )

            if not par_ok:
                raise RuntimeError(f"parallel child failed (wall={par_wall:.3f}s)")

            par_data = json.loads(par_stdout)
            par_data["wall_seconds"] = par_wall

        # --- Validate branches (wall_seconds already assigned above) ---
        _validate_branch(seq_data, batch, 1)
        _validate_branch(par_data, batch, workers)

        # --- Physics validation on every row ---
        for branch in (seq_data, par_data):
            for i, rec in enumerate(branch["rows"]):
                _validate_physics(rec["result"], batch[i])

        # --- Comparison ---
        matches = _compare_results(seq_data["rows"], par_data["rows"], batch)

        seq_wall = seq_data["wall_seconds"]
        par_wall = par_data["wall_seconds"]
        seq_engine = seq_data["engine_seconds"]
        par_engine = par_data["engine_seconds"]

        speedup = seq_wall / par_wall if par_wall > 0 else None
        engine_speedup = seq_engine / par_engine if par_engine > 0 else None

        # Scaling available: only if pool_width > 1
        scaling_available = par_data["pool_width"] > 1

        # Overlap check
        overlap = _check_overlap(par_data["rows"])

        report = {
            "sequential": {
                "batch": batch,
                "rows": seq_data["rows"],
                "workers": 1,
                "pool_width": seq_data["pool_width"],
                "actual_workers": seq_data["actual_workers"],
                "engine_start": seq_data["engine_start"],
                "engine_end": seq_data["engine_end"],
                "engine_seconds": seq_engine,
                "wall_seconds": seq_wall,
            },
            "parallel": {
                "batch": batch,
                "rows": par_data["rows"],
                "workers": workers,
                "pool_width": par_data["pool_width"],
                "actual_workers": par_data["actual_workers"],
                "engine_start": par_data["engine_start"],
                "engine_end": par_data["engine_end"],
                "engine_seconds": par_engine,
                "wall_seconds": par_wall,
            },
            "comparison": {
                "matches": matches,
                "speedup": speedup,
                "engine_speedup": engine_speedup,
                "scaling_available": scaling_available,
                "overlap_observed": overlap,
                "comparison_method": "case-index-aligned status+objective comparison with independent physics validation",
            },
        }

        return report
    finally:
        _lock.release()


# ---------------------------------------------------------------------------
# CLI dispatch (child entry point)
# ---------------------------------------------------------------------------


def _cli_main() -> None:
    """Fixed CLI for child subprocess invocation."""
    import argparse

    parser = argparse.ArgumentParser(description="energy_runner child")
    parser.add_argument("--single", type=str, default=None)
    parser.add_argument("--batch", type=str, default=None)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    # Reject unknown keys
    known = {"single", "batch", "workers"}
    for a in sys.argv[1:]:
        if a.startswith("--") and a[2:].split("=")[0] not in known:
            print(json.dumps({"error": f"unknown argument: {a}"}), file=sys.stderr)
            sys.exit(1)

    if args.single is not None and args.batch is not None:
        print(json.dumps({"error": "--single and --batch are mutually exclusive"}), file=sys.stderr)
        sys.exit(1)

    if args.single is not None:
        try:
            settings = json.loads(args.single)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"invalid settings JSON: {e}"}), file=sys.stderr)
            sys.exit(1)
        try:
            validate_settings(settings)
        except Exception as e:
            print(json.dumps({"error": f"settings validation: {e}"}), file=sys.stderr)
            sys.exit(1)
        items = [{"case": 0, "settings": settings}]
        result = _child_run_batch(items, 1)
        print(json.dumps(result, allow_nan=False))

    elif args.batch is not None:
        try:
            batch = json.loads(args.batch)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"invalid batch JSON: {e}"}), file=sys.stderr)
            sys.exit(1)
        if not isinstance(batch, list) or len(batch) not in _VALID_BATCH_LENGTHS:
            print(json.dumps({"error": "batch must be list of length 4, 8, or 12"}), file=sys.stderr)
            sys.exit(1)
        if not isinstance(args.workers, int) or isinstance(args.workers, bool):
            print(json.dumps({"error": "workers must be strict int"}), file=sys.stderr)
            sys.exit(1)
        max_w = min(_MAX_WORKERS, cpu_limits()["effective_cpus"])
        if not (1 <= args.workers <= max_w):
            print(json.dumps({"error": f"workers must be 1..{max_w}"}), file=sys.stderr)
            sys.exit(1)
        for i, s in enumerate(batch):
            try:
                validate_settings(s)
            except Exception as e:
                print(json.dumps({"error": f"batch[{i}]: {e}"}), file=sys.stderr)
                sys.exit(1)
        items = [{"case": i, "settings": s} for i, s in enumerate(batch)]
        result = _child_run_batch(items, args.workers)
        print(json.dumps(result, allow_nan=False))

    else:
        print(json.dumps({"error": "must specify --single or --batch"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    # Only run CLI if actually invoked as a script (not re-imported by spawn)
    if "--single" in sys.argv or "--batch" in sys.argv:
        _cli_main()
    # Spawned workers from ProcessPoolExecutor will re-import this module
    # but won't have --single/--batch in their argv, so they skip CLI.