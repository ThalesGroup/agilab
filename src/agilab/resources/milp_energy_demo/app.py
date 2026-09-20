import streamlit as st
import pandas as pd
import altair as alt
import json
import math

from energy_core import default_settings, validate_settings, make_batch, cpu_limits, model_artifact_text
from energy_runner import run_scenario, run_benchmark


def _sig(d):
    return json.dumps(d, sort_keys=True, allow_nan=False)


def _fmt(v, fmt="{:.4f}"):
    if v is None:
        return "N/A"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)) and math.isfinite(v):
        return fmt.format(v)
    return str(v)


def _dispatch_df(result):
    status = result.get("status")
    if status not in ("optimal", "feasible"):
        return None
    solver = result.get("solver", {})
    if not solver.get("incumbent"):
        return None
    if result.get("objective") is None:
        return None
    settings = result.get("settings", {})
    hours = settings.get("hours")
    if hours is None:
        return None
    required = ["demand", "dispatch", "solar", "shed", "active_modules", "startup", "shutdown"]
    for key in required:
        vec = result.get(key, [])
        if len(vec) != hours:
            return None
    df = pd.DataFrame({
        "hour": list(range(hours)),
        "demand": result["demand"],
        "gas": result["dispatch"],
        "solar": result["solar"],
        "shed": result["shed"],
        "active_modules": result["active_modules"],
        "startup": result["startup"],
        "shutdown": result["shutdown"],
    })
    sa = result.get("solar_available", [])
    if len(sa) == hours:
        df["solar_available"] = sa
    return df


def _cost_df(result):
    costs = result.get("costs", {})
    if not costs:
        return None
    return pd.DataFrame([{"component": k, "cost": v} for k, v in costs.items()])


def _show_result(result):
    status = result.get("status", "unknown")
    st.subheader(f"Status: {status}")
    solver = result.get("solver", {})
    st.write(
        f"Solver: {solver.get('name', 'N/A')} | Threads: {solver.get('threads', 'N/A')} | "
        f"Termination: {solver.get('termination', 'N/A')} | "
        f"Gap: {_fmt(solver.get('gap'))} | Bound: {_fmt(solver.get('bound'))} | "
        f"Incumbent: {solver.get('incumbent', False)}"
    )
    st.write(f"Elapsed: {_fmt(result.get('elapsed_seconds'))} s")

    if status in ("optimal", "feasible"):
        st.write(f"**Objective (horizon cost):** {_fmt(result.get('objective'))}")
        st.write(f"Modules installed: {result.get('modules', 'N/A')}")
        st.write(f"Capacity: {_fmt(result.get('capacity_mw'))} MW")
        shed = result.get("shed", [])
        if shed:
            unserved = sum(shed)
            st.write(f"Unserved energy: {_fmt(unserved)} MWh")
        cdf = _cost_df(result)
        if cdf is not None:
            st.dataframe(cdf, use_container_width=True)
        df = _dispatch_df(result)
        if df is not None:
            supply = df[["hour", "gas", "solar", "shed"]].melt(
                id_vars="hour", var_name="source", value_name="MW"
            )
            demand_line = df[["hour", "demand"]].rename(columns={"demand": "MW"})
            area = (
                alt.Chart(supply)
                .mark_area(opacity=0.7)
                .encode(
                    x="hour:Q",
                    y=alt.Y("MW:Q", stack="zero"),
                    color=alt.Color("source:N", scale=alt.Scale(domain=["gas", "solar", "shed"], range=["#e6550d", "#f39bcb", "#31a354"])),
                )
            )
            line = (
                alt.Chart(demand_line)
                .mark_line(color="#4c78a8", strokeWidth=2, strokeDash=[5, 3])
                .encode(
                    x="hour:Q",
                    y="MW:Q",
                    tooltip=[alt.Tooltip("hour:Q"), alt.Tooltip("MW:Q", title="Demand (MW)")],
                )
            )
            chart = (area + line).properties(height=300).interactive()
            st.altair_chart(chart, use_container_width=True)
        st.write(f"Active modules: {result.get('active_modules', [])}")
        st.write(f"Startup: {result.get('startup', [])}")
        st.write(f"Shutdown: {result.get('shutdown', [])}")
        res = result.get("residuals", {})
        if res:
            st.write(f"Residuals: {res}")
    elif status == "infeasible":
        st.warning("No feasible solution found.")
        if result.get("error"):
            st.error(result["error"])
    else:
        st.error(f"Error: {result.get('error', 'unknown')}")


