"""Reject corrupted solver evidence independently of the optimization backend."""

import copy
import importlib
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest


@pytest.fixture
def energy_contract(monkeypatch):
    root = (
        Path(__file__).resolve().parents[1]
        / "src/agilab/demos/resources/milp_energy_demo"
    )

    def load(name, file):
        spec = importlib.util.spec_from_file_location(name, root / file)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    core = load("energy_core", "energy_core.py")
    pool = importlib.import_module(
        "agilab.demos.resources.milp_energy_demo.agilab_pool"
    )
    monkeypatch.setitem(sys.modules, "agilab_pool", pool)
    runner = load("_energy_evidence_contract_runner", "energy_runner.py")
    settings = core.default_settings()
    settings["allow_shedding"] = True
    hours = settings["hours"]
    demand = core._demand_profile(hours, settings["demand_multiplier"]).tolist()
    solar = (settings["solar_capacity"] * core._solar_profile(hours)).tolist()
    result = {
        "status": "feasible",
        "solver": {"incumbent": True},
        "objective": 100000 * sum(demand),
        "modules": 0,
        "capacity_mw": 0,
        "demand": demand,
        "solar_available": solar,
        "dispatch": [0] * hours,
        "active_modules": [0] * hours,
        "solar": [0] * hours,
        "shed": list(demand),
        "startup": [0] * hours,
        "shutdown": [0] * hours,
    }
    return core, runner, settings, result


def test_feasible_shed_only_evidence_passes_both_independent_checks(energy_contract):
    core, runner, settings, result = energy_contract
    runner._validate_physics(result, settings)
    outcome = core._physical_validation(
        settings,
        0,
        np.zeros(4),
        np.zeros(4),
        np.zeros(4),
        np.array(result["shed"]),
        np.array(result["demand"]),
        core._solar_profile(4),
        result["objective"],
    )
    assert outcome[0] is True and not outcome[1]
    assert outcome[2] is not None and outcome[3] is not None


@pytest.mark.parametrize(
    "field",
    [
        "dispatch",
        "active_modules",
        "solar",
        "shed",
        "startup",
        "shutdown",
        "demand",
        "solar_available",
    ],
)
@pytest.mark.parametrize("corruption", ["short", "nonfinite", "nonnumeric"])
def test_solver_arrays_must_have_the_horizon_and_finite_numbers(
    energy_contract, field, corruption
):
    _, runner, settings, result = energy_contract
    if corruption == "short":
        result[field].pop()
    else:
        result[field][0] = float("nan") if corruption == "nonfinite" else "untrusted"
    with pytest.raises(ValueError, match=field):
        runner._validate_physics(result, settings)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("objective", float("inf"), "objective"),
        ("objective", -1, "objective mismatch"),
        ("modules", True, "modules must be int"),
        ("modules", -1, "modules=.*out of"),
        ("modules", 51, "modules=.*out of"),
        ("capacity_mw", float("nan"), "capacity"),
        ("capacity_mw", 1, "capacity"),
        ("solver", {"incumbent": False}, "incumbent"),
        ("status", "error", "unexpected status"),
    ],
)
def test_solver_scalar_claims_cannot_bypass_physical_proof(
    energy_contract, field, value, reason
):
    _, runner, settings, result = energy_contract
    result[field] = value
    with pytest.raises(ValueError, match=reason):
        runner._validate_physics(result, settings)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("active_modules", 0.5, "not integer"),
        ("active_modules", -1, "active out"),
        ("active_modules", 1, "active out"),
        ("dispatch", 1, "dispatch outside"),
        ("solar", -1, "solar negative"),
        ("solar", 1, "solar exceeds"),
        ("shed", -1, "shed negative"),
        ("shed", 100000, "shed exceeds"),
        ("shed", 0, "balance residual"),
        ("startup", 1, "startup mismatch"),
        ("shutdown", 1, "shutdown mismatch"),
        ("demand", 0, "demand.*expected"),
        ("solar_available", 1, "solar_available.*expected"),
    ],
)
def test_each_physical_invariant_rejects_a_corrupt_result(
    energy_contract, field, value, reason
):
    _, runner, settings, result = energy_contract
    result[field][0] = value
    with pytest.raises(ValueError, match=reason):
        runner._validate_physics(result, settings)


def test_shedding_requires_explicit_permission(energy_contract):
    _, runner, settings, result = energy_contract
    settings["allow_shedding"] = False
    with pytest.raises(ValueError, match="shedding present"):
        runner._validate_physics(result, settings)


