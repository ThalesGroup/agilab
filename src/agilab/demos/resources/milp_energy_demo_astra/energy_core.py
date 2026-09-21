"""MILP Energy Lab. Derived notebook material: CC BY 4.0; see LICENSE.

Heavy solver imports occur only in isolated CLI / AGILAB worker processes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time

SOURCE_URL = "https://github.com/PyPSA/PyPSA/blob/c838aa498557cc8e27a9d3ed10d45e35c4b0b442/docs/examples/modular-committable.ipynb"
SHED_COST = 100000.0
TOL = 1e-5


def default_settings() -> dict:
    return dict(
        hours=4,
        demand_multiplier=1.0,
        module_mw=200.0,
        max_modules=50,
        investment_cost=1.0,
        marginal_cost=1.0,
        startup_cost=0.0,
        standby_cost=1.0,
        min_loading=0.1,
        solar_capacity=0.0,
        allow_shedding=False,
        time_limit=5.0,
        mip_rel_gap=0.0001,
    )


def validate_settings(settings: dict) -> dict:
    if type(settings) is not dict:
        raise ValueError("Settings must be an object.")
    defaults = default_settings()
    if settings.keys() - defaults.keys():
        raise ValueError(
            "Unknown settings fields: "
            + str(sorted(settings.keys() - defaults.keys(), key=str))
        )
    out = defaults | settings
    bounds = dict(
        demand_multiplier=(0.1, 2.0),
        module_mw=(50, 1000),
        investment_cost=(0, 1000),
        marginal_cost=(0, 1000),
        startup_cost=(0, 100000),
        standby_cost=(0, 10000),
        min_loading=(0, 1),
        solar_capacity=(0, 12000),
        time_limit=(0.1, 10),
        mip_rel_gap=(0, 0.05),
    )
    for key, (lo, hi) in bounds.items():
        value = out[key]
        if (
            type(value) not in (int, float)
            or not lo <= value <= hi
            or not math.isfinite(value)
        ):
            raise ValueError(f"{key} must be a finite number in [{lo}, {hi}].")
        out[key] = float(value)
    if type(out["hours"]) is not int or out["hours"] not in (4, 12, 24):
        raise ValueError("hours must be 4, 12 or 24 (integer).")
    if type(out["max_modules"]) is not int or not 1 <= out["max_modules"] <= 100:
        raise ValueError("max_modules must be an integer from 1 to 100.")
    if type(out["allow_shedding"]) is not bool:
        raise ValueError("allow_shedding must be a boolean.")
    return out


def profiles(s: dict) -> tuple[list, list]:
    # Hourly MW; longer profiles repeat the upstream stress pattern.
    demand = [
        v * s["demand_multiplier"] for v in [4000, 6000, 5000, 800] * (s["hours"] // 4)
    ]
    solar_pu = (
        [0, 0.6, 0.9, 0]
        if s["hours"] == 4
        else [
            max(0.0, math.sin(math.pi * (h / (s["hours"] - 1) * 2 - 0.5)))
            for h in range(s["hours"])
        ]
    )
    return demand, [v * s["solar_capacity"] for v in solar_pu]


def canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def model_text(s: dict) -> str:
    s = validate_settings(s)
    demand, solar = profiles(s)
    return f"""MILP Energy Lab — exact mathematical model (text, not an LP file)
One-hour snapshots t=0,...,{s["hours"] - 1}. All modules initially OFF; no terminal obligation.
N integer installed modules in [0,{s["max_modules"]}].
u[t], a[t], b[t] nonnegative integers: active, started, stopped modules.
z[t] binary: transition direction. p[t] gas MW; q[t] used solar MW; l[t] shed MW.
M={s["module_mw"]} MW/module; L={s["min_loading"]}; K={s["max_modules"]}.
0 <= u[t] <= N; L*M*u[t] <= p[t] <= M*u[t].
u[-1]=0; u[t]-u[t-1]=a[t]-b[t].
0<=a[t]<=K*z[t]; 0<=b[t]<=K*(1-z[t]).
0<=q[t]<=solar_available[t]; 0<=l[t]<=demand[t]*{int(s["allow_shedding"])}.
p[t]+q[t]+l[t]=demand[t]. Capacity = M*N MW.
Minimize {s["investment_cost"]}*M*N + sum_t(
 {s["marginal_cost"]}*p[t] + {s["standby_cost"]}*u[t]
 + {s["startup_cost"]}*a[t] + {SHED_COST}*l[t]).