def _show_benchmark(report):
    seq = report.get("sequential", {})
    par = report.get("parallel", {})
    comp = report.get("comparison", {})
    st.subheader("Sequential branch")
    st.write(
        f"Workers: {seq.get('workers')} | Pool width: {seq.get('pool_width')} | "
        f"Actual workers: {seq.get('actual_workers')} | "
        f"Engine: {_fmt(seq.get('engine_seconds'))} s | Wall: {_fmt(seq.get('wall_seconds'))} s"
    )
    st.subheader("Parallel branch")
    st.write(
        f"Workers: {par.get('workers')} | Pool width: {par.get('pool_width')} | "
        f"Actual workers: {par.get('actual_workers')} | "
        f"Engine: {_fmt(par.get('engine_seconds'))} s | Wall: {_fmt(par.get('wall_seconds'))} s"
    )
    st.subheader("Comparison")
    st.write(
        f"Matches: {comp.get('matches')} | Speedup: {_fmt(comp.get('speedup'))} | "
        f"Engine speedup: {_fmt(comp.get('engine_speedup'))} | "
        f"Scaling available: {comp.get('scaling_available')} | "
        f"Overlap observed: {comp.get('overlap_observed')}"
    )
    if not comp.get("scaling_available"):
        st.info("Only one worker was used; no parallel scaling claim is made.")
    # Worker intervals
    rows = par.get("rows", [])
    if rows:
        interval_df = pd.DataFrame(
            [
                {
                    "case": r.get("case"),
                    "pid": r.get("pid"),
                    "start": r.get("start_monotonic"),
                    "end": r.get("end_monotonic"),
                    "duration": (r.get("end_monotonic", 0) - r.get("start_monotonic", 0)),
                }
                for r in rows
            ]
        )
        st.dataframe(interval_df, use_container_width=True)
    # Speedup chart (separate marks, never stacked)
    if comp.get("speedup") is not None and comp.get("engine_speedup") is not None:
        spd = pd.DataFrame(
            [
                {"metric": "wall_speedup", "value": comp["speedup"]},
                {"metric": "engine_speedup", "value": comp["engine_speedup"]},
            ]
        )
        bar = (
            alt.Chart(spd)
            .mark_bar()
            .encode(x="metric:N", y="value:Q", color="metric:N")
            .properties(height=200)
        )
        st.altair_chart(bar, use_container_width=True)


