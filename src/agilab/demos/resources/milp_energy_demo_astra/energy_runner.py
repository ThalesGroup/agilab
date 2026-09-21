"""Bounded subprocess ownership for the public lab (no solver imports)."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from energy_core import canonical_hash, cpu_limits, validate_batch, validate_settings

MAX_SECONDS = 150.0


@contextmanager
def _exclusive():
    if os.environ.get("MILP_ENERGY_CHILD"):
        raise RuntimeError(
            "Nested outer runs are disabled; use the scenario worker in a batch."
        )
    identity = hashlib.sha256(
        str(Path(__file__).resolve().parent).encode()
    ).hexdigest()[:20]
    # Stable advisory-lock inode: deliberately never unlink while another process may open it.
    path = Path(tempfile.gettempdir()) / f"milp-energy-{os.getuid()}-{identity}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "MILP Energy Lab is busy with another run. Try again when it finishes."
            ) from None
        yield
    finally:
        os.close(fd)


def _terminate_group(process):
    """Only terminate this task's new session, then wait for known descendants."""
    import psutil

    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except (psutil.Error, OSError):
        # Sandboxed macOS can forbid system-wide PID enumeration. The process
        # group remains our owned boundary and must still be terminated.
        descendants = []
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.7)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)
    _, alive = psutil.wait_procs(descendants, timeout=0.5)
    for child in alive:
        try:
            child.kill()
        except (psutil.Error, OSError):
            pass
    psutil.wait_procs(alive, timeout=0.5)


def _launch(mode, payload, deadline, progress=None):
    start = time.monotonic()
    if start >= deadline:
        raise TimeoutError("The total experiment time budget was exhausted.")
    with tempfile.TemporaryDirectory(prefix="milp-energy-run-") as scratch:
        directory = Path(scratch)
        input_path, output_path = directory / "input.json", directory / "output.json"
        input_path.write_text(json.dumps(payload, allow_nan=False))
        env = os.environ.copy()
        env.update(
            {
                key: "1"
                for key in (
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                    "BLIS_NUM_THREADS",
                )
            }
        )
        env.update(
            MILP_ENERGY_CHILD="1",
            AGILAB_POOL_EXECUTOR="process",
            PYTHONDONTWRITEBYTECODE="1",
            MPLCONFIGDIR=scratch,
            TMPDIR=scratch,
            AGILAB_POOL_MAX_WORKERS=str(payload.get("workers", 1)),
        )
        # File-backed logs cannot fill a pipe and deadlock the solver.
        with (directory / "run.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("energy_core.py")),
                    mode,
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=scratch,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                while process.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            "Experiment exceeded its bounded wall time; child processes were terminated."
                        )
                    if progress:
                        progress(time.monotonic() - start)
                    try:
                        process.wait(timeout=min(0.25, remaining))
                    except subprocess.TimeoutExpired:
                        pass
                if process.returncode or not output_path.exists():
                    log.seek(0)
                    tail = log.read()[-1800:]
                    # Never expose per-run machine paths in downloadable reports.
                    raise RuntimeError(
                        "Isolated computation failed: " + tail.replace(scratch, "<run>")
                    )
                result = json.loads(
                    output_path.read_text(),
                    parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
                )
            finally:
                _terminate_group(process)
    result["wall_seconds"] = time.monotonic() - start
    return result


def run_scenario(settings, progress=None):
    settings = validate_settings(settings)
    with _exclusive():
        result = _launch("single", settings, time.monotonic() + 45, progress)
    if result["settings"] != settings or result["input_sha256"] != canonical_hash(
        settings
    ):
        raise RuntimeError("Result does not bind the submitted settings.")
    return result


def run_batch(batch, workers=1, progress=None):
    batch = validate_batch(batch, workers)
    with _exclusive():
        result = _launch(
            "batch",
            dict(batch=batch, workers=workers),
            time.monotonic() + MAX_SECONDS - 5,
            progress,
        )
    _check_batch_identity(result, batch, workers)
    return result


def _check_batch_identity(result, batch, workers):
    if (
        result["batch"] != batch
        or result["batch_sha256"] != canonical_hash(batch)
        or result["workers"] != workers
    ):
        raise RuntimeError("Batch report does not match submitted inputs.")
    if [row["case"] for row in result["rows"]] != list(range(len(batch))):
        raise RuntimeError("Missing or reordered batch cases.")
    for row, s in zip(result["rows"], batch):
        if row["result"]["settings"] != s or row["result"][
            "input_sha256"
        ] != canonical_hash(s):
            raise RuntimeError("Scenario identity mismatch.")


def compare_runs(one, many):
    if one["batch_sha256"] != many["batch_sha256"] or one["batch"] != many["batch"]:
        raise ValueError("Only identical input batches can be compared.")
    _check_batch_identity(one, one["batch"], one["workers"])
    _check_batch_identity(many, one["batch"], many["workers"])
    checks = []
    for a, b in zip(one["rows"], many["rows"]):
        x, y = a["result"], b["result"]
        valid = x["status"] in ("optimal", "feasible", "infeasible") and y[
            "status"
        ] in ("optimal", "feasible", "infeasible")
        same = x["status"] == y["status"]
        objectives = (
            x["objective"] is None and y["objective"] is None
            if x["objective"] is None or y["objective"] is None
            else math.isclose(
                x["objective"], y["objective"], rel_tol=1e-7, abs_tol=1e-4
            )
        )
        verified = all(
            r["status"] == "infeasible" or r["residuals"]["verified"] for r in (x, y)
        )
        checks.append(
            dict(
                case=a["case"],
                matches=valid and same and objectives and verified,
                sequential_status=x["status"],
                parallel_status=y["status"],
                sequential_objective=x["objective"],
                parallel_objective=y["objective"],
            )
        )
    return dict(
        matches=bool(checks) and all(x["matches"] for x in checks),
        cases=checks,
        tolerance=dict(relative=1e-7, absolute=1e-4),
    )


def run_benchmark(batch, workers, progress=None):
    batch = validate_batch(batch, workers)
    if workers < 2:
        raise ValueError(
            "Scaling unavailable: at least two effective CPUs are required."
        )
    start = time.monotonic()
    deadline = start + MAX_SECONDS - 5
    with _exclusive():
        one = _launch("batch", dict(batch=batch, workers=1), deadline, progress)
        _check_batch_identity(one, batch, 1)
        many = _launch("batch", dict(batch=batch, workers=workers), deadline, progress)
        _check_batch_identity(many, batch, workers)
    comparison = compare_runs(one, many)
    return dict(
        batch=batch,
        batch_sha256=canonical_hash(batch),
        environment=cpu_limits(),
        sequential=one,
        parallel=many,
        comparison=comparison,
        speedup=one["wall_seconds"] / many["wall_seconds"],
        sequential_cases_per_second=len(batch) / one["wall_seconds"],
        parallel_cases_per_second=len(batch) / many["wall_seconds"],
        total_wall_seconds=time.monotonic() - start,
        note="Independent scenarios on local spawned workers, not a distributed cluster or a faster single MILP. Includes startup/imports; no timing cache.",
    )
