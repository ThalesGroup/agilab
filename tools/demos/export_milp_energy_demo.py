"""Check and publish an immutable, real notebook-agent MILP lab build."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from agilab.demos.milp_energy_showcase import PUBLIC_FILES

SOURCE_COMMIT = "c838aa498557cc8e27a9d3ed10d45e35c4b0b442"
SOURCE_URL = f"https://github.com/PyPSA/PyPSA/blob/{SOURCE_COMMIT}/docs/examples/modular-committable.ipynb"
SOURCE_HASH = "f7ea554af73cb21b3eb8c0569c7c21eac0b327e0ce35c29cf23806d74af926b8"
# Original public source metadata, also required by the sealed replay tests.
PROVENANCE_HASH = "5a142f1195399b3efb5b6f8713500d72c81efcd7b68fc27c9102ff4bc19566ff"
LICENSE_HASH = "d557539df68e771cc1eedcc91d13f70fca930e508d11eedcafa4b15db49e3744"
ENGINE_COMMIT = "7d2b1355b84eed3cbf0828c325cddb8308be77a3"
ENGINE_PATH = "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/worker_pool_support.py"
ENGINE_HASH = "305ba174348e92376b08be149b488fc41983de04c5b2564695493769fc21f066"
ENGINE_LICENSE_HASH = "b9c2bbb8087ee916e1f8628c002b1f9af77cf7dc112331edca5edec4cd5b0a16"


def validate_analysis(project: Path) -> dict:
    """Check actual solver output against the hand-computable upstream instance."""
    # An isolated process prevents HiGHS global state leaking into export callers.
    program = """
import json, sys
from pathlib import Path
from energy_core import default_settings, solve_scenario, make_batch, cpu_limits
from energy_runner import run_benchmark
settings = default_settings()
result = solve_scenario(settings)
infeasible = solve_scenario(settings | {'max_modules': 20})
shed = solve_scenario(settings | {'max_modules': 20, 'allow_shedding': True})
solar = solve_scenario(settings | {'solar_capacity': 1500.0, 'startup_cost': 500.0})
workers = min(2, cpu_limits()['effective_cpus'])
benchmark = run_benchmark(make_batch(settings, 4), workers) if workers > 1 else None
Path(sys.argv[1]).write_text(json.dumps({'reference': result, 'infeasible': infeasible,
    'shed': shed, 'solar': solar, 'benchmark': benchmark}, allow_nan=False))
