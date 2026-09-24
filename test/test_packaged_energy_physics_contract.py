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

@pytest.mark.parametrize("returncode,timeout", [(0, False), (2, False), (None, True)])
def test_child_launch_is_isolated_bounded_and_always_cleaned(energy_contract, monkeypatch, returncode, timeout):
    import subprocess
    from types import SimpleNamespace
    _, runner, _, _ = energy_contract
    calls, cleaned = [], []
    class Child:
        def __init__(self):
            self.returncode = returncode
        def communicate(self, timeout):
            calls.append(("communicate", timeout))
            if self.returncode is None:
                raise subprocess.TimeoutExpired("solver", timeout)
            return b'{"rows": []}', b"diagnostic"
    child = Child()
    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return child
    proxy = SimpleNamespace(Popen=launch, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired)
    monkeypatch.setitem(sys.modules, "subprocess", proxy)
    monkeypatch.setattr(runner, "_cleanup_process_group", cleaned.append)
    text, elapsed, success = runner._launch_child_safe(["--single", "{}"], 2.5, "/isolated", {"PRIVATE": "1"})
    assert success is (returncode == 0)
    assert text == ("" if timeout else '{"rows": []}')
    assert elapsed >= 0
    command, options = calls[0]
    assert command[-2:] == ["--single", "{}"]
    assert options["start_new_session"] is True
    assert options["cwd"] == "/isolated" and options["env"] == {"PRIVATE": "1"}
    assert calls[1] == ("communicate", 2.5)
    assert cleaned == [child]


