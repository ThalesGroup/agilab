"""tests.py – concise pytest suite for energy_core and energy_runner."""
import copy
import math
import pytest
import numpy as np

import energy_core as core
import energy_runner as runner


# ─── Module-scoped solve fixtures ────────────────────────────────────────────

@pytest.fixture(scope="module")
def default_result():
    return core.solve_scenario(core.default_settings())

@pytest.fixture(scope="module")
def infeasible_result():
    s = core.default_settings()
    s["max_modules"] = 20
    return core.solve_scenario(s)

@pytest.fixture(scope="module")
def shedding_result():
    s = core.default_settings()
    s["max_modules"] = 20
    s["allow_shedding"] = True
    return core.solve_scenario(s)

@pytest.fixture(scope="module")
def solar_startup_result():
    s = core.default_settings()
    s["solar_capacity"] = 1000.0
    s["startup_cost"] = 5.0
    return core.solve_scenario(s)


# ─── Core: settings validation ───────────────────────────────────────────────

def test_defaults_bounds():
    s = core.default_settings()
    assert s["hours"] == 4 and s["max_modules"] == 50
    assert s["module_mw"] == 200.0 and s["min_loading"] == 0.1
    assert s["allow_shedding"] is False and s["mip_rel_gap"] == 0.0
    assert s["solver_time_limit"] == 10.0

def test_invalid_settings_rejection():
    base = core.default_settings()
    for key, bad in [("demand_multiplier", True), ("module_mw", float("inf")),
                     ("max_modules", 0), ("hours", 4.0), ("allow_shedding", 1)]:
        s = dict(base); s[key] = bad
        with pytest.raises(ValueError):
            core.validate_settings(s)


# ─── Core: default optimum ───────────────────────────────────────────────────

def test_default_optimum(default_result):
    r = default_result
    assert r["status"] == "optimal"
    assert r["modules"] == 30
    assert r["objective"] == pytest.approx(21879.0, abs=1e-3)
    assert r["dispatch"] == pytest.approx([4000, 6000, 5000, 800], abs=1e-3)
    assert r["active_modules"] == [20, 30, 25, 4]
    assert r["solver"]["threads"] == 1


# ─── Core: infeasible ────────────────────────────────────────────────────────

def test_infeasible_no_incumbent(infeasible_result):
    r = infeasible_result
    assert r["status"] == "infeasible"
    assert r["solver"]["incumbent"] is False
    assert r["dispatch"] == [] and r["active_modules"] == []
    assert r["objective"] is None


# ─── Core: shedding ──────────────────────────────────────────────────────────

def test_shedding_shortage_and_balance(shedding_result):
    r = shedding_result
    assert r["status"] in ("optimal", "feasible")
    assert r["solver"]["incumbent"] is True
    shed = np.array(r["shed"])
    demand = np.array(r["demand"])
    gas = np.array(r["dispatch"])
    assert float(np.sum(shed)) >= 3000.0 - 1e-3
    # Independent balance check
    assert np.max(np.abs(gas + np.array(r["solar"]) + shed - demand)) < 1e-4
    # Reconstruct costs independently
    s = r["settings"]
    active = np.array(r["active_modules"])
    startup = np.array(r["startup"])
    inv = s["investment_cost"] * r["modules"] * s["module_mw"]
    fuel = float(np.sum(gas * s["marginal_cost"]))
    standby = float(np.sum(active * s["standby_cost"]))
    st = float(np.sum(startup * s["startup_cost"]))
    shed_cost = float(np.sum(shed * 100000.0))
    total = inv + fuel + standby + st + shed_cost
    assert total == pytest.approx(r["objective"], rel=1e-5)


# ─── Core: solar + startup physical validity ─────────────────────────────────

def test_solar_startup_physical(solar_startup_result):
    r = solar_startup_result
    assert r["status"] in ("optimal", "feasible")
    s = r["settings"]
    solar = np.array(r["solar"])
    avail = np.array(r["solar_available"])
    assert np.all(solar >= -1e-5)
    assert np.all(solar <= avail + 1e-5)
    active = np.array(r["active_modules"])
    assert np.all(np.abs(active - np.round(active)) < 1e-5)
    assert np.all(active >= 0) and np.all(active <= r["modules"])
    gas = np.array(r["dispatch"])
    lo = s["min_loading"] * s["module_mw"] * active
    hi = s["module_mw"] * active
    assert np.all(gas >= lo - 1e-5) and np.all(gas <= hi + 1e-5)


# ─── Core: make_batch determinism ────────────────────────────────────────────

