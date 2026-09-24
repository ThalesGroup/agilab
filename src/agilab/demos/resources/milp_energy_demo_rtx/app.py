"""Streamlit UI: modular expansion with unit commitment (MILP) analysis.

Adapted from the PyPSA example notebook "Modular Expansion with Unit
Commitment" (PyPSA contributors, CC-BY-4.0). Built on the validated public
modules ``energy_core`` (scenario model + solver) and ``energy_runner`` (real
serial/parallel benchmark), so the app is self-contained within the exported
bundle.
"""

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import energy_core as core

st.set_page_config(
    page_title="Modular Unit Commitment (MILP)",
    page_icon=":electric_plug:",
    layout="wide",
)

st.title("Modular Expansion with Unit Commitment (MILP)")
st.markdown(
    "Extendable, committable power assets that can only be built in "
    "fixed-size modules, optimised as a mixed-integer linear programme "
    "with PyPSA and the HiGHS solver. Adapted from the PyPSA example "
    "notebook *Modular Expansion with Unit Commitment* "
    "(PyPSA contributors, "
    "[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/))."
)

CASE_LABELS = {
    "reference": "Reference optimum (single bus, no solar)",
    "solar": "Modular generator with solar resource",
    "commitment": "Commitment dynamics (start-up costs)",
    "shortage": "Capacity-limited shortage (load shedding)",
}

# Scenario presets: the keys are the exact ``energy_core.default_settings()``
# keys, so every control maps one-to-one onto a real solver parameter.
CASE_DEFAULTS = {
    "reference": {},
    "solar": {"solar_capacity": 1500.0, "startup_cost": 500.0},
    "commitment": {"hours": 12, "startup_cost": 500.0},
    "shortage": {"max_modules": 20, "allow_shedding": True},
}


def _to_jsonable(value):
    """Recursively convert numpy/pandas scalars and containers to plain JSON."""
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, bool, int, float, type(None))):
        return value
    if hasattr(value, "item"):
        try:
            return _to_jsonable(value.item())
        except Exception:
            return str(value)
    return str(value)


def render_result(result: dict, ran_at: str) -> None:
    st.subheader("Results")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Status", result.get("status", "-"))
    col2.metric("Installed capacity [MW]", f"{result.get('capacity_mw', 0.0):.0f}")
    col3.metric("Modules built", result.get("modules", 0))
    objective = result.get("objective")
    col4.metric("Objective [currency/MWh]", "n/a" if objective is None else f"{objective:.1f}")

    solver = result.get("solver", {})
    if solver:
        st.caption(f"Solver: {solver.get('name')} (threads: {solver.get('threads')})")

    if result.get("status") != "optimal":
        st.warning("The scenario is infeasible as configured: the installed capacity cannot meet the demand. Adjust the parameters and run the analysis again.")
        return

    hours = result["settings"]["hours"]
    schedule = pd.DataFrame(
        {
            "Hour": list(range(1, hours + 1)),
            "Demand [MW]": result["demand"],
            "Gas dispatch [MW]": result["dispatch"],
            "Solar [MW]": result["solar"],
            "Shed [MW]": result["shed"],
            "Active modules": result["active_modules"],
            "Start-ups": result["startup"],
            "Shut-downs": result["shutdown"],
        }
    )
    st.dataframe(schedule, width="stretch")

    extra_metrics = [("Total start-ups", int(sum(result["startup"]))), ("Total shut-downs", int(sum(result["shutdown"])))]
    if result["settings"]["allow_shedding"]:
        extra_metrics.append(("Total shed [MW]", f"{sum(result['shed']):.0f}"))
    if result["settings"]["solar_capacity"] > 0:
        extra_metrics.append(("Solar capacity [MW]", f"{result['settings']['solar_capacity']:.0f}"))
    cols = st.columns(len(extra_metrics))
    for col, (name, value) in zip(cols, extra_metrics):
        col.metric(name, value)

    st.json(
        _to_jsonable(
            {"ran_at": ran_at, **{k: v for k, v in result.items() if k not in ("schedule", "dispatch", "demand", "active_modules", "solar", "shed", "startup", "shutdown")}}
        )
    )


