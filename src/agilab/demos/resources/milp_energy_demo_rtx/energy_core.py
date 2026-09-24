"""Parameterized modular-unit-commitment MILP scenarios (PyPSA + HiGHS).

Each scenario is a small, hand-checkable instance of "modular expansion with
unit commitment": one electricity bus, a fixed load profile, an extendable
committable generator built in fixed-size modules, an optional flat solar
resource, and optional load shedding.

The public surface is intentionally tiny so the independent validator can call
it without touching the rest of the project:

* :func:`default_settings` - the reference scenario parameters.
* :func:`solve_scenario`   - build + solve one scenario, return a flat dict.
* :func:`make_batch`       - deterministic fan-out of scenarios for benchmarks.
* :func:`cpu_limits`       - report the effective CPU budget for scaling tests.
"""

from __future__ import annotations

import math
import os
from typing import Any

import pandas as pd

SOLVER_NAME = "highs"
_SOLVER_THREADS = 1

# Base four-hour load shape (MW); a scenario repeats this ``hours // 4`` times.
_BASE_DEMAND = (4000.0, 6000.0, 5000.0, 800.0)
# Hourly solar capacity factor over the base four hours (fraction of capacity).
_BASE_SOLAR_PU = (0.0, 0.6, 0.9, 0.0)


def default_settings() -> dict[str, Any]:
    """Reference scenario parameters (the hand-checkable 21879 optimum)."""
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
        "shed_cost": 100000.0,
    }


