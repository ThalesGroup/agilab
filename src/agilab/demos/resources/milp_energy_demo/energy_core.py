#!/usr/bin/env python3
"""energy_core.py – PyPSA modular MILP lab (PyPSA 1.2.4, Linopy 0.9.1, highspy 1.15.1)."""

import json
import math
import os
import sys
import time
import logging
import numpy as np
import pandas as pd

log = logging.getLogger("energy_core")
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_KNOWN_KEYS = {
    "hours", "demand_multiplier", "module_mw", "max_modules",
    "min_loading", "investment_cost", "marginal_cost", "standby_cost",
    "startup_cost", "solar_capacity", "allow_shedding",
    "solver_time_limit", "mip_rel_gap",
}

def default_settings():
    return {
        "hours": 4,
        "demand_multiplier": 1.0,
        "module_mw": 200.0,
        "max_modules": 50,
        "min_loading": 0.1,
        "investment_cost": 1.0,
        "marginal_cost": 1.0,
        "standby_cost": 1.0,
        "startup_cost": 0.0,
        "solar_capacity": 0.0,
        "allow_shedding": False,
        "solver_time_limit": 10.0,
        "mip_rel_gap": 0.0,
    }

def _is_strict_int(v):
    return isinstance(v, int) and not isinstance(v, bool)

def _is_strict_bool(v):
    return isinstance(v, bool)