@pytest.mark.parametrize(
    "field",
    [
        "dispatch",
        "active_modules",
        "solar",
        "shed",
        "startup",
        "shutdown",
        "modules",
        "capacity_mw",
        "objective",
        "solver",
        "demand",
        "solar_available",
    ],
)
def test_infeasible_evidence_cannot_claim_an_incumbent_or_dispatch(
    energy_contract, field
):
    _, runner, settings, feasible = energy_contract
    result = copy.deepcopy(feasible)
    result.update(
        status="infeasible",
        solver={"incumbent": False},
        objective=None,
        modules=None,
        capacity_mw=None,
    )
    for name in ("dispatch", "active_modules", "solar", "shed", "startup", "shutdown"):
        result[name] = []
    runner._validate_physics(result, settings)
    if field in ("demand", "solar_available"):
        result[field][0] += 1
    elif field == "solver":
        result[field] = {"incumbent": True}
    elif field in ("modules", "capacity_mw", "objective"):
        result[field] = 0
    else:
        result[field] = [0]
    with pytest.raises(ValueError):
        runner._validate_physics(result, settings)


def _core_evidence(core, settings, result):
    return {
        "s": settings,
        "modules": result["modules"],
        "active": np.array(result["active_modules"], dtype=float),
        "gas": np.array(result["dispatch"], dtype=float),
        "solar": np.array(result["solar"], dtype=float),
        "shed": np.array(result["shed"], dtype=float),
        "demand": np.array(result["demand"], dtype=float),
        "solar_pu": core._solar_profile(settings["hours"]),
        "objective": result["objective"],
    }


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("modules", float("nan"), "non-finite"),
        ("active", [float("inf")] * 4, "non-finite"),
        ("gas", [float("nan")] * 4, "non-finite"),
        ("solar", [float("nan")] * 4, "non-finite"),
        ("shed", [float("nan")] * 4, "non-finite"),
        ("demand", [float("nan")] * 4, "non-finite"),
        ("active", [0] * 3, "horizon"),
        ("gas", [0] * 3, "horizon"),
        ("solar", [0] * 3, "horizon"),
        ("shed", [0] * 3, "horizon"),
        ("modules", 0.5, "not integer"),
        ("active", [0.5] * 4, "not integer"),
        ("modules", -1, "out of"),
        ("modules", 51, "out of"),
        ("active", [-1] * 4, "out of"),
        ("active", [1] * 4, "out of"),
        ("gas", [-1] * 4, "dispatch outside"),
        ("gas", [1] * 4, "dispatch outside"),
        ("solar", [-1] * 4, "solar negative"),
        ("solar", [1] * 4, "solar exceeds"),
        ("shed", [-1] * 4, "shed negative"),
        ("shed", [1e9] * 4, "shed exceeds"),
        ("shed", [0] * 4, "balance residual"),
        ("objective", float("inf"), "objective not finite"),
        ("objective", 0, "objective mismatch"),
    ],
)
def test_core_rejects_corrupted_physical_evidence(
    energy_contract, field, value, reason
):
    core, _, settings, result = energy_contract
    evidence = _core_evidence(core, settings, result)
    evidence[field] = np.array(value, dtype=float) if isinstance(value, list) else value
    ok, error, costs, residuals = core._physical_validation(**evidence)
    assert ok is False
    assert reason in error
    assert costs is None and residuals is None


def test_core_requires_explicit_shedding_permission(energy_contract):
    core, _, settings, result = energy_contract
    settings["allow_shedding"] = False
    ok, error, costs, residuals = core._physical_validation(
        **_core_evidence(core, settings, result)
    )
    assert ok is False and "not allowed" in error
    assert costs is None and residuals is None


def test_core_reconstructs_costs_and_module_transitions(energy_contract):
    core, _, settings, _ = energy_contract
    settings.update(investment_cost=2, marginal_cost=3, standby_cost=5, startup_cost=7)
    active = np.array([1.0, 2.0, 1.0, 0.0])
    gas = np.array([100.0, 200.0, 100.0, 0.0])
    # Independently calculated: 400 MW * 2 + 400 MWh * 3 + 4 * 5 + 2 starts * 7.
    expected = 2034
    ok, error, costs, residuals = core._physical_validation(
        settings,
        2,
        active,
        gas,
        np.zeros(4),
        np.zeros(4),
        gas.copy(),
        np.zeros(4),
        expected,
    )
    assert ok is True and error is None
    assert costs == {
        "investment": 800,
        "fuel": 1200,
        "standby": 20,
        "startup": 14,
        "shedding": 0,
        "total": expected,
    }
    assert all(value == 0 for value in residuals.values())
    startup, shutdown = core._derive_transitions(active)
    np.testing.assert_array_equal(startup, [1, 1, 0, 0])
    np.testing.assert_array_equal(shutdown, [0, 0, 1, 1])


