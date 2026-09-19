"""Validate and export a real free-threading notebook-agent build."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import statistics
import sys

from agilab.agent_runtime.free_threading_showcase import PUBLIC_FILES

ENGINE_COMMIT = "7d2b1355b84eed3cbf0828c325cddb8308be77a3"
ENGINE_PATH = "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/worker_pool_support.py"
ENGINE_HASH = "305ba174348e92376b08be149b488fc41983de04c5b2564695493769fc21f066"
SOURCE_HASH = "ea34493fc5caaa6062dfa9b4210b1d0620f205cce4cc117c9293155f75a1c911"


def reference_counts(width: int, height: int, iterations: int) -> list[int]:
    """Independent scalar oracle; no worker adapter or generated kernel calls."""
    values = []
    for row in range(height):
        for column in range(width):
            parameter = complex(-2 + 3 * column / (width - 1), -1.2 + 2.4 * row / (height - 1))
            point = 0j
            for count in range(iterations):
                if point.real * point.real + point.imag * point.imag > 4:
                    break
                point = point ** 2 + parameter
            else:
                count = iterations
            values.append(count)
    return values


def validate_analysis(project: Path) -> dict:
    names = ("agilab_pool", "free_threading_core", "benchmark")
    saved = {name: sys.modules.pop(name, None) for name in names}
    old_path = sys.path[:]
    sys.path.insert(0, str(project))
    try:
        core = importlib.import_module("free_threading_core")
        benchmark = importlib.import_module("benchmark")
        for width, height, iterations in ((9, 7, 30), (64, 41, 90), (96, 64, 100)):
            assert core.reference_image(width, height, iterations) == reference_counts(width, height, iterations)
        workers = min(2, benchmark.effective_cpus()["effective_cpus"])
        result = benchmark.run_benchmark(width=96, height=64, iterations=100, workers=workers, repeats=2)
        expected = reference_counts(96, 64, 100)
        assert len(result["runs"]) == 12 and len(result["summary"]) == 6
        assert result["same_work_verified"] is True
        for run in result["runs"]:
            ordered = sorted(run["records"], key=lambda record: record["row_start"])
            assert [value for record in ordered for value in record["counts"]] == expected
            assert run["digest"] == result["digest"]
            assert run["before"]["free_threaded_build"] is True
            assert run["before"] == run["after"]
            assert run["before"]["gil_enabled"] is (run["mode"] != "gil_off_threads")
            assert run["before"]["version"] == result["python_build"]
            assert 0 < run["engine_seconds"] <= run["wall_seconds"]
            assert run["actual_workers"] == run["workers"]
        for summary in result["summary"]:
            group = [r for r in result["runs"] if r["mode"] == summary["mode"] and r["role"] == summary["role"]]
            baseline = [r for r in result["runs"] if r["mode"] == summary["mode"] and r["role"] == "baseline"]
            median = statistics.median(r["wall_seconds"] for r in group)
            assert summary["wall_seconds"] == median
            assert summary["speedup"] == statistics.median(r["wall_seconds"] for r in baseline) / median
        return {"status": "passed", "checks": [
            "unchanged_AGILAB_pool_engine", "independent_scalar_image_oracle",
            "real_threads_and_spawned_processes", "actual_GIL_state_before_after_and_per_task",
            "same_image_across_modes_widths_and_repeats", "same_interpreter_build_controls",
            "complete_tile_reduction", "end_to_end_timing_and_repeated_medians",
        ], "hardware": result["hardware"], "python_build": result["python_build"],
            "measurements": result["summary"], "measurement_scope": "local build-machine validation; not Space benchmark results"}
    finally:
        sys.path[:] = old_path
        for name in names:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]


def export_demo(run: Path, destination: Path) -> dict:
    report = json.loads((run / "result.json").read_text())
    if report.get("status") != "passed" or report.get("verification", {}).get("status") != "passed":
        raise ValueError("A passed autonomous notebook-agent run is required")
    if report.get("source", {}).get("sha256") != SOURCE_HASH:
        raise ValueError("Unexpected source notebook")
    project = run / "notebook_app_project"
    if project.is_symlink():
        raise ValueError("Project must be a real directory")
    if (destination.is_symlink() or any(p.is_symlink() for p in destination.absolute().parents)
            or destination.exists() and any(destination.iterdir())):
        raise ValueError("Export destination must be an empty real directory")
    payload = {}
    for name in sorted(PUBLIC_FILES):
        path = project
        for part in Path(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Symlinked public asset: {name}")
        payload[name] = path.read_bytes()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    for name in PUBLIC_FILES:
        if name.startswith("source/") or Path(name).suffix not in {".py", ".ipynb", ".toml"}:
            continue
        if hashes[name] != report["files"].get(name):
            raise ValueError(f"Autonomous-run artifact changed: {name}")
    if hashes["agilab_pool.py"] != ENGINE_HASH or hashes["source/original.ipynb"] != SOURCE_HASH:
        raise ValueError("Pinned AGILAB engine or source notebook changed")
    checks = validate_analysis(project)
    if any((project / name).read_bytes() != content for name, content in payload.items()):
        raise ValueError("Public assets changed during validation")
    public = {
        "schema": "agilab.notebook_agent.public_demo.v1", "status": "passed",
        "run_id": run.name, "seconds": report["seconds"], "workflow_stages": report["workflow_stages"],
        "source": {"source_kind": "original_agilab_notebook", "title": "AGILAB free-threading reference notebook",
                   "author": "AGILAB contributors", "license": "BSD-3-Clause", "sha256": SOURCE_HASH,
                   "created": "2026-09-19"},
        "engine": {"repository": "ThalesGroup/agilab", "commit": ENGINE_COMMIT,
                   "path": ENGINE_PATH, "sha256": ENGINE_HASH},
        "verification_scope": "execution_interface_and_bounded_local_pool_scaling",
        "verification": {**report["verification"], "free_threading": checks}, "files": hashes,
    }
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in payload.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (destination / "result.json").write_text(json.dumps(public, indent=2, allow_nan=False) + "\n")
    return public


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = export_demo(args.run, args.destination)
    print(json.dumps({"status": result["status"], "run_id": result["run_id"],
                      "seconds": result["seconds"], "checks": result["verification"]["free_threading"]["checks"]}))