def _is_finite_real(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return math.isfinite(v)
    return False

def validate_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("settings must be a dict")
    keys = set(settings.keys())
    if keys != _KNOWN_KEYS:
        missing = _KNOWN_KEYS - keys
        extra = keys - _KNOWN_KEYS
        raise ValueError(f"settings keys mismatch. missing={sorted(missing)}, extra={sorted(extra)}")

    s = dict(settings)

    # hours: strict int, in (4,12,24)
    if not _is_strict_int(s["hours"]) or s["hours"] not in (4, 12, 24):
        raise ValueError(f"hours must be a strict int in (4,12,24), got {s['hours']!r}")

    # max_modules: strict int, 1..200
    if not _is_strict_int(s["max_modules"]) or not (1 <= s["max_modules"] <= 200):
        raise ValueError(f"max_modules must be a strict int in 1..200, got {s['max_modules']!r}")

    # allow_shedding: strict bool
    if not _is_strict_bool(s["allow_shedding"]):
        raise ValueError(f"allow_shedding must be a strict bool, got {s['allow_shedding']!r}")

    # Finite real fields with ranges
    ranges = {
        "demand_multiplier": (0.1, 3.0),
        "module_mw": (10.0, 1000.0),
        "min_loading": (0.0, 1.0),
        "investment_cost": (0.0, 1000.0),
        "marginal_cost": (0.01, 1000.0),
        "standby_cost": (0.0, 10000.0),
        "startup_cost": (0.0, 10000.0),
        "solar_capacity": (0.0, 20000.0),
        "solver_time_limit": (0.1, 10.0),
        "mip_rel_gap": (0.0, 0.1),
    }
    for k, (lo, hi) in ranges.items():
        v = s[k]
        if not _is_finite_real(v):
            raise ValueError(f"{k} must be a finite real (not bool), got {v!r}")
        if not (lo <= v <= hi):
            raise ValueError(f"{k} must be in [{lo}, {hi}], got {v}")

    return s


def _demand_profile(hours, multiplier):
    base = np.array([4000.0, 6000.0, 5000.0, 800.0])
    reps = hours // 4
    d = np.tile(base, reps) * multiplier
    return d

def _solar_profile(hours):
    if hours == 4:
        return np.array([0.0, 0.6, 0.9, 0.0])
    h = np.arange(hours)
    return np.maximum(0.0, np.sin(np.pi * (h / (hours - 1) * 2.0 - 0.5)))


def _build_network(s):
    import pypsa

    hours = s["hours"]
    demand = _demand_profile(hours, s["demand_multiplier"])
    solar_pu = _solar_profile(hours)

    n = pypsa.Network(snapshots=range(hours))
    n.add("Carrier", "electricity")
    n.add("Bus", "bus", carrier="electricity")
    n.add("Load", "load", bus="bus", p_set=demand)

    n.add("Generator", "modular_gas",
        bus="bus",
        carrier="electricity",
        p_nom_extendable=True,
        committable=True,
        p_nom_mod=s["module_mw"],
        p_nom_max=s["max_modules"] * s["module_mw"],
        p_min_pu=s["min_loading"],
        marginal_cost=s["marginal_cost"],
        capital_cost=s["investment_cost"],
        stand_by_cost=s["standby_cost"],
        start_up_cost=s["startup_cost"],
        up_time_before=0,
    )

    if s["solar_capacity"] > 0:
        n.add("Generator", "solar",
            bus="bus",
            carrier="electricity",
            p_nom=s["solar_capacity"],
            p_max_pu=solar_pu,
            marginal_cost=0.0,
        )

    if s["allow_shedding"]:
        max_d = float(np.max(demand))
        if max_d > 0:
            n.add("Generator", "shedding",
                bus="bus",
                carrier="electricity",
                p_nom=max_d,
                p_max_pu=demand / max_d,
                marginal_cost=100000.0,
            )

    return n, demand, solar_pu


def _extract_solutions(n, s, demand, solar_pu):
    """Extract solution arrays from Linopy variables after gate passes."""
    hours = s["hours"]
    snap_idx = list(range(hours))

    # Modules (scalar)
    n_mod = n.model.variables["Generator-n_mod"].solution.sel(name="modular_gas")
    modules = float(n_mod)

    # Active (per snapshot)
    status = n.model.variables["Generator-status"].solution.sel(name="modular_gas")
    active = np.array([float(status.loc[si]) for si in snap_idx])

    # Gas dispatch
    gas_p = n.model.variables["Generator-p"].solution.sel(name="modular_gas")
    gas = np.array([float(gas_p.loc[si]) for si in snap_idx])

    # Solar
    if s["solar_capacity"] > 0:
        sol_p = n.model.variables["Generator-p"].solution.sel(name="solar")
        solar = np.array([float(sol_p.loc[si]) for si in snap_idx])
    else:
        solar = np.zeros(hours)

    # Shedding
    if s["allow_shedding"]:
        shed_p = n.model.variables["Generator-p"].solution.sel(name="shedding")
        shed = np.array([float(shed_p.loc[si]) for si in snap_idx])
    else:
        shed = np.zeros(hours)

    return modules, active, gas, solar, shed


def _derive_transitions(active):
    startup = np.zeros_like(active)
    shutdown = np.zeros_like(active)
    prev = 0.0
    for i in range(len(active)):
        startup[i] = max(active[i] - prev, 0.0)
        shutdown[i] = max(prev - active[i], 0.0)
        prev = active[i]
    return startup, shutdown


def _physical_validation(s, modules, active, gas, solar, shed, demand, solar_pu, objective):
    """Returns (ok, error_msg, costs, residuals)."""
    hours = s["hours"]
    tol = 1e-5
    rel_tol = 1e-7
    abs_tol = 1e-4

    # Finite arrays correct horizon
    for name, arr in [("modules", np.array([modules])), ("active", active), ("gas", gas),
                       ("solar", solar), ("shed", shed), ("demand", demand)]:
        if not np.all(np.isfinite(arr)):
            return False, f"non-finite values in {name}", None, None
    if len(active) != hours or len(gas) != hours or len(solar) != hours or len(shed) != hours:
        return False, "array horizon mismatch", None, None

    # Module and active integers
    if abs(modules - round(modules)) > tol:
        return False, f"modules={modules} not integer within tol", None, None
    if not np.all(np.abs(active - np.round(active)) <= tol):
        return False, "active not integer within tol", None, None

    modules_i = int(round(modules))
    active_i = np.round(active).astype(int)

    # 0 <= active <= installed <= max
    if modules_i < 0 or modules_i > s["max_modules"]:
        return False, f"modules={modules_i} out of [0, max_modules={s['max_modules']}]", None, None
    if np.any(active_i < 0) or np.any(active_i > modules_i):
        return False, "active out of [0, installed]", None, None

    capacity = modules_i * s["module_mw"]

    # 0 <= gas between min_loading*module*active and module*active
    gas_lo = s["min_loading"] * s["module_mw"] * active_i
    gas_hi = s["module_mw"] * active_i
    if np.any(gas < gas_lo - tol) or np.any(gas > gas_hi + tol):
        return False, "gas dispatch outside [min_loading*module*active, module*active]", None, None

    # solar: non-negative and <= available
    solar_avail = s["solar_capacity"] * solar_pu
    if np.any(solar < -tol):
        return False, "solar negative", None, None
    if np.any(solar > solar_avail + tol):
        return False, "solar exceeds available", None, None

    # shed: non-negative, <= demand, and only allowed
    if np.any(shed < -tol):
        return False, "shed negative", None, None
    if not s["allow_shedding"] and np.any(shed > tol):
        return False, "shedding present but not allowed", None, None
    if np.any(shed > demand + tol):
        return False, "shed exceeds demand", None, None

    # gas + solar + shed == demand (strict balance within 1e-5)
    balance = gas + solar + shed - demand
    if np.max(np.abs(balance)) > tol:
        return False, f"balance residual max={np.max(np.abs(balance)):.6f} exceeds tol", None, None

    # Derived transitions
    startup, shutdown = _derive_transitions(active_i.astype(float))

    # Objective check
    investment = s["investment_cost"] * capacity
    fuel = float(np.sum(gas * s["marginal_cost"]))
    standby = float(np.sum(active_i * s["standby_cost"]))
    startup_cost_total = float(np.sum(startup * s["startup_cost"]))
    shedding_cost = float(np.sum(shed * 100000.0))
    total = investment + fuel + standby + startup_cost_total + shedding_cost

    if not math.isfinite(objective):
        return False, "objective not finite", None, None

    obj_diff = abs(total - objective)
    if obj_diff > abs_tol + rel_tol * abs(objective):
        return False, f"objective mismatch: computed={total:.6f} vs solver={objective:.6f} (diff={obj_diff:.6f})", None, None

    costs = {
        "investment": investment,
        "fuel": fuel,
        "standby": standby,
        "startup": startup_cost_total,
        "shedding": shedding_cost,
        "total": total,
    }

    residuals = {
        "balance_max": float(max(0.0, np.max(np.abs(balance)))),
        "gas_bounds_max": float(max(0.0, np.max(np.maximum(gas_lo - gas, gas - gas_hi)))),
        "solar_avail_max": float(max(0.0, np.max(np.maximum(0, solar - solar_avail)))),
        "shed_demand_max": float(max(0.0, np.max(np.maximum(0, shed - demand)))),
    }
    for rk, rv in residuals.items():
        if not math.isfinite(rv):
            return False, f"residual {rk} not finite", None, None

    return True, None, costs, residuals


def solve_scenario(settings):
    s = validate_settings(settings)
    t0 = time.time()

    n, demand, solar_pu = _build_network(s)

    try:
        n.optimize(
            solver_name="highs",
            threads=1,
            time_limit=s["solver_time_limit"],
            mip_rel_gap=s["mip_rel_gap"],
            log_to_console=False,
        )
    except Exception as e:
        elapsed = time.time() - t0
        return {
            "settings": s,
            "status": "error",
            "objective": None,
            "modules": None,
            "capacity_mw": None,
            "dispatch": [],
            "active_modules": [],
            "solar": [],
            "shed": [],
            "startup": [],
            "shutdown": [],
            "demand": demand.tolist(),
            "solar_available": (s["solar_capacity"] * solar_pu).tolist(),
            "costs": {},
            "solver": {"name": "highs", "threads": 1, "termination": "exception", "gap": None, "bound": None, "incumbent": False},
            "residuals": {},
            "elapsed_seconds": elapsed,
            "transition_method": "derived from active module counts",
            "error": f"optimize raised: {type(e).__name__}: {e}",
        }

    elapsed = time.time() - t0

    # Access highspy model
    import highspy

    h = n.model.solver_model
    info = h.getInfo()
    sol = h.getSolution()
    status = h.getModelStatus()
    termination = h.modelStatusToString(status)

    # Gate: valid incumbent
    has_incumbent = (
        info.valid
        and sol.value_valid
        and info.primal_solution_status == int(highspy.SolutionStatus.kSolutionStatusFeasible)
    )

    # Objective from info
    obj_val = info.objective_function_value
    if not math.isfinite(obj_val):
        obj_val = None

    gap_val = info.mip_gap
    if not math.isfinite(gap_val):
        gap_val = None

    bound_val = info.mip_dual_bound
    if not math.isfinite(bound_val):
        bound_val = None

    solver_dict = {
        "name": "highs",
        "threads": 1,
        "termination": termination,
        "gap": gap_val,
        "bound": bound_val,
        "incumbent": bool(has_incumbent),
    }

    # Determine status
    if status == highspy.HighsModelStatus.kOptimal and has_incumbent:
        status_str = "optimal"
    elif has_incumbent:
        status_str = "feasible"
    elif status == highspy.HighsModelStatus.kInfeasible:
        status_str = "infeasible"
    else:
        status_str = "error"

    # Non-incumbent: empty schedules
    if not has_incumbent:
        return {
            "settings": s,
            "status": status_str,
            "objective": None,
            "modules": None,
            "capacity_mw": None,
            "dispatch": [],
            "active_modules": [],
            "solar": [],
            "shed": [],
            "startup": [],
            "shutdown": [],
            "demand": demand.tolist(),
            "solar_available": (s["solar_capacity"] * solar_pu).tolist(),
            "costs": {},
            "solver": solver_dict,
            "residuals": {},
            "elapsed_seconds": elapsed,
            "transition_method": "derived from active module counts",
        }

    # Extract solutions
    try:
        modules, active, gas, solar, shed = _extract_solutions(n, s, demand, solar_pu)
    except Exception as e:
        return {
            "settings": s,
            "status": "error",
            "objective": None,
            "modules": None,
            "capacity_mw": None,
            "dispatch": [],
            "active_modules": [],
            "solar": [],
            "shed": [],
            "startup": [],
            "shutdown": [],
            "demand": demand.tolist(),
            "solar_available": (s["solar_capacity"] * solar_pu).tolist(),
            "costs": {},
            "solver": solver_dict,
            "residuals": {},
            "elapsed_seconds": elapsed,
            "transition_method": "derived from active module counts",
            "error": f"solution extraction failed: {type(e).__name__}: {e}",
        }

    # Physical validation
    ok, err_msg, costs, residuals = _physical_validation(
        s, modules, active, gas, solar, shed, demand, solar_pu, obj_val
    )

    if not ok:
        return {
            "settings": s,
            "status": "error",
            "objective": None,
            "modules": None,
            "capacity_mw": None,
            "dispatch": [],
            "active_modules": [],
            "solar": [],
            "shed": [],
            "startup": [],
            "shutdown": [],
            "demand": demand.tolist(),
            "solar_available": (s["solar_capacity"] * solar_pu).tolist(),
            "costs": {},
            "solver": solver_dict,
            "residuals": {},
            "elapsed_seconds": elapsed,
            "transition_method": "derived from active module counts",
            "error": f"physical validation failed: {err_msg}",
        }

    # Normalize after integrality check passed
    modules_i = int(round(modules))
    active_i = np.round(active).astype(int)
    startup, shutdown = _derive_transitions(active_i.astype(float))
    capacity = modules_i * s["module_mw"]

    return {
        "settings": s,
        "status": status_str,
        "objective": obj_val,
        "modules": modules_i,
        "capacity_mw": capacity,
        "dispatch": gas.tolist(),
        "active_modules": active_i.tolist(),
        "solar": solar.tolist(),
        "shed": shed.tolist(),
        "startup": startup.tolist(),
        "shutdown": shutdown.tolist(),
        "demand": demand.tolist(),
        "solar_available": (s["solar_capacity"] * solar_pu).tolist(),
        "costs": costs,
        "solver": solver_dict,
        "residuals": residuals,
        "elapsed_seconds": elapsed,
        "transition_method": "derived from active module counts",
    }


def make_batch(settings, count):
    if not _is_strict_int(count) or count not in (4, 8, 12):
        raise ValueError(f"count must be a strict int in (4, 8, 12), got {count!r}")
    base = validate_settings(settings)
    results = []
    for i in range(count):
        s = dict(base)
        # Deterministic bounded relative factor centered around 1
        factor = 1.0 + 0.1 * (i - (count - 1) / 2.0)
        s["demand_multiplier"] = max(0.1, min(3.0, factor * base["demand_multiplier"]))
        validate_settings(s)
        results.append(s)
    return results


def cpu_limits():
    """Return effective_cpus and observed caps."""
    caps = []

    # Host CPUs
    try:
        import os
        host_cpus = os.cpu_count()
        if host_cpus is not None:
            caps.append(float(host_cpus))
    except Exception:
        pass

    # Process affinity
    try:
        import os
        aff = os.sched_getaffinity(0)
        caps.append(float(len(aff)))
    except (AttributeError, OSError):
        pass

    # Linux cgroup v2
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            parts = f.read().split()
            if parts[0] != "max":
                quota = int(parts[0])
                period = int(parts[1])
                if period > 0:
                    caps.append(quota / period)
    except (FileNotFoundError, ValueError, IndexError, OSError):
        pass

    # Linux cgroup v1
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            period = int(f.read().strip())
        if quota > 0 and period > 0:
            caps.append(quota / period)
    except (FileNotFoundError, ValueError, OSError):
        pass

    # CPU_CORES env
    cpu_cores_env = os.environ.get("CPU_CORES")
    if cpu_cores_env is not None:
        try:
            val = float(cpu_cores_env)
            if val <= 0:
                raise ValueError(f"CPU_CORES must be positive, got {val}")
            caps.append(math.floor(val))
        except ValueError as e:
            raise ValueError(f"CPU_CORES invalid: {e}")

    if not caps:
        effective = 1
    else:
        effective = max(1, min(4, int(math.floor(min(caps)))))

    return {
        "effective_cpus": effective,
        "observed_caps": [round(c, 4) for c in caps],
    }


def model_artifact_text(settings):
    s = validate_settings(settings)
    hours = s["hours"]
    demand = _demand_profile(hours, s["demand_multiplier"])
    solar_pu = _solar_profile(hours)
    max_cap = s["max_modules"] * s["module_mw"]

    lines = [
        "PyPSA Modular MILP – Descriptive Formulation",
        "=" * 50,
        "",
        f"Horizon: {hours} snapshots",
        f"Demand profile (MW): {demand.tolist()}",
        f"Solar availability (pu): {solar_pu.tolist()}",
        "",
        "Decision Variables:",
        f"  n_mod (modular_gas): integer, 0..{s['max_modules']} installed modules",
        f"  status (modular_gas): integer, 0..n_mod active modules per snapshot",
        f"  p (modular_gas): continuous, {s['min_loading']}*{s['module_mw']}*status <= p <= {s['module_mw']}*status per snapshot",
    ]
    if s["solar_capacity"] > 0:
        lines.append(f"  p (solar): continuous, 0..{s['solar_capacity']}*solar_pu per snapshot")
    if s["allow_shedding"]:
        lines.append(f"  p (shedding): continuous, 0..demand per snapshot")

    lines += [
        "",
        "Constraints:",
        "  Power balance: gas + solar + shed == demand (per snapshot)",
        f"  Gas bounds: {s['min_loading']}*{s['module_mw']}*status <= p_gas <= {s['module_mw']}*status",
        f"  Capacity: p_nom = n_mod * {s['module_mw']} MW, max {max_cap} MW",
        "",
        "Objective (minimize):",
        f"  {s['investment_cost']} * n_mod * {s['module_mw']} + sum(p_gas * {s['marginal_cost']} + status * {s['standby_cost']} + startup * {s['startup_cost']}"
        + (f" + shed * 100000" if s["allow_shedding"] else "")
        + ")",
        "",
        "Parameters:",
        f"  module_mw={s['module_mw']}, max_modules={s['max_modules']}, min_loading={s['min_loading']}",
        f"  investment_cost={s['investment_cost']} (per MW per horizon), marginal_cost={s['marginal_cost']}",
        f"  standby_cost={s['standby_cost']}, startup_cost={s['startup_cost']}",
        f"  solar_capacity={s['solar_capacity']}, allow_shedding={s['allow_shedding']}",
        f"  solver_time_limit={s['solver_time_limit']}s, mip_rel_gap={s['mip_rel_gap']}",
        "",
        "Note: This is a descriptive formulation of the in-memory model, not an exported solver LP file.",
    ]
    return "\n".join(lines)


def _main():
    import argparse
    parser = argparse.ArgumentParser(description="PyPSA modular MILP lab")
    parser.add_argument("--settings", type=str, required=True, help="JSON settings")
    args = parser.parse_args()

    try:
        settings = json.loads(args.settings)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    try:
        result = solve_scenario(settings)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}

    # Ensure all floats are finite for JSON
    def _sanitize(obj):
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_sanitize(v) for v in obj]
        if isinstance(obj, float):
            if not math.isfinite(obj):
                return None
            return obj
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            v = float(obj)
            return v if math.isfinite(v) else None
        return obj

    result = _sanitize(result)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    _main()