@pytest.fixture
def energy_branch(energy_contract):
    _, runner, settings, result = energy_contract
    result["settings"] = copy.deepcopy(settings)
    result["solver"].update(name="highs", threads=1)
    row = dict(case=0, pid=100, start_monotonic=10.0, end_monotonic=11.0, result=result)
    branch = dict(
        rows=[row],
        engine_start=10.0,
        engine_end=12.0,
        engine_seconds=1.0,
        wall_seconds=3.0,
        workers=1,
        pool_width=1,
    )
    return runner, settings, branch


def test_valid_solver_branch_records_observed_worker_count(energy_branch):
    runner, settings, branch = energy_branch
    runner._validate_branch(branch, [settings], 1)
    assert branch["actual_workers"] == 1


@pytest.mark.parametrize(
    "path,value,reason",
    [
        (("rows",), {}, "rows must be a list"),
        (("rows",), [], "expected 1 rows"),
        (("rows", 0), [], "row record must be dict"),
        (("rows", 0, "case"), True, "case must be strict int"),
        (("rows", 0, "case"), 1, "case mismatch"),
        (("rows", 0, "pid"), True, "pid must be positive int"),
        (("rows", 0, "pid"), -1, "pid must be positive int"),
        (("rows", 0, "start_monotonic"), float("nan"), "start_monotonic"),
        (("rows", 0, "end_monotonic"), float("inf"), "end_monotonic"),
        (("rows", 0, "end_monotonic"), 10, "interval non-positive"),
        (("rows", 0, "result"), None, "result must be dict"),
        (("rows", 0, "result", "settings"), {}, "settings mismatch"),
        (("rows", 0, "result", "solver"), None, "solver metadata missing"),
        (("rows", 0, "result", "solver", "name"), "other", "solver name"),
        (
            ("rows", 0, "result", "solver", "threads"),
            True,
            "threads must be strict int",
        ),
        (("rows", 0, "result", "solver", "threads"), 2, "threads must be strict int"),
        (("engine_start",), True, "engine_start not finite"),
        (("engine_start",), float("nan"), "engine_start not finite"),
        (("engine_end",), True, "engine_end not finite"),
        (("engine_end",), float("inf"), "engine_end not finite"),
        (("engine_seconds",), True, "positive finite"),
        (("engine_seconds",), 0, "positive finite"),
        (("engine_seconds",), 4, "> engine span"),
        (("wall_seconds",), True, "strictly positive finite"),
        (("wall_seconds",), 0, "strictly positive finite"),
        (("wall_seconds",), 1, "> wall_seconds"),
        (("rows", 0, "start_monotonic"), 9, "outside engine interval"),
        (("rows", 0, "end_monotonic"), 13, "outside engine interval"),
        (("workers",), 2, "expected 1"),
        (("pool_width",), True, "pool_width must be positive int"),
        (("pool_width",), 0, "pool_width must be positive int"),
        (("pool_width",), 2, "> workers"),
    ],
)
def test_invalid_solver_branch_evidence_is_rejected(energy_branch, path, value, reason):
    runner, settings, branch = energy_branch
    target = branch
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=reason):
        runner._validate_branch(branch, [settings], 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("settings", {}),
        ("status", "infeasible"),
        ("objective", None),
        ("objective", "invalid"),
        ("objective", float("inf")),
        ("objective", -1),
    ],
)
def test_sequential_and_parallel_results_must_agree(energy_branch, field, value):
    runner, settings, branch = energy_branch
    parallel = copy.deepcopy(branch["rows"])
    parallel[0]["result"][field] = value
    assert runner._compare_results(branch["rows"], parallel, [settings]) is False


def test_result_comparison_handles_infeasibility_and_unknown_status(energy_branch):
    runner, settings, branch = energy_branch
    rows = branch["rows"]
    assert runner._compare_results(rows, copy.deepcopy(rows), [settings]) is True
    assert runner._compare_results(rows, [], [settings]) is False
    rows[0]["result"].update(status="infeasible", objective=None)
    assert runner._compare_results(rows, copy.deepcopy(rows), [settings]) is True
    rows[0]["result"]["objective"] = 0
    assert runner._compare_results(rows, copy.deepcopy(rows), [settings]) is False
    rows[0]["result"]["status"] = "error"
    assert runner._compare_results(rows, copy.deepcopy(rows), [settings]) is False


@pytest.mark.parametrize(
    "other_pid,start,end,expected",
    [
        (101, 10.5, 11.5, True),
        (100, 10.5, 11.5, False),
        (101, 11, 12, False),
        (101, 12, 13, False),
    ],
)
def test_overlap_requires_different_processes_and_intersecting_intervals(
    energy_branch, other_pid, start, end, expected
):
    runner, _, branch = energy_branch
    row = copy.deepcopy(branch["rows"][0])
    row.update(pid=other_pid, start_monotonic=start, end_monotonic=end)
    assert runner._check_overlap([branch["rows"][0], row]) is expected