def main():
    st.title("MILP Energy Lab")

    if "analysis" not in st.session_state:
        st.session_state["analysis"] = None
    if "analysis_signature" not in st.session_state:
        st.session_state["analysis_signature"] = None
    if "comparisons" not in st.session_state:
        st.session_state["comparisons"] = []
    if "benchmark_result" not in st.session_state:
        st.session_state["benchmark_result"] = None
    if "benchmark_signature" not in st.session_state:
        st.session_state["benchmark_signature"] = None

    tab_exp, tab_ins, tab_cmp, tab_scl, tab_rep = st.tabs(
        ["Experiment", "Inspect", "Compare", "Scale", "Reproduce"]
    )

    # ─── Experiment ───
    with tab_exp:
        defaults = default_settings()
        with st.form("milp_exp_form"):
            hours = st.selectbox("Horizon (hours)", [4, 12, 24],
                                 index=[4, 12, 24].index(defaults["hours"]),
                                 key="milp_hours")
            demand_multiplier = st.slider("Demand multiplier", 0.1, 3.0,
                                          float(defaults["demand_multiplier"]), 0.1,
                                          key="milp_dm")
            module_mw = st.number_input("Module size (MW)", 10.0, 1000.0,
                                        float(defaults["module_mw"]), 1.0,
                                        key="milp_mmw")
            max_modules = st.number_input("Max modules", 1, 200,
                                          int(defaults["max_modules"]), 1,
                                          key="milp_maxm")
            min_loading = st.slider("Min loading fraction", 0.0, 1.0,
                                    float(defaults["min_loading"]), 0.01,
                                    key="milp_minl")
            investment_cost = st.number_input("Investment cost (per MW per horizon)",
                                              0.0, 1000.0,
                                              float(defaults["investment_cost"]), 0.1,
                                              key="milp_inv")
            marginal_cost = st.number_input("Marginal cost", 0.01, 1000.0,
                                            float(defaults["marginal_cost"]), 0.01,
                                            key="milp_marg")
            standby_cost = st.number_input("Standby cost", 0.0, 10000.0,
                                           float(defaults["standby_cost"]), 0.1,
                                           key="milp_stby")
            startup_cost = st.number_input("Startup cost", 0.0, 10000.0,
                                           float(defaults["startup_cost"]), 0.1,
                                           key="milp_stup")
            solar_capacity = st.number_input("Solar capacity (MW)", 0.0, 20000.0,
                                             float(defaults["solar_capacity"]), 1.0,
                                             key="milp_solar")
            allow_shedding = st.checkbox("Allow shedding",
                                         bool(defaults["allow_shedding"]),
                                         key="milp_shed")
            solver_time_limit = st.number_input("Solver time limit (s)", 0.1, 10.0,
                                                float(defaults["solver_time_limit"]), 0.1,
                                                key="milp_tlimit")
            mip_rel_gap = st.number_input("MIP relative gap", 0.0, 0.1,
                                          float(defaults["mip_rel_gap"]), 0.001,
                                          key="milp_gap")
            submitted = st.form_submit_button("Run analysis")

        if submitted:
            settings = {
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
                "solver_time_limit": float(solver_time_limit),
                "mip_rel_gap": float(mip_rel_gap),
            }
            try:
                validate_settings(settings)
            except Exception as e:
                st.error(f"Validation failed: {e}")
            else:
                with st.spinner("Solving…"):
                    try:
                        result = run_scenario(settings)
                    except Exception as e:
                        st.error(f"Run failed: {e}")
                        result = None
                if result is not None:
                    st.session_state["analysis"] = result
                    st.session_state["analysis_signature"] = _sig(settings)
                    st.session_state["benchmark_result"] = None
                    st.session_state["benchmark_signature"] = None

        if st.session_state["analysis"] is not None:
            _show_result(st.session_state["analysis"])
        else:
            st.info("No analysis has been run yet. Configure settings and press 'Run analysis'.")

    # ─── Inspect ───
    with tab_ins:
        result = st.session_state["analysis"]
        if result is None:
            st.info("Run an analysis first in the Experiment tab.")
        else:
            settings = result.get("settings", {})
            st.subheader("Committed settings")
            st.json(settings)

            st.subheader("Model formulation")
            try:
                artifact = model_artifact_text(settings)
            except Exception as e:
                artifact = f"Error generating artifact: {e}"
            st.code(artifact, language="text")
            st.download_button("Download formulation text",
                               data=artifact, file_name="model_formulation.txt",
                               mime="text/plain", key="milp_dl_form")

            st.subheader("Solver diagnostics")
            solver = result.get("solver", {})
            st.json(solver)

            st.subheader("Residuals")
            res = result.get("residuals", {})
            if res:
                st.json(res)
            else:
                st.write("No residuals (no incumbent or validation failed).")

            st.subheader("Transition method")
            st.write(result.get("transition_method", "N/A"))

            st.subheader("Downloads")
            result_json = json.dumps(result, allow_nan=False, indent=2)
            st.download_button("Download result JSON", data=result_json,
                               file_name="result.json", mime="application/json",
                               key="milp_dl_json")
            df = _dispatch_df(result)
            if df is not None and result.get("status") in ("optimal", "feasible"):
                st.download_button("Download schedule CSV", data=df.to_csv(index=False),
                                   file_name="schedule.csv", mime="text/csv",
                                   key="milp_dl_csv")
            else:
                st.caption("No schedule available for download.")

    # ─── Compare ───
    with tab_cmp:
        result = st.session_state["analysis"]
        if result is not None:
            if st.button("Keep scenario", key="milp_keep"):
                if len(st.session_state["comparisons"]) < 10:
                    st.session_state["comparisons"].append(
                        json.loads(json.dumps(result, allow_nan=False))
                    )
                else:
                    st.warning("Comparison limit (10) reached. Clear first.")
            if st.button("Clear comparisons", key="milp_clear_cmp"):
                st.session_state["comparisons"] = []

        comparisons = st.session_state["comparisons"]
        if not comparisons:
            st.info("No scenarios kept yet. Use 'Keep scenario' after running an analysis.")
        else:
            rows = []
            for i, c in enumerate(comparisons):
                s = c.get("settings", {})
                rows.append({
                    "idx": i,
                    "status": c.get("status"),
                    "hours": s.get("hours"),
                    "demand_mult": s.get("demand_multiplier"),
                    "module_mw": s.get("module_mw"),
                    "max_modules": s.get("max_modules"),
                    "objective": c.get("objective"),
                    "modules": c.get("modules"),
                    "capacity_mw": c.get("capacity_mw"),
                    "elapsed": c.get("elapsed_seconds"),
                })
            cmp_df = pd.DataFrame(rows)
            st.dataframe(cmp_df, use_container_width=True)

            cmp_json = json.dumps(comparisons, allow_nan=False, indent=2)
            st.download_button("Download comparisons JSON", data=cmp_json,
                               file_name="comparisons.json", mime="application/json",
                               key="milp_dl_cmp_json")
            st.download_button("Download comparisons CSV", data=cmp_df.to_csv(index=False),
                               file_name="comparisons.csv", mime="text/csv",
                               key="milp_dl_cmp_csv")

    # ─── Scale ───
    with tab_scl:
        caps = cpu_limits()
        effective = caps.get("effective_cpus", 1)
        st.subheader("CPU limits")
        st.write(f"Effective CPUs: {effective}")
        st.write(f"Observed caps: {caps.get('observed_caps', [])}")

        max_workers = max(1, min(4, effective))
        cases_choice = st.selectbox("Batch size", [4, 8, 12], index=0, key="milp_cases")
        workers_choice = st.selectbox("Workers", list(range(1, max_workers + 1)),
                                      index=0, key="milp_workers")

        result = st.session_state["analysis"]
        if result is None:
            st.info("A committed scenario is required. Run an analysis first.")
        else:
            committed_settings = result.get("settings", {})
            current_sig = _sig(committed_settings) + f"|cases={cases_choice}|workers={workers_choice}"

            if st.button("Run benchmark", key="milp_run_bench"):
                with st.spinner("Running benchmark…"):
                    try:
                        batch = make_batch(committed_settings, cases_choice)
                        report = run_benchmark(batch, workers_choice)
                    except Exception as e:
                        st.error(f"Benchmark failed: {e}")
                        report = None
                if report is not None:
                    st.session_state["benchmark_result"] = report
                    st.session_state["benchmark_signature"] = current_sig

            stored = st.session_state["benchmark_result"]
            if stored is not None:
                stored_sig = st.session_state["benchmark_signature"]
                if stored_sig == current_sig:
                    st.caption("Report matches current controls.")
                else:
                    st.warning("Controls changed since last benchmark. Report reflects previous parameters. Re-run to update.")
                _show_benchmark(stored)
            else:
                st.info("No benchmark has been run yet.")

    # ─── Reproduce ───
    with tab_rep:
        st.subheader("Provenance")
        st.write(
            "This lab is based on the PyPSA modular-committable notebook "
            "(commit `c838aa498557cc8e27a9d3ed10d45e35c4b0b442`), "
            "licensed CC BY 4.0. The PyPSA library is MIT-licensed. "
            "The AGILAB pool engine is unchanged (BSD 3-Clause)."
        )

        st.subheader("Model description")
        st.write(
            "- **Integer installed modules** (`n_mod`): a single integer variable representing "
            "the number of identical gas modules to install (0 to `max_modules`)."
        )
        st.write(
            "- **Integer hourly active count** (`status`): an integer variable per snapshot "
            "representing how many of the installed modules are active (0 to `n_mod`). "
            "This is NOT a binary on/off per module; it is a count."
        )
        st.write(
            "- **Energy-balance equality**: `gas + solar + shed == demand` at every snapshot."
        )
        st.write(
            f"- **Minimum loading**: when a module is active, it must produce at least "
            f"`min_loading × module_mw` MW."
        )
        st.write(
            "- **Curtailed solar**: solar generation is bounded above by available capacity "
            "× availability profile; unused solar is simply not dispatched."
        )
        st.write(
            "- **Optional shedding**: when enabled, a virtual generator with marginal cost "
            "100,000 per MWh absorbs unmet demand."
        )

        st.subheader("Reference values (not freshly measured)")
        st.write(
            "For the 4-hour reference demand profile [4000, 6000, 5000, 800] MW with "
            "200 MW modules, the known optimum is **30 modules** with objective **21,879**. "
            "These are reference values from the source notebook, not results of a fresh solve "
            "in this session."
        )

        st.subheader("Scaling scope")
        st.write(
            "The Scale tab measures local independent-scenario throughput using a bounded "
            "process pool. It does NOT claim distributed-cluster scaling or free-threading "
            "benefits. The public app performs no Qwen inference and makes no Tokki offload claim."
        )

        st.subheader("Build identity")
        st.write(
            "The exact build-model identity is supplied by the host receipt and is not "
            "duplicated here."
        )


if __name__ == "__main__":
    main()