@pytest.mark.parametrize("failure", ["spawn", "communicate"])
def test_child_launch_errors_still_reach_cleanup(energy_contract, monkeypatch, failure):
    import subprocess
    from types import SimpleNamespace
    _, runner, _, _ = energy_contract
    cleaned = []
    child = SimpleNamespace()
    def broken_communication(**kwargs):
        raise OSError("read failed")
    child.communicate = broken_communication
    def launch(*args, **kwargs):
        if failure == "spawn":
            raise OSError("spawn failed")
        return child
    monkeypatch.setitem(sys.modules, "subprocess", SimpleNamespace(
        Popen=launch, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(runner, "_cleanup_process_group", cleaned.append)
    with pytest.raises(OSError):
        runner._launch_child_safe([], 1, "/isolated", {})
    assert cleaned == [None if failure == "spawn" else child]


@pytest.mark.parametrize("group_exists,reap_failures", [(False, 0), (True, 0), (True, 1), (False, 2)])
def test_owned_process_cleanup_is_bounded_and_reports_unreapable_child(
    energy_contract, monkeypatch, group_exists, reap_failures,
):
    from types import SimpleNamespace
    _, runner, _, _ = energy_contract
    signals, waits = [], []
    def killpg(pid, sig):
        assert pid == 98765
        signals.append(sig)
        if not group_exists:
            raise ProcessLookupError()
    def wait(*, timeout):
        waits.append(timeout)
        if len(waits) <= reap_failures:
            raise TimeoutError()
    clock = iter([0, 1])
    monkeypatch.setattr(runner, "os", SimpleNamespace(killpg=killpg))
    monkeypatch.setattr(runner, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    child = SimpleNamespace(pid=98765, wait=wait)
    if reap_failures == 2:
        with pytest.raises(RuntimeError, match="Failed to reap"):
            runner._cleanup_process_group(child)
    else:
        runner._cleanup_process_group(child)
    assert len(waits) == min(reap_failures + 1, 2)
    assert all(timeout == runner._REAP_TIMEOUT for timeout in waits)
    if group_exists:
        assert runner.signal.SIGTERM in signals and runner.signal.SIGKILL in signals


def test_solver_child_environment_discards_inherited_pool_overrides(energy_contract, monkeypatch):
    from types import SimpleNamespace
    _, runner, _, _ = energy_contract
    inherited = {"AGILAB_POOL_EXECUTOR": "thread", "AGILAB_POOL_ITEM_TIMEOUT": "0",
                 "OMP_NUM_THREADS": "500", "PATH": "preserved"}
    monkeypatch.setattr(runner, "os", SimpleNamespace(environ=inherited))
    env = runner._build_child_env()
    assert env["AGILAB_POOL_EXECUTOR"] == "process"
    assert "AGILAB_POOL_ITEM_TIMEOUT" not in env
    assert env["PATH"] == "preserved"
    assert all(env[key] == "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"))
    assert inherited["OMP_NUM_THREADS"] == "500"


@pytest.mark.parametrize("response,success,error", [
    ("{}", False, "single child failed"),
    ("{}", True, "expected 1 row"),
    ('{"rows": [{}, {}]}', True, "expected 1 row"),
])
def test_failed_solver_protocol_releases_the_single_run_lock(energy_contract, monkeypatch, response, success, error):
    _, runner, settings, _ = energy_contract
    monkeypatch.setattr(runner, "_launch_child_safe", lambda *args: (response, 0.1, success))
    with pytest.raises(RuntimeError, match=error):
        runner.run_scenario(settings)
    assert runner._lock.acquire(blocking=False)
    runner._lock.release()

@pytest.mark.parametrize("entrypoint", ["_child_main", "_cli_main"])
@pytest.mark.parametrize("case", ["missing", "single-json", "single-settings", "batch-json", "batch-length", "batch-item", "workers"])
def test_energy_child_cli_rejects_invalid_requests_before_pool_launch(
    energy_contract, monkeypatch, capsys, entrypoint, case,
):
    import json
    _, runner, settings, _ = energy_contract
    requests = {
        "missing": [], "single-json": ["--single", "{"],
        "single-settings": ["--single", '{"hours": 0}'],
        "batch-json": ["--batch", "{"], "batch-length": ["--batch", "[]"],
        "batch-item": ["--batch", json.dumps([settings, settings, {"hours": 0}, settings])],
        "workers": ["--batch", json.dumps([settings] * 4), "--workers", "9"],
    }
    monkeypatch.setattr(sys, "argv", ["energy_runner.py", *requests[case]])
    monkeypatch.setattr(runner, "cpu_limits", lambda: {"effective_cpus": 4})
    def forbidden(*args):
        pytest.fail("invalid input must not reach the worker pool")
    monkeypatch.setattr(runner, "_child_run_batch", forbidden)
    with pytest.raises(SystemExit) as error:
        getattr(runner, entrypoint)()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]


@pytest.mark.parametrize("entrypoint", ["_child_main", "_cli_main"])
@pytest.mark.parametrize("batch_mode", [False, True])
def test_energy_child_cli_forwards_validated_scenarios_and_worker_count(
    energy_contract, monkeypatch, capsys, entrypoint, batch_mode,
):
    import json
    _, runner, settings, _ = energy_contract
    requests = ["--batch", json.dumps([settings] * 4), "--workers", "2"] if batch_mode else ["--single", json.dumps(settings)]
    monkeypatch.setattr(sys, "argv", ["energy_runner.py", *requests])
    monkeypatch.setattr(runner, "cpu_limits", lambda: {"effective_cpus": 4})
    calls = []
    def run(items, workers):
        calls.append((items, workers))
        return {"rows": [], "workers": workers}
    monkeypatch.setattr(runner, "_child_run_batch", run)
    getattr(runner, entrypoint)()
    expected_count = 4 if batch_mode else 1
    assert calls == [([{"case": i, "settings": settings} for i in range(expected_count)], 2 if batch_mode else 1)]
    output = capsys.readouterr()
    assert json.loads(output.out) == {"rows": [], "workers": 2 if batch_mode else 1}
    assert output.err == ""


def test_energy_child_cli_rejects_conflicting_modes(energy_contract, monkeypatch, capsys):
    import json
    _, runner, settings, _ = energy_contract
    monkeypatch.setattr(sys, "argv", ["energy_runner.py", "--single", json.dumps(settings), "--batch", json.dumps([settings] * 4)])
    with pytest.raises(SystemExit) as error:
        runner._cli_main()
    assert error.value.code == 1
    assert "mutually exclusive" in json.loads(capsys.readouterr().err)["error"]


def test_energy_core_cli_serializes_finite_evidence_and_numpy_scalars(
    energy_contract, monkeypatch, capsys,
):
    import json
    core, _, settings, _ = energy_contract
    monkeypatch.setattr(sys, "argv", ["energy_core.py", "--settings", json.dumps(settings)])
    result = {"nested": [float("nan"), float("inf"), 1.25, np.int64(7),
                         np.float32(2.5), np.float32("nan"), ("label", True)]}
    monkeypatch.setattr(core, "solve_scenario", lambda supplied: result)
    core._main()
    assert json.loads(capsys.readouterr().out) == {"nested": [None, None, 1.25, 7, 2.5, None, ["label", True]]}


@pytest.mark.parametrize("bad_json", [False, True])
def test_energy_core_cli_emits_structured_errors(energy_contract, monkeypatch, capsys, bad_json):
    import json
    core, _, settings, _ = energy_contract
    monkeypatch.setattr(sys, "argv", ["energy_core.py", "--settings", "{" if bad_json else json.dumps(settings)])
    def fail(settings):
        raise RuntimeError("solver unavailable")
    monkeypatch.setattr(core, "solve_scenario", fail)
    if bad_json:
        with pytest.raises(SystemExit) as error:
            core._main()
        assert error.value.code == 1
        assert "invalid JSON" in json.loads(capsys.readouterr().err)["error"]
    else:
        core._main()
        assert json.loads(capsys.readouterr().out) == {"error": "RuntimeError: solver unavailable"}


@pytest.mark.parametrize("files,expected", [
    ({"/sys/fs/cgroup/cpu.max": "150000 100000"}, 1),
    ({"/sys/fs/cgroup/cpu.max": "max 100000",
      "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "250000",
      "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000"}, 2),
    ({"/sys/fs/cgroup/cpu.max": "bad", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "-1",
      "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000"}, 4),
    ({"/sys/fs/cgroup/cpu.max": "", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "100",
      "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "0"}, 4),
])
def test_energy_cpu_limits_respect_cgroup_caps_and_ignore_unlimited_or_malformed_records(energy_contract, monkeypatch, files, expected):
    import io
    import os
    core, _, _, _ = energy_contract
    monkeypatch.delenv("CPU_CORES", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: set(range(6)), raising=False)
    def read_fixture(path, *args, **kwargs):
        if str(path) not in files:
            raise FileNotFoundError(path)
        return io.StringIO(files[str(path)])
    monkeypatch.setattr(core, "open", read_fixture, raising=False)
    result = core.cpu_limits()
    assert result["effective_cpus"] == expected
    assert 8.0 in result["observed_caps"]
    assert 6.0 in result["observed_caps"]


@pytest.mark.parametrize("allowance", ["0", "-1", "invalid"])
def test_energy_cpu_limits_reject_invalid_operator_allowance(energy_contract, monkeypatch, allowance):
    import os
    from unittest.mock import Mock
    core, _, _, _ = energy_contract
    monkeypatch.setenv("CPU_CORES", allowance)
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    monkeypatch.setattr(os, "sched_getaffinity", Mock(side_effect=OSError("unavailable")), raising=False)
    monkeypatch.setattr(core, "open", Mock(side_effect=FileNotFoundError()), raising=False)
    with pytest.raises(ValueError, match="CPU_CORES invalid"):
        core.cpu_limits()


@pytest.mark.parametrize("host_failure", [False, True])
def test_energy_cpu_limits_default_to_one_when_platform_cannot_report_capacity(energy_contract, monkeypatch, host_failure):
    import os
    from unittest.mock import Mock
    core, _, _, _ = energy_contract
    monkeypatch.delenv("CPU_CORES", raising=False)
    monkeypatch.setattr(os, "cpu_count", Mock(return_value=None, side_effect=OSError("unavailable") if host_failure else None))
    monkeypatch.setattr(os, "sched_getaffinity", Mock(side_effect=OSError("unavailable")), raising=False)
    monkeypatch.setattr(core, "open", Mock(side_effect=FileNotFoundError()), raising=False)
    assert core.cpu_limits() == {"effective_cpus": 1, "observed_caps": []}


@pytest.mark.parametrize("failure", ["before-sequential", "before-parallel", "sequential-child", "parallel-child"])
def test_energy_benchmark_stops_at_failed_phase_and_releases_lock(energy_contract, monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import Mock
    _, runner, settings, _ = energy_contract
    batch = [dict(settings) for _ in range(min(runner._VALID_BATCH_LENGTHS))]
    monkeypatch.setattr(runner, "cpu_limits", lambda: {"effective_cpus": 2})
    ticks = [0, runner._TOTAL_BUDGET + 1] if failure == "before-sequential" else [0, 0, runner._TOTAL_BUDGET + 1] if failure == "before-parallel" else [0, 0, 0]
    monkeypatch.setattr(runner, "time", SimpleNamespace(perf_counter=Mock(side_effect=ticks)))
    replies = [("{}", .1, failure != "sequential-child"), ("{}", .1, failure != "parallel-child")]
    launch = Mock(side_effect=replies)
    monkeypatch.setattr(runner, "_launch_child_safe", launch)
    message = "budget exhausted" if failure.startswith("before") else failure.replace("-", " ") + " failed"
    with pytest.raises(RuntimeError, match=message):
        runner.run_benchmark(batch, workers=2)
    assert launch.call_count == {"before-sequential": 0, "before-parallel": 1, "sequential-child": 1, "parallel-child": 2}[failure]
    assert runner._lock.acquire(blocking=False)
    runner._lock.release()


@pytest.mark.parametrize("entrypoint", ["run_scenario", "run_benchmark"])
def test_energy_concurrent_run_is_rejected_without_launch(energy_contract, monkeypatch, entrypoint):
    from unittest.mock import Mock
    _, runner, settings, _ = energy_contract
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(runner, "_launch_child_safe", launch)
    assert runner._lock.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match="in progress"):
            runner.run_scenario(settings) if entrypoint == "run_scenario" else runner.run_benchmark([], 1)
    finally:
        runner._lock.release()
    launch.assert_not_called()


@pytest.mark.parametrize("solar,shedding", [(0, False), (10, False), (0, True), (10, True)])
def test_energy_formulation_lists_only_enabled_optional_sources(energy_contract, solar, shedding):
    core, _, settings, _ = energy_contract
    settings.update(solar_capacity=solar, allow_shedding=shedding)
    text = core.model_artifact_text(settings)
    assert ("p (solar):" in text) is bool(solar)
    assert ("p (shedding):" in text) is shedding
    assert "Power balance:" in text


@pytest.mark.parametrize("failure", ["optimize", "no-incumbent", "infeasible", "extract", "physics"])
def test_solver_boundary_failures_never_publish_feasible_dispatch(energy_contract, monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import Mock
    core, _, settings, _ = energy_contract
    highs = SimpleNamespace(SolutionStatus=SimpleNamespace(kSolutionStatusFeasible=1),
        HighsModelStatus=SimpleNamespace(kOptimal=10, kInfeasible=20))
    monkeypatch.setitem(sys.modules, "highspy", highs)
    incumbent = failure in {"extract", "physics"}
    info = SimpleNamespace(valid=incumbent, primal_solution_status=1,
        objective_function_value=float("nan"), mip_gap=float("nan"), mip_dual_bound=float("nan"))
    solver = SimpleNamespace(getInfo=lambda: info, getSolution=lambda: SimpleNamespace(value_valid=incumbent),
        getModelStatus=lambda: 20 if failure == "infeasible" else 10,
        modelStatusToString=lambda value: "synthetic status")
    optimize = Mock(side_effect=RuntimeError("backend unavailable") if failure == "optimize" else None)
    network = SimpleNamespace(optimize=optimize, model=SimpleNamespace(solver_model=solver))
    demand = core._demand_profile(settings["hours"], settings["demand_multiplier"])
    solar = core._solar_profile(settings["hours"])
    monkeypatch.setattr(core, "_build_network", lambda supplied: (network, demand, solar))
    extract = Mock(side_effect=KeyError("missing solver variables") if failure == "extract" else None,
        return_value=(0, np.zeros(len(demand)), np.zeros(len(demand)), np.zeros(len(demand)), np.zeros(len(demand))))
    monkeypatch.setattr(core, "_extract_solutions", extract)
    result = core.solve_scenario(settings)
    assert result["status"] == ("infeasible" if failure == "infeasible" else "error")
    assert result["objective"] is None
    assert result["dispatch"] == []
    assert result["modules"] is None
    assert result["solver"]["threads"] == 1
    assert result["solver"]["gap"] is None
    assert result["solver"]["bound"] is None
    if failure not in {"extract", "physics"}:
        extract.assert_not_called()
    if failure == "optimize":
        assert "backend unavailable" in result["error"]
    if failure == "extract":
        assert "solution extraction failed" in result["error"]


@pytest.mark.parametrize("field", ["demand", "solar_available"])
@pytest.mark.parametrize("corruption", ["short", "nan", "text"])
def test_infeasible_evidence_still_requires_complete_finite_input_profiles(energy_contract, field, corruption):
    _, runner, settings, feasible = energy_contract
    result = copy.deepcopy(feasible)
    result.update(status="infeasible", solver={"incumbent": False},
                  objective=None, modules=None, capacity_mw=None)
    for name in ("dispatch", "active_modules", "solar", "shed", "startup", "shutdown"):
        result[name] = []
    if corruption == "short":
        result[field] = result[field][:-1]
    else:
        result[field][0] = float("nan") if corruption == "nan" else "unknown"
    with pytest.raises(ValueError, match=field):
        runner._validate_physics(result, settings)