"""
    with tempfile.TemporaryDirectory(prefix="milp-export-") as directory:
        output = Path(directory) / "reference.json"
        checked = subprocess.run([sys.executable, "-c", program, str(output)], cwd=project,
                                 capture_output=True, text=True, timeout=240)
        if checked.returncode:
            raise ValueError(f"MILP reference execution failed: {checked.stderr[-3000:]}")
        evidence = json.loads(output.read_text())
    result = evidence["reference"]
    demand = [4000, 6000, 5000, 800]
    active = [20, 30, 25, 4]
    expected_cost = sum(demand) + 200 * max(active) + sum(active)
    if result["status"] != "optimal" or abs(result["objective"] - expected_cost) > 1e-5:
        raise ValueError("Default MILP result does not match the independently calculated optimum")
    for key, expected in (("dispatch", demand), ("demand", demand), ("active_modules", active)):
        actual = result[key]
        if len(actual) != len(expected) or any(abs(a - b) > 1e-6 for a, b in zip(actual, expected)):
            raise ValueError(f"Default MILP {key} does not match the reference")
    if abs(result["capacity_mw"] - 6000) > 1e-6 or abs(result["modules"] - 30) > 1e-6:
        raise ValueError("Default MILP installed capacity is incorrect")
    if any(abs(v) > 1e-6 for key in ("solar", "shed") for v in result[key]):
        raise ValueError("Unexpected solar or shedding in the reference instance")
    if str(result["solver"]["name"]).lower() != "highs" or result["solver"]["threads"] != 1:
        raise ValueError("The public MILP solver must be HiGHS with one thread")
    failed = evidence["infeasible"]
    if failed["status"] != "infeasible" or failed["objective"] is not None or failed["dispatch"]:
        raise ValueError("Capacity-limited infeasibility must not expose a solution")
    if sum(evidence["shed"]["shed"]) < 3000 - 1e-5:
        raise ValueError("The shortage scenario does not report required unserved demand")
    for scenario in (result, evidence["shed"], evidence["solar"]):
        validate_physics(scenario)
    benchmark = evidence["benchmark"]
    if benchmark is None:
        raise ValueError("Publication requires a real scaling check on at least two available CPUs")
    one, many = benchmark["sequential"], benchmark["parallel"]
    if not benchmark["comparison"]["matches"] or one["batch"] != many["batch"]:
        raise ValueError("AGILAB serial/parallel scenarios or outcomes differ")
    rows = many["rows"]
    if len(rows) != 4 or sorted(row["case"] for row in rows) != list(range(4)):
        raise ValueError("AGILAB did not collect every scenario exactly once")
    if len({row["pid"] for row in rows}) != 2 or not any(
        a["pid"] != b["pid"] and max(a["start_monotonic"], b["start_monotonic"])
        < min(a["end_monotonic"], b["end_monotonic"]) for a in rows for b in rows
    ):
        raise ValueError("Two actual AGILAB workers did not overlap")
    for run in (one, many):
        if run["wall_seconds"] <= 0 or run["engine_seconds"] <= 0:
            raise ValueError("Scaling needs fresh, positive measured timings")
        for row in run["rows"]:
            validate_physics(row["result"])
    return {"status": "passed", "checks": [
        "pinned notebook and CC BY 4.0 license", "unchanged AGILAB pool engine",
        "fresh HiGHS execution with one solver thread", "independent 21879 objective and 30-module optimum",
        "reference dispatch and integer commitment at every timestep",
        "capacity-limited infeasibility without an incumbent", "independent shortage and solar/startup constraints and costs",
        "same scenario batch and outcomes on one and two AGILAB workers", "measured overlapping worker processes",
    ], "reference_objective": expected_cost,
        "scaling_validation": {"cases": 4, "workers": 2, "scope": "local scenario throughput",
                               "note": "Timings are validation evidence, not a guarantee of public Space speedup"}}


def validate_physics(result: dict) -> None:
    """Check schedules without calling the generated residual checker."""
    import math

    if result["status"] not in {"optimal", "feasible"}:
        raise ValueError("Expected a feasible solution for physical validation")
    s = result["settings"]
    if result["solver"]["threads"] != 1 or str(result["solver"]["name"]).lower() != "highs":
        raise ValueError("Unexpected solver execution settings")
    arrays = [result[key] for key in ("dispatch", "active_modules", "solar", "shed", "startup", "shutdown")]
    if any(len(values) != s["hours"] for values in arrays):
        raise ValueError("Incomplete hourly schedule")
    n, module = result["modules"], s["module_mw"]
    if not math.isfinite(n) or abs(n - round(n)) > 1e-5 or not 0 <= n <= s["max_modules"]:
        raise ValueError("Invalid installed integer module count")
    if abs(result["capacity_mw"] - n * module) > 1e-5:
        raise ValueError("Installed capacity does not match the module count")
    demand = [v * s["demand_multiplier"] for v in [4000, 6000, 5000, 800] * (s["hours"] // 4)]
    solar_pu = [0, 0.6, 0.9, 0] if s["hours"] == 4 else [
        max(0, math.sin(math.pi * (h / (s["hours"] - 1) * 2 - 0.5))) for h in range(s["hours"])]
    previous = 0
    cost = s["investment_cost"] * module * n
    for hour, (power, active, solar, shed, startup, shutdown) in enumerate(zip(*arrays)):
        values = (power, active, solar, shed, startup, shutdown)
        if any(not math.isfinite(v) or v < -1e-5 for v in values):
            raise ValueError("Non-finite or negative physical quantity")
        if any(abs(v - round(v)) > 1e-5 for v in (active, startup, shutdown)):
            raise ValueError("Noninteger commitment or transition")
        if active > n + 1e-5 or not s["min_loading"] * module * active - 1e-5 <= power <= module * active + 1e-5:
            raise ValueError("Dispatch violates committed capacity")
        if solar > solar_pu[hour] * s["solar_capacity"] + 1e-5 or shed > demand[hour] * s["allow_shedding"] + 1e-5:
            raise ValueError("Solar or shedding exceeds its allowed supply")
        if abs(power + solar + shed - demand[hour]) > 1e-5:
            raise ValueError("Demand balance violated")
        if abs(startup - max(0, active - previous)) > 1e-5 or abs(shutdown - max(0, previous - active)) > 1e-5:
            raise ValueError("Startup or shutdown count is incorrect")
        cost += power * s["marginal_cost"] + active * s["standby_cost"] + startup * s["startup_cost"] + shed * 100000
        previous = active
    if not math.isclose(cost, result["objective"], abs_tol=1e-4, rel_tol=1e-7):
        raise ValueError("Objective differs from independently reconstructed costs")


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
    if (hashes["agilab_pool.py"] != ENGINE_HASH or hashes["source/original.ipynb"] != SOURCE_HASH
            or hashes["source/LICENSE"] != LICENSE_HASH or hashes["AGILAB_LICENSE"] != ENGINE_LICENSE_HASH
            or hashes["source/provenance.json"] != PROVENANCE_HASH):
        raise ValueError("Pinned AGILAB engine, source notebook or notebook license changed")
    checks = validate_analysis(project)
    if any((project / name).read_bytes() != content for name, content in payload.items()):
        raise ValueError("Public assets changed during validation")
    public = {
        "schema": "agilab.notebook_agent.public_demo.v1", "status": "passed",
        "run_id": run.name, "seconds": report["seconds"], "workflow_stages": report["workflow_stages"],
        "source": {"source_kind": "github", "repository": "PyPSA/PyPSA", "commit": SOURCE_COMMIT,
                   "url": SOURCE_URL, "title": "Modular Expansion with Unit Commitment",
                   "author": "PyPSA contributors", "license": "CC-BY-4.0", "sha256": SOURCE_HASH,
                   "license_sha256": LICENSE_HASH, "introduced": "2026-02-17", "updated": "2026-08-05",
                   "adaptation": "Interactive lab, HiGHS solver, parameterized scenarios, solution checks and AGILAB batches"},
        "engine": {"repository": "ThalesGroup/agilab", "commit": ENGINE_COMMIT,
                   "path": ENGINE_PATH, "sha256": ENGINE_HASH},
        "verification_scope": "execution_interface_and_bounded_local_milp_scenario_scaling",
        "verification": {**report["verification"], "milp_energy": checks}, "files": hashes,
    }
    if "build_model" in report:
        model = report["build_model"]
        if not isinstance(model, dict) or any(
            not isinstance(model.get(key), str) or not model[key].strip()
            for key in ("id", "provider", "execution")
        ):
            raise ValueError("Invalid build model metadata")
        string_fields = {
            "id", "provider", "execution", "revision", "upstream", "upstream_revision",
            "quantization", "method", "coordination",
        }
        bool_fields = {"cloud_codegen_fallback", "tokki_agent_offload"}
        if any(key in model and not isinstance(model[key], str) for key in string_fields):
            raise ValueError("Invalid build model string metadata")
        if any(key in model and not isinstance(model[key], bool) for key in bool_fields):
            raise ValueError("Invalid build model routing metadata")
        public["build_model"] = {key: model[key] for key in sorted(string_fields | bool_fields) if key in model}
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
                      "seconds": result["seconds"], "checks": result["verification"]["milp_energy"]["checks"]}))