def _normalize(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Fill missing keys with defaults and cast to canonical types."""
    base = default_settings()
    merged = dict(base)
    for key in base:
        if settings and key in settings:
            merged[key] = settings[key]
    merged["hours"] = int(merged["hours"])
    merged["demand_multiplier"] = float(merged["demand_multiplier"])
    merged["module_mw"] = float(merged["module_mw"])
    merged["max_modules"] = int(merged["max_modules"])
    merged["min_loading"] = float(merged["min_loading"])
    merged["investment_cost"] = float(merged["investment_cost"])
    merged["marginal_cost"] = float(merged["marginal_cost"])
    merged["standby_cost"] = float(merged["standby_cost"])
    merged["startup_cost"] = float(merged["startup_cost"])
    merged["solar_capacity"] = float(merged["solar_capacity"])
    merged["allow_shedding"] = bool(merged["allow_shedding"])
    merged["shed_cost"] = float(merged["shed_cost"])
    return merged


def _demand_profile(s: dict[str, Any]) -> list[float]:
    repeats = max(1, s["hours"] // 4)
    base = _BASE_DEMAND * repeats
    return [value * s["demand_multiplier"] for value in base[: s["hours"]]]


def _solar_profile(s: dict[str, Any]) -> list[float]:
    if s["hours"] == 4:
        return list(_BASE_SOLAR_PU)
    span = s["hours"] - 1
    return [
        max(0.0, math.sin(math.pi * (hour / span * 2 - 0.5)))
        for hour in range(s["hours"])
    ]


def _transitions(active: list[int]) -> tuple[list[int], list[int]]:
    """Naive module-transition counts the validator reconstructs by hand."""
    startup: list[int] = []
    shutdown: list[int] = []
    previous = 0
    for count in active:
        startup.append(max(0, count - previous))
        shutdown.append(max(0, previous - count))
        previous = count
    return startup, shutdown


def _build_network(s: dict[str, Any]) -> tuple[pypsa.Network, list[float]]:
    # Imported here (not at module scope) so merely importing energy_core
    # never loads pypsa/PROJ; the solver subprocess builds the Network only
    # when a solve is actually requested.
    import pypsa

    demand = _demand_profile(s)
    snapshots = range(s["hours"])
    network = pypsa.Network(snapshots=snapshots)
    network.add("Bus", "bus", carrier="electricity")
    network.add("Carrier", "electricity")
    network.add("Load", "load", bus="bus", p_set=demand)
    network.add(
        "Generator",
        "gas",
        bus="bus",
        p_nom_extendable=True,
        committable=True,
        p_nom_mod=s["module_mw"],
        p_nom_max=s["module_mw"] * s["max_modules"],
        p_min_pu=s["min_loading"],
        marginal_cost=s["marginal_cost"],
        capital_cost=s["investment_cost"],
        stand_by_cost=s["standby_cost"],
        start_up_cost=s["startup_cost"],
    )
    if s["solar_capacity"] > 0:
        solar_pu = pd.Series(_solar_profile(s), index=snapshots)
        network.add(
            "Generator",
            "solar",
            bus="bus",
            p_nom=s["solar_capacity"],
            marginal_cost=0.0,
            p_max_pu=solar_pu,
        )
    if s["allow_shedding"]:
        # Unserved demand is a non-committable sink generator priced at the
        # shedding cost: it absorbs exactly the shortfall of every hour.
        network.add(
            "Generator",
            "shed",
            bus="bus",
            p_nom_extendable=True,
            p_nom_min=0.0,
            p_nom_max=float("inf"),
            p_min_pu=0.0,
            p_max_pu=1.0,
            marginal_cost=s["shed_cost"],
        )
    return network, demand


def _optimize(network: pypsa.Network) -> tuple[str, float | None]:
    import logging
    import warnings

    logger = logging.getLogger("linopy")
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _, condition = network.optimize(
                solver_name=SOLVER_NAME,
                solver_options={"threads": str(_SOLVER_THREADS)},
                log_to_console=False,
                include_objective_constant=False,
            )
    finally:
        logger.setLevel(previous_level)
    if condition in ("optimal", "optimal_gap"):
        return "optimal", None
    return condition, None


def solve_scenario(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build, solve and summarise one scenario as a flat, JSON-safe dict."""
    s = _normalize(settings)
    network, demand = _build_network(s)
    status, _ = _optimize(network)

    if status != "optimal":
        return {
            "status": "infeasible",
            "objective": None,
            "dispatch": [],
            "demand": [],
            "active_modules": [],
            "solar": [],
            "shed": [],
            "startup": [],
            "shutdown": [],
            "capacity_mw": 0.0,
            "modules": 0,
            "solver": {"name": SOLVER_NAME, "threads": _SOLVER_THREADS},
            "settings": s,
        }

    dispatch = [float(value) for value in network.generators_t.p["gas"].tolist()]
    active = [int(value) for value in network.generators_t.status["gas"].tolist()]
    solar = (
        [float(value) for value in network.generators_t.p["solar"].tolist()]
        if s["solar_capacity"] > 0
        else [0.0] * s["hours"]
    )
    if s["allow_shedding"]:
        shed = [float(value) for value in network.generators_t.p["shed"].tolist()]
    else:
        shed = [0.0] * s["hours"]
    capacity = float(network.generators.p_nom_opt["gas"])
    modules = int(round(capacity / s["module_mw"]))
    startup, shutdown = _transitions(active)

    objective = s["investment_cost"] * s["module_mw"] * modules
    for hour in range(s["hours"]):
        objective += (
            dispatch[hour] * s["marginal_cost"]
            + active[hour] * s["standby_cost"]
            + startup[hour] * s["startup_cost"]
            + shed[hour] * 100000.0
        )

    return {
        "status": "optimal",
        "objective": float(objective),
        "dispatch": dispatch,
        "demand": demand,
        "active_modules": active,
        "solar": solar,
        "shed": shed,
        "startup": startup,
        "shutdown": shutdown,
        "capacity_mw": float(capacity),
        "modules": modules,
        "solver": {"name": SOLVER_NAME, "threads": _SOLVER_THREADS},
        "settings": s,
    }


def make_batch(settings: dict[str, Any] | None, count: int) -> list[dict[str, Any]]:
    """Deterministically fan a base scenario out into ``count`` variants.

    Each variant scales the demand profile so the batch is not four identical
    solves; the first variant is exactly the base scenario.
    """
    base = _normalize(settings)
    batch: list[dict[str, Any]] = []
    for index in range(int(count)):
        variant = dict(base)
        variant["demand_multiplier"] = base["demand_multiplier"] * (1.0 + 0.05 * index)
        batch.append(variant)
    return batch


def _effective_cpus() -> int:
    candidates: list[int] = []
    try:
        if hasattr(os, "process_cpu_affinity"):
            candidates.append(len(os.process_cpu_affinity(0)))
    except Exception:
        pass
    for env_name in ("TASKSET_AFFINITY", "CPU_LIMIT", "OMP_NUM_THREADS"):
        raw = os.environ.get(env_name)
        if raw:
            try:
                candidates.append(int(raw))
            except ValueError:
                pass
    try:
        with open("/sys/fs/cgroup/cpu.max", encoding="utf-8") as handle:
            quota, _, period = handle.read().strip().partition(" ")
            if quota != "max" and period:
                candidates.append(max(1, int(int(quota) / int(period))))
    except Exception:
        pass
    if hasattr(os, "cpu_count"):
        candidates.append(os.cpu_count() or 1)
    return max(1, min(candidates)) if candidates else 1


def cpu_limits() -> dict[str, Any]:
    """Report the effective CPU budget (never below one usable core)."""
    effective = _effective_cpus()
    return {"effective_cpus": effective, "logical_cpus": os.cpu_count() or 1}