Costs in illustrative cost units: investment per MW for THIS horizon,
dispatch/shedding per MWh, standby per module-hour, startup per module-start.
No annualization, ramp limits, minimum up/down durations, storage or network losses.
Solar is fixed sunk supply; unused solar is curtailed without cost.
demand={json.dumps(demand)}
solar_available={json.dumps(solar)}
settings={json.dumps(s, sort_keys=True, allow_nan=False)}
"""


def check_result(s: dict, result: dict) -> tuple[dict, dict]:
    """Independently reconstruct physical constraints and economic objective."""
    s = validate_settings(s)
    demand, available = profiles(s)
    p, u, q, shed, a, b = [
        result[k]
        for k in ("dispatch", "active_modules", "solar", "shed", "startup", "shutdown")
    ]
    if any(len(x) != s["hours"] for x in (p, u, q, shed, a, b)):
        raise ValueError("Wrong schedule length")
    n, cap = result["modules"], result["capacity_mw"]
    values = [n, cap, result["objective"]] + p + u + q + shed + a + b
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Non-finite incumbent")

    def max0(values):
        return max([0.0] + list(values))

    delta = [u[t] - (u[t - 1] if t else 0) for t in range(s["hours"])]
    costs = dict(
        investment=s["investment_cost"] * s["module_mw"] * n,
        dispatch=s["marginal_cost"] * sum(p),
        standby=s["standby_cost"] * sum(u),
        startup=s["startup_cost"] * sum(a),
        shedding=SHED_COST * sum(shed),
    )
    reconstructed = sum(costs.values())
    residuals = dict(
        integrality=max0(abs(v - round(v)) for v in [n] + u + a + b),
        balance_mw=max0(
            abs(p[t] + q[t] + shed[t] - demand[t]) for t in range(s["hours"])
        ),
        dispatch_bounds_mw=max0(
            [s["min_loading"] * s["module_mw"] * u[t] - p[t] for t in range(s["hours"])]
            + [p[t] - s["module_mw"] * u[t] for t in range(s["hours"])]
        ),
        capacity=max0(
            [abs(cap - s["module_mw"] * n), -n, n - s["max_modules"]]
            + [v - n for v in u]
        ),
        nonnegative=max0(-v for v in p + u + q + shed + a + b),
        solar_bounds_mw=max0(q[t] - available[t] for t in range(s["hours"])),
        shed_bounds_mw=max0(
            shed[t] - demand[t] * s["allow_shedding"] for t in range(s["hours"])
        ),
        transitions=max0(
            [abs(a[t] - max(0, delta[t])) for t in range(s["hours"])]
            + [abs(b[t] - max(0, -delta[t])) for t in range(s["hours"])]
        ),
        objective_absolute=abs(result["objective"] - reconstructed),
        objective_relative=abs(result["objective"] - reconstructed)
        / max(1, abs(reconstructed)),
    )
    residuals["verified"] = (
        all(v <= TOL for k, v in residuals.items() if not k.startswith("objective"))
        and residuals["objective_relative"] <= 1e-7
    )
    return costs, residuals


def _empty_result(s: dict) -> dict:
    demand, available = profiles(s)
    return dict(
        settings=s,
        input_sha256=canonical_hash(s),
        status="error",
        objective=None,
        capacity_mw=None,
        modules=None,
        dispatch=[],
        active_modules=[],
        demand=demand,
        solar=[],
        solar_available=available,
        shed=[],
        startup=[],
        shutdown=[],
        costs={},
        solver=dict(
            name="highs",
            threads=1,
            termination="not_started",
            gap=None,
            objective_bound=None,
        ),
        residuals=dict(verified=False),
        elapsed_seconds=0.0,
        model_text=model_text(s),
    )


def _solve(s: dict) -> dict:
    s = validate_settings(s)
    result = _empty_result(s)
    start = time.monotonic()
    try:
        import logging
        import pypsa
        import pandas as pd

        for name in ("pypsa", "linopy"):
            logging.getLogger(name).setLevel(logging.ERROR)
        demand, available = profiles(s)
        n = pypsa.Network(snapshots=pd.RangeIndex(s["hours"], name="snapshot"))
        n.add("Carrier", "electricity")
        n.add("Bus", "bus", carrier="electricity")
        n.add("Load", "load", bus="bus", p_set=demand)
        n.add(
            "Generator",
            "gas",
            bus="bus",
            carrier="electricity",
            p_nom_extendable=True,
            committable=True,
            p_nom_mod=s["module_mw"],
            p_nom_max=s["module_mw"] * s["max_modules"],
            p_min_pu=s["min_loading"],
            marginal_cost=s["marginal_cost"],
            capital_cost=s["investment_cost"],
            stand_by_cost=s["standby_cost"],
            start_up_cost=s["startup_cost"],
            up_time_before=0,
            down_time_before=1,
        )
        n.add(
            "Generator",
            "solar",
            bus="bus",
            carrier="electricity",
            p_nom=s["solar_capacity"],
            p_max_pu=[
                v / s["solar_capacity"] if s["solar_capacity"] else 0 for v in available
            ],
        )
        n.add(
            "Generator",
            "shed",
            bus="bus",
            carrier="electricity",
            p_nom=max(demand) if s["allow_shedding"] else 0,
            marginal_cost=SHED_COST,
            p_max_pu=[v / max(demand) for v in demand],
        )
        m = n.optimize.create_model()
        u = m["Generator-status"].sel(name="gas")
        a = m["Generator-start_up"].sel(name="gas")
        b = m["Generator-shut_down"].sel(name="gas")
        # Linopy's fill_value addresses variable labels, not numerical constants.
        # Its default missing label (-1) correctly omits the pre-horizon term.
        previous = u.shift(snapshot=1)
        z = m.add_variables(
            binary=True, coords=[n.snapshots], name="transition_direction"
        )
        # Tighten PyPSA's transition inequalities to exact counts, even with zero costs.
        m.add_constraints(u - previous == a - b, name="exact_transitions")
        m.add_constraints(a <= s["max_modules"] * z, name="start_direction")
        m.add_constraints(b <= s["max_modules"] * (1 - z), name="stop_direction")
        m.solve(
            solver_name="highs",
            io_api="direct",
            threads=1,
            time_limit=s["time_limit"],
            mip_rel_gap=s["mip_rel_gap"],
            log_to_console=False,
        )
        h = m.solver_model
        info, solution = h.getInfo(), h.getSolution()
        termination = h.modelStatusToString(h.getModelStatus())
        result["solver"]["termination"] = termination
        for key, attr in [("gap", "mip_gap"), ("objective_bound", "mip_dual_bound")]:
            value = getattr(info, attr, None)
            result["solver"][key] = (
                float(value)
                if info.valid and value is not None and math.isfinite(value)
                else None
            )
        # Read raw HiGHS columns by Linopy labels: usable even at a time limit.
        if not solution.value_valid or info.primal_solution_status != 2:
            result["status"] = (
                "infeasible" if termination.lower() == "infeasible" else "error"
            )
            result["message"] = (
                "No physically feasible schedule under these constraints."
                if result["status"] == "infeasible"
                else "No verified incumbent returned; no objective or schedule is reported."
            )
        else:

            def vals(name, component):
                labels = m[name].sel(name=component).labels.values.reshape(-1)
                return [float(solution.col_value[int(i)]) for i in labels]

            modules = vals("Generator-n_mod", "gas")[0]
            result.update(
                objective=float(info.objective_function_value),
                modules=modules,
                capacity_mw=vals("Generator-p_nom", "gas")[0],
                dispatch=vals("Generator-p", "gas"),
                active_modules=vals("Generator-status", "gas"),
                solar=vals("Generator-p", "solar"),
                shed=vals("Generator-p", "shed"),
                startup=vals("Generator-start_up", "gas"),
                shutdown=vals("Generator-shut_down", "gas"),
            )
            result["costs"], result["residuals"] = check_result(s, result)
            if not result["residuals"]["verified"]:
                raise ValueError(
                    "Incumbent failed independent physical/objective checks"
                )
            result["status"] = (
                "optimal" if termination.lower() == "optimal" else "feasible"
            )
            result["physical_supply_sufficient"] = sum(result["shed"]) <= TOL
            result["message"] = (
                "Demand served without shedding."
                if result["physical_supply_sufficient"]
                else "Feasible with load shedding: the schedule contains unserved demand."
            )
    except Exception as exc:
        result = _empty_result(s) | dict(message=f"{type(exc).__name__}: {exc}")
    result["elapsed_seconds"] = time.monotonic() - start
    json.dumps(result, allow_nan=False)
    return result


def solve_scenario(settings: dict) -> dict:
    """Validated public API; all solver work is isolated from the calling process."""
    from energy_runner import run_scenario

    return run_scenario(validate_settings(settings))


def cpu_limits() -> dict:
    limits = {"os.cpu_count": os.cpu_count() or 1, "public_cap": 4}
    process_count = getattr(os, "process_cpu_count", lambda: None)()
    if process_count:
        limits["os.process_cpu_count"] = process_count
    if hasattr(os, "sched_getaffinity"):
        limits["affinity"] = len(os.sched_getaffinity(0))
    raw = os.environ.get("CPU_CORES")
    if raw is not None:
        try:
            value = float(raw)
            limits["SPACE CPU_CORES"] = (
                max(1, math.floor(value)) if math.isfinite(value) and value > 0 else 1
            )
        except ValueError:
            limits["SPACE CPU_CORES"] = 1
    # Walk visible cgroup ancestry; a parent's quota can be tighter than a child's.
    roots = [
        Path("/sys/fs/cgroup"),
        Path("/sys/fs/cgroup/cpu"),
        Path("/sys/fs/cgroup/cpu,cpuacct"),
    ]
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            _, controllers, rel = line.split(":", 2)
            if not controllers or "cpu" in controllers.split(","):
                for base in list(roots[:3]):
                    path = base / rel.lstrip("/")
                    if ".." not in path.parts:
                        while path != base and path.is_relative_to(base):
                            roots.append(path)
                            path = path.parent
    except (OSError, ValueError):
        pass
    quotas = []
    for path in set(roots):
        try:
            quota, period = (path / "cpu.max").read_text().split()
            if quota != "max" and int(period) > 0:
                quotas.append(max(1, int(quota) // int(period)))
        except (OSError, ValueError):
            pass
        try:
            quota = int((path / "cpu.cfs_quota_us").read_text())
            period = int((path / "cpu.cfs_period_us").read_text())
            if quota > 0 and period > 0:
                quotas.append(max(1, quota // period))
        except (OSError, ValueError):
            pass
    if quotas:
        limits["cgroup quota"] = min(quotas)
    return dict(effective_cpus=max(1, min(limits.values())), limits=limits)


def make_batch(settings: dict, count: int = 4) -> list:
    s = validate_settings(settings)
    if type(count) is not int or count not in (4, 8, 12):
        raise ValueError("Batch size must be 4, 8 or 12.")
    return [
        validate_settings(
            s
            | dict(
                demand_multiplier=round(0.65 + 0.1 * (i % 8), 2),
                startup_cost=float((i % 3) * 250),
                solar_capacity=float((i % 4) * 400),
            )
        )
        for i in range(count)
    ]


def validate_batch(batch: list, workers: int) -> list:
    if type(batch) is not list or len(batch) not in (4, 8, 12):
        raise ValueError("Batch must contain 4, 8 or 12 scenarios.")
    if type(workers) is not int or not 1 <= workers <= cpu_limits()["effective_cpus"]:
        raise ValueError("Worker count exceeds the effective CPU/public limit.")
    return [validate_settings(s) for s in batch]


def _spawn_executor(**kwargs):
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing

    return ProcessPoolExecutor(
        mp_context=multiprocessing.get_context("spawn"), **kwargs
    )


def _is_frame(frame):
    return isinstance(frame, list)


def _is_empty(frame):
    return not frame


def _concat(frames, labels):
    return [
        row | {"engine_label": label}
        for frame, label in zip(frames, labels)
        for row in frame
    ]


def _hooks():
    from agilab_pool import PoolFrameHooks

    return PoolFrameHooks(
        "MILP list frames",
        "process",
        _spawn_executor,
        _is_frame,
        _is_empty,
        _concat,
        list,
    )


class ScenarioWorker:
    """Picklable list-frame adapter for the unmodified AGILAB pool engine."""

    def __init__(self, workers):
        self._worker_id = 0
        self._mode = 1 if workers > 1 else 0
        self.args = dict(pool_max_workers=workers, pool_item_timeout=30)
        self.pool_vars = None
        self.rows = []

    def work_init(self):
        pass

    def pool_init(self, pool_vars):
        pass

    def work_pool(self, item):
        index, settings = item
        start = time.monotonic()
        result = _solve(settings)
        return [
            dict(
                case=index,
                pid=os.getpid(),
                start_monotonic=start,
                end_monotonic=time.monotonic(),
                result=result,
            )
        ]

    def work_done(self, frame):
        self.rows.extend(frame)

    def stop(self):
        pass

    def _exec_mono_process(self, plan, metadata):
        from agilab_pool import exec_mono_process

        exec_mono_process(self, plan, metadata, _hooks())

    def _exec_multi_process(self, plan, metadata):
        from agilab_pool import exec_multi_process

        exec_multi_process(self, plan, metadata, _hooks())


def _batch(batch, workers):
    from agilab_pool import run_works

    batch = validate_batch(batch, workers)
    worker = ScenarioWorker(workers)
    elapsed = run_works(worker, [[list(enumerate(batch))]], None)
    return dict(
        batch=batch,
        batch_sha256=canonical_hash(batch),
        workers=workers,
        environment=cpu_limits(),
        engine_seconds=elapsed,
        rows=worker.rows,
    )


def main():
    parser = argparse.ArgumentParser(description="Bounded MILP Energy Lab JSON CLI")
    parser.add_argument("mode", choices=["single", "batch"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text())
    if os.environ.get("MILP_ENERGY_CHILD") == "1":
        import signal

        def terminate(signum, frame):
            # Unwind the AGILAB executor so it reaps its workers on group TERM.
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, terminate)
        result = (
            _solve(payload)
            if args.mode == "single"
            else _batch(payload["batch"], payload["workers"])
        )
    else:
        from energy_runner import run_scenario, run_batch

        result = (
            run_scenario(payload)
            if args.mode == "single"
            else run_batch(payload["batch"], payload["workers"])
        )
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