def test_make_batch_deterministic_and_distinct():
    base = core.default_settings()
    for count in (4, 8, 12):
        b1 = core.make_batch(base, count)
        b2 = core.make_batch(base, count)
        assert len(b1) == count
        assert b1 == b2
        mults = [x["demand_multiplier"] for x in b1]
        assert len(set(mults)) == count  # all distinct
        for x in b1:
            assert x["module_mw"] == base["module_mw"]
            assert x["max_modules"] == base["max_modules"]
            assert x["hours"] == base["hours"]


# ─── Core: cpu_limits ────────────────────────────────────────────────────────

def test_cpu_limits_effective():
    info = core.cpu_limits()
    assert info["effective_cpus"] >= 1
    assert info["effective_cpus"] <= 4


# ─── Core: model_artifact_text ───────────────────────────────────────────────

def test_model_artifact_text():
    s = core.default_settings()
    text = core.model_artifact_text(s)
    assert "integer" in text.lower()
    assert "30" in text or "50" in text  # max_modules bound mentioned
    assert "200" in text  # module_mw
    assert "1.0" in text  # cost params


# ─── Runner: single scenario smoke ───────────────────────────────────────────

def test_runner_run_scenario_smoke():
    result = runner.run_scenario(core.default_settings())
    assert result["status"] in ("optimal", "feasible")
    assert result["modules"] == 30
    assert result["solver"]["threads"] == 1
    assert result["objective"] == pytest.approx(21879.0, abs=1.0)


# ─── Runner: benchmark smoke ─────────────────────────────────────────────────

def test_runner_run_benchmark_smoke():
    base = core.default_settings()
    batch = core.make_batch(base, 4)
    workers = min(2, core.cpu_limits()["effective_cpus"])
    report = runner.run_benchmark(batch, workers)

    seq = report["sequential"]
    par = report["parallel"]
    comp = report["comparison"]

    # Same batch in both branches
    assert seq["batch"] == par["batch"] == batch
    # Comparison matches
    assert comp["matches"] is True
    # Finite positive timings
    assert seq["wall_seconds"] > 0 and math.isfinite(seq["wall_seconds"])
    assert par["wall_seconds"] > 0 and math.isfinite(par["wall_seconds"])
    assert seq["engine_seconds"] > 0 and math.isfinite(seq["engine_seconds"])
    assert par["engine_seconds"] > 0 and math.isfinite(par["engine_seconds"])
    # Observed identities match reported actual workers
    assert seq["actual_workers"] == 1
    assert par["actual_workers"] == workers
    # Truthful ratios
    assert comp["speedup"] == pytest.approx(seq["wall_seconds"] / par["wall_seconds"], rel=1e-6)
    assert comp["engine_speedup"] == pytest.approx(seq["engine_seconds"] / par["engine_seconds"], rel=1e-6)
    # Every row: solver threads 1 and physical output present
    for branch in (seq, par):
        for rec in branch["rows"]:
            res = rec["result"]
            assert res["solver"]["threads"] == 1
            assert len(res["dispatch"]) == 4
            assert len(res["active_modules"]) == 4
            assert all(math.isfinite(v) for v in res["dispatch"])


# ─── Runner: negative validation ─────────────────────────────────────────────

def test_runner_negative_validation():
    base = core.default_settings()
    batch = core.make_batch(base, 4)
    # workers bool
    with pytest.raises((ValueError, TypeError)):
        runner.run_benchmark(batch, True)
    # workers 0
    with pytest.raises((ValueError, TypeError)):
        runner.run_benchmark(batch, 0)
    # workers out of range
    with pytest.raises((ValueError, TypeError)):
        runner.run_benchmark(batch, 999)
    # batch wrong length
    with pytest.raises((ValueError, TypeError)):
        runner.run_benchmark([base], 1)


# ─── Runner: row tampering rejection ─────────────────────────────────────────

def test_runner_row_tampering_rejected():
    result = runner.run_scenario(core.default_settings())
    tampered = copy.deepcopy(result)
    tampered["dispatch"][0] = 99999.0  # break balance
    with pytest.raises(Exception):
        runner._validate_physics(tampered, core.default_settings())


# ─── Streamlit AppTest ───────────────────────────────────────────────────────

def test_app_opens_cleanly():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app.py").run()
    assert not at.exception
    # Run analysis button exists
    buttons = [b.label for b in at.button]
    assert any("Run" in lbl for lbl in buttons)
    # No solver errors in sidebar/main
    assert not at.error