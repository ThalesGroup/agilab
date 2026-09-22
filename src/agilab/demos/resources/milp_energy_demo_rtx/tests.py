"""Focused, fast checks for the MILP energy core.

These tests exercise ``energy_core`` (the validated PyPSA/HiGHS core) only.
They reconstruct the objective and the physical constraints independently of
the model and compare them against the returned solution, so they verify real
solver output rather than echoing the model back.

Run with:  python tests.py
"""
from __future__ import annotations

import sys

from energy_core import default_settings, solve_scenario

_TOL = 1e-6


def _reconstruct_objective(result: dict) -> float:
    """Independently rebuild the objective from the returned solution."""
    s = result["settings"]
    total = s["investment_cost"] * s["module_mw"] * result["modules"]
    for hour in range(s["hours"]):
        total += (
            result["dispatch"][hour] * s["marginal_cost"]
            + result["active_modules"][hour] * s["standby_cost"]
            + result["startup"][hour] * s["startup_cost"]
            + result["shed"][hour] * s["shed_cost"]
        )
    return total


def _check_physics(result: dict) -> None:
    """Independently verify the physical constraints of a solved scenario."""
    s = result["settings"]
    demand = result["demand"]
    dispatch = result["dispatch"]
    solar = result["solar"]
    shed = result["shed"]
    active = result["active_modules"]
    module = s["module_mw"]
    capacity = result["capacity_mw"]

    assert len(demand) == s["hours"]
    assert len(dispatch) == s["hours"]
    assert len(active) == s["hours"]

    # Installed capacity is an integer number of modules.
    assert abs(capacity - module * result["modules"]) < _TOL
    assert capacity >= 0.0

    for hour in range(s["hours"]):
        # Dispatch is bounded by the active modules and respects min loading.
        assert -_TOL <= dispatch[hour] <= active[hour] * module + _TOL
        if active[hour] > 0:
            assert dispatch[hour] >= s["min_loading"] * active[hour] * module - _TOL
        else:
            assert dispatch[hour] <= _TOL
        # Active modules never exceed the installed fleet.
        assert 0 <= active[hour] <= result["modules"]
        # Energy balance: the shed unit is a sink generator, so gas + solar
        # + shed exactly meets the demand of the hour.
        assert abs(dispatch[hour] + solar[hour] + shed[hour] - demand[hour]) < 1e-3
        # Shedding is non-negative and, when not allowed, exactly zero.
        assert shed[hour] >= -_TOL
        if not s["allow_shedding"]:
            assert abs(shed[hour]) < _TOL
    # Transitions are consistent with the commitment path (initially off).
    previous = 0
    for hour in range(s["hours"]):
        assert result["startup"][hour] == max(0, active[hour] - previous)
        assert result["shutdown"][hour] == max(0, previous - active[hour])
        previous = active[hour]


def test_default_optimum() -> None:
    settings = default_settings()
    result = solve_scenario(settings)

    assert result["status"] == "optimal"
    assert str(result["solver"]["name"]).lower() == "highs"
    assert result["solver"]["threads"] == 1

    demand = [4000.0, 6000.0, 5000.0, 800.0]
    active = [20, 30, 25, 4]
    # Hand-computable optimum for the reference instance.
    expected_cost = sum(demand) + 200.0 * max(active) + sum(active)

    assert abs(result["objective"] - expected_cost) < 1e-5
    # The returned objective matches an independent reconstruction.
    assert abs(result["objective"] - _reconstruct_objective(result)) < 1e-5

    assert all(abs(a - b) < 1e-6 for a, b in zip(result["dispatch"], demand))
    assert all(abs(a - b) < 1e-6 for a, b in zip(result["demand"], demand))
    assert result["active_modules"] == active
    assert abs(result["capacity_mw"] - 6000.0) < _TOL
    assert result["modules"] == 30
    assert all(abs(v) < _TOL for v in result["solar"])
    assert all(abs(v) < _TOL for v in result["shed"])

    _check_physics(result)


def test_capacity_limited_infeasible() -> None:
    settings = default_settings()
    result = solve_scenario(settings | {"max_modules": 20})

    assert result["status"] == "infeasible"
    assert result["objective"] is None
    assert result["dispatch"] == []
    assert result["active_modules"] == []
    assert result["capacity_mw"] == 0.0
    assert result["modules"] == 0


def test_shedding_covers_shortfall() -> None:
    settings = default_settings()
    result = solve_scenario(
        settings | {"max_modules": 20, "allow_shedding": True}
    )

    assert result["status"] == "optimal"
    assert sum(result["shed"]) >= 3000.0 - 1e-5
    # The objective still matches an independent reconstruction.
    assert abs(result["objective"] - _reconstruct_objective(result)) < 1e-5
    _check_physics(result)


def _main() -> int:
    failures = []
    for name, func in sorted(
        [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    ):
        try:
            func()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")
    if failures:
        print(f"{len(failures)} test(s) failed: {', '.join(failures)}")
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
