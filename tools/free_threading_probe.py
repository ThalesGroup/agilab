#!/usr/bin/env python3
"""Probe built AGILAB wheels in an isolated, free-threaded Python environment.

Run with ``--help`` for the local-only report and replay command. This probe
does not change installer policy or establish general thread safety.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from typing import Any


SCHEMA = "agilab.free_threading_probe.v1"
ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("agilab", "agi-env", "agi-node", "agi-cluster", "agi-core")
MODULES = (
    "agilab", "agi_env", "agi_node", "agi_cluster", "agi_core",
    "numpy", "pandas", "polars", "dask.distributed", "sklearn",
    "agi_node.agi_dispatcher", "agi_node.polars_worker",
)


def isolated_env(directory: Path) -> dict[str, str]:
    """Prevent user Python, AGILAB and worker settings from changing the probe."""
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "AGI_", "AGILAB_"))
        and key not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH", "APPS_REPOSITORY"}
    }
    home = directory / "home"
    home.mkdir()
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), AGILAB_POOL_MAX_WORKERS="2")
    # Do not force PYTHON_GIL=0: an extension enabling the GIL must be detected.
    return env


def diagnostic(text: str) -> str:
    """Keep local failure evidence bounded and remove credential values."""
    text = re.sub(r"(https?://)[^\s/]+@", r"\1<redacted>@", text)
    for key, value in os.environ.items():
        if len(value) >= 8 and re.search(r"TOKEN|PASSWORD|SECRET|API_KEY", key, re.I):
            text = text.replace(value, "<redacted>")
    return text[-4000:]


def run_step(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
        return {"status": "passed" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "diagnostic": diagnostic(result.stderr + result.stdout) if result.returncode else ""}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "returncode": None,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "diagnostic": diagnostic(str(exc))}


def worker_check() -> dict[str, Any]:
    """Compare actual PolarsWorker mono/pool dispatch, including item labels."""
    import polars as pl
    from agi_node.polars_worker import PolarsWorker

    class ProbeWorker(PolarsWorker):
        def __init__(self, mode: int):
            self._worker_id = 0
            self._mode = mode
            self.args = {"pool_max_workers": 2}
            self.pool_vars = None
            self.outputs: list[list[dict[str, Any]]] = []

        def _actual_work_pool(self, value: int):
            return pl.DataFrame({"input": [value], "square": [value * value]})

        def work_done(self, frame):
            self.outputs.append(frame.to_dicts())

        def stop(self):
            pass

    chunks = [[3, 1, 3, 2], [8, 0, 5]]
    expected = [[{"input": value, "square": value * value, "worker_id": str((0, index))}
                 for index, value in enumerate(chunk)] for chunk in chunks]
    timings = []
    for mode in (0, 1):
        worker = ProbeWorker(mode)
        timings.append(worker.works([chunks], None))
        if worker.outputs != expected:
            return {"status": "failed", "reason": "worker_output_mismatch", "mode": mode}
    return {"status": "passed", "workload": "PolarsWorker.works: mono and thread pool",
            "items": 7, "chunks": 2, "workers": 2,
            "output_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(),
            "sequential_seconds": timings[0], "threaded_seconds": timings[1]}


def runtime_probe() -> dict[str, Any]:
    gil_enabled = getattr(sys, "_is_gil_enabled", lambda: True)
    report: dict[str, Any] = {
        "status": "failed", "python": platform.python_version(), "platform": platform.platform(),
        "free_threaded_build": sysconfig.get_config_var("Py_GIL_DISABLED") == 1,
        "gil_enabled_before_imports": gil_enabled(), "imports": [],
        "worker": {"status": "skipped", "reason": "runtime_checks_not_passed"},
    }
    if not report["free_threaded_build"] or report["gil_enabled_before_imports"]:
        report["reason"] = "requires_free_threaded_python_with_gil_disabled"
        return report
    report["versions"] = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
    for name in MODULES:
        entry: dict[str, Any] = {"module": name, "gil_enabled_before": gil_enabled()}
        try:
            module = importlib.import_module(name)
            origins = ([module.__file__] if getattr(module, "__file__", None)
                       else list(getattr(module, "__path__", [])))
            if not origins or not all(Path(path).resolve().is_relative_to(Path(sys.prefix).resolve()) for path in origins):
                raise RuntimeError("module did not load from the isolated environment")
            entry["status"] = "passed"
        except Exception as exc:
            entry.update(status="failed", error=diagnostic(f"{type(exc).__name__}: {exc}"))
        entry["gil_enabled_after"] = gil_enabled()
        if entry["gil_enabled_after"]:
            entry.update(status="failed", reason="gil_enabled_after_import")
        report["imports"].append(entry)
    if any(entry["status"] != "passed" for entry in report["imports"]):
        report["reason"] = "import_or_gil_check_failed"
        return report
    try:
        report["worker"] = worker_check()
    except Exception as exc:
        report["worker"] = {"status": "failed", "error": diagnostic(f"{type(exc).__name__}: {exc}")}
    report["gil_enabled_after_worker"] = gil_enabled()
    if report["worker"]["status"] == "passed" and not report["gil_enabled_after_worker"]:
        report["status"] = "passed"
    return report


def read_runtime_result(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text())
        if not isinstance(result, dict) or result.get("status") not in {"passed", "failed"}:
            raise ValueError("invalid runtime status")
        return result
    except (OSError, ValueError) as exc:
        return {"status": "failed", "reason": "runtime_result_missing_or_invalid",
                "error": diagnostic(str(exc))}


def probe(*, python: str, timeout: float, repo_root: Path = ROOT) -> dict[str, Any]:
    # Reuse the release package inventory; do not create a second path mapping.
    sys.path.insert(0, str(repo_root / "tools"))
    from package_split_contract import package_by_name

    report: dict[str, Any] = {
        "schema": SCHEMA, "producer": "tools/free_threading_probe.py", "local_only": True,
        "created_at": datetime.now(timezone.utc).isoformat(), "python_requested": python,
        "command": ["uv", "--preview-features", "extra-build-dependencies", "run", "--no-sync",
                    "python", "tools/free_threading_probe.py", "--python", python, "--timeout", str(timeout)],
        "status": "failed", "packages": list(PACKAGES), "steps": [], "wheels": [],
        "runtime": {"status": "skipped", "reason": "setup_not_completed"},
    }
    uv = shutil.which("uv")
    if not uv:
        report["reason"] = "uv_not_found"
        return report
    with tempfile.TemporaryDirectory(prefix="agilab-free-threading-") as temporary:
        work = Path(temporary)
        env = isolated_env(work)
        wheels = work / "wheels"
        wheels.mkdir()

        def step(name: str, command: list[str], cwd: Path = work) -> bool:
            result = run_step(command, cwd=cwd, env=env, timeout=timeout)
            report["steps"].append({"name": name, **result})
            if result["status"] != "passed":
                report["reason"] = name + "_failed"
                return False
            return True

        for name in PACKAGES:
            project = repo_root / package_by_name(name).project
            if not step("build:" + name, [uv, "build", "--no-config", "--python", sys.executable,
                                          "--wheel", "--out-dir", str(wheels), str(project)]):
                return report
        artifacts = sorted(wheels.glob("*.whl"))
        if len(artifacts) != len(PACKAGES):
            report["reason"] = "unexpected_wheel_count"
            return report
        report["wheels"] = [{"filename": path.name, "size": path.stat().st_size,
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "retained": False}
                            for path in artifacts]
        venv = work / "venv"
        if not step("environment", [uv, "venv", "--no-config", "--python", python, str(venv)]):
            return report
        executable = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not step("dependencies", [uv, "pip", "install", "--no-config", "--python", str(executable),
                                     "--only-binary", ":all:", *(str(path) for path in artifacts)]):
            return report
        runtime_script = work / "probe.py"
        shutil.copyfile(Path(__file__), runtime_script)
        result_file = work / "runtime.json"
        if not step("runtime", [str(executable), "-I", str(runtime_script), "--runtime", str(result_file)]):
            # Runtime failures still produce useful structured diagnostics.
            report["runtime"] = read_runtime_result(result_file)
            return report
        report["runtime"] = read_runtime_result(result_file)
        report["status"] = report["runtime"]["status"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="3.14t", help="Free-threaded interpreter selector for uv.")
    parser.add_argument("--timeout", type=float, default=600, help="Maximum seconds per subprocess.")
    parser.add_argument("--output", type=Path, default=Path("reports/free-threading/probe.json"))
    parser.add_argument("--runtime", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    report = runtime_probe() if args.runtime else probe(python=args.python, timeout=args.timeout)
    output = args.runtime or args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{report['status']}: {output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