def render_benchmark(report: dict, ran_at: str) -> None:
    st.subheader("Scaling check (serial vs parallel)")
    one, many = report["sequential"], report["parallel"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cases", len(one["batch"]))
    col2.metric("Workers", len({row["pid"] for row in many["rows"]}))
    col3.metric("Serial wall [s]", f"{one['wall_seconds']:.3f}")
    col4.metric("Parallel wall [s]", f"{many['wall_seconds']:.3f}")
    st.caption("Timings are real measured evidence from this run; they are not a speedup guarantee.")
    st.json(_to_jsonable({"ran_at": ran_at, "comparison": report["comparison"]}))


with st.sidebar:
    st.header("Case parameters")
    label = st.selectbox("Case", list(CASE_LABELS.values()), key="case_select")
    case = next(key for key, value in CASE_LABELS.items() if value == label)
    overrides = CASE_DEFAULTS[case]
    base = core.default_settings()
    initial = dict(base)
    initial.update(overrides)

    def _setting(key, widget, widget_kwargs):
        return widget(key, value=initial[key], key=f"setting_{case}_{key}", **widget_kwargs)

    hours = _setting("hours", st.number_input, {"min_value": 4, "max_value": 12, "step": 4, "help": "Simulation horizon; must be a multiple of 4."})
    hours = max(4, int(hours))
    if hours % 4 != 0:
        hours = (hours // 4) * 4 + 4
    demand_multiplier = _setting("demand_multiplier", st.number_input, {"min_value": 0.1, "max_value": 10.0, "step": 0.1, "format": "%.2f"})
    module_mw = _setting("module_mw", st.number_input, {"min_value": 10.0, "max_value": 1000.0, "step": 10.0, "help": "Fixed size of each buildable module [MW]."})
    max_modules = _setting("max_modules", st.number_input, {"min_value": 1, "max_value": 200, "step": 1})
    min_loading = _setting("min_loading", st.slider, {"min_value": 0.0, "max_value": 0.9, "step": 0.05, "format": "%.2f", "help": "Minimum part-load fraction when a module is active."})
    investment_cost = _setting("investment_cost", st.number_input, {"min_value": 0.0, "step": 0.5, "format": "%.2f"})
    marginal_cost = _setting("marginal_cost", st.number_input, {"min_value": 0.0, "step": 0.5, "format": "%.2f"})
    standby_cost = _setting("standby_cost", st.number_input, {"min_value": 0.0, "step": 0.5, "format": "%.2f"})
    startup_cost = _setting("startup_cost", st.number_input, {"min_value": 0.0, "step": 50.0, "format": "%.2f"})
    solar_capacity = _setting("solar_capacity", st.number_input, {"min_value": 0.0, "max_value": 5000.0, "step": 100.0, "help": "Fixed solar capacity [MW]; 0 disables solar."})
    allow_shedding = _setting("allow_shedding", st.checkbox, {"help": "Allow load shedding when capacity is insufficient."})
    shed_cost = _setting("shed_cost", st.number_input, {"min_value": 0.0, "step": 10000.0, "format": "%.0f"})

    st.divider()
    st.subheader("Scaling check")
    st.caption("Serially and in parallel across real worker processes (real measured timings).")
    workers = st.selectbox("Workers", [1, 2, 4], index=1, key="workers")
    batch_count = st.number_input("Batch size", min_value=1, max_value=12, step=1, value=4, key="batch_count")


def _settings_from_sidebar() -> dict:
    return {
        "hours": int(hours),
        "demand_multiplier": float(demand_multiplier),
        "module_mw": float(module_mw),
        "max_modules": int(max_modules),
        "min_loading": float(min_loading),
        "investment_cost": float(investment_cost),
        "marginal_cost": float(marginal_cost),
        "standby_cost": float(standby_cost),
        "startup_cost": float(startup_cost),
        "solar_capacity": float(solar_capacity),
        "allow_shedding": bool(allow_shedding),
        "shed_cost": float(shed_cost),
    }


if st.button("Run analysis"):
    settings = _settings_from_sidebar()
    try:
        result = core.solve_scenario(settings)
        st.session_state["result"] = result
        st.session_state["ran_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        st.session_state.pop("run_error", None)
    except Exception as exc:  # surface solver/model failures in the UI
        st.session_state["run_error"] = f"{type(exc).__name__}: {exc}"
        st.session_state.pop("result", None)

if st.button("Run scaling check"):
    settings = _settings_from_sidebar()
    try:
        import energy_runner as runner

        report = runner.run_benchmark(core.make_batch(settings, int(batch_count)), int(workers))
        st.session_state["benchmark"] = report
        st.session_state["benchmark_ran_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        st.session_state.pop("benchmark_error", None)
    except Exception as exc:  # surface runner failures in the UI
        st.session_state["benchmark_error"] = f"{type(exc).__name__}: {exc}"
        st.session_state.pop("benchmark", None)

if st.session_state.get("run_error"):
    st.error(st.session_state["run_error"])
if st.session_state.get("result") is not None:
    render_result(st.session_state["result"], st.session_state["ran_at"])
else:
    st.info("Configure a case on the left and press 'Run analysis' to solve the MILP.")

if st.session_state.get("benchmark_error"):
    st.error(st.session_state["benchmark_error"])
if st.session_state.get("benchmark") is not None:
    render_benchmark(st.session_state["benchmark"], st.session_state["benchmark_ran_at"])
else:
    st.info("Press 'Run scaling check' to compare serial and parallel throughput with real measured timings.")
