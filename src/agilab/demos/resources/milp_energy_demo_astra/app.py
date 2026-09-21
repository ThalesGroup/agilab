"""Native Streamlit interface for MILP Energy Lab. See LICENSE for attribution."""

from __future__ import annotations

import copy
import json

import altair as alt
import pandas as pd
import streamlit as st

from energy_core import (
    SOURCE_URL,
    cpu_limits,
    default_settings,
    make_batch,
)
from energy_runner import run_benchmark, run_scenario

P = "milp_energy_"
st.set_page_config(
    page_title="MILP Energy Lab", page_icon=":material/bolt:", layout="wide"
)
st.title("MILP Energy Lab")
st.markdown(
    "Build just enough generation, schedule integer modules, and explore the cost of keeping the lights on."
)
st.caption(
    "Tokki × AGILAB · Lab 05 · Synthetic hourly power system · Local HiGHS solver"
)
st.markdown(
    "**Start here:** choose a scenario, click **Run analysis**, then inspect the schedule, compare alternatives or measure a batch."
)
st.caption(
    f"Adapted from [Modular Expansion with Unit Commitment]({SOURCE_URL}) by PyPSA contributors, "
    "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). "
    "Changes: interactive parameters, HiGHS, solar/shedding, independent solver checks and AGILAB batch measurement."
)


def json_text(value):
    return json.dumps(value, indent=2, allow_nan=False)


def metrics(items):
    with st.container(horizontal=True):
        for label, value, help_text in items:
            with st.container(border=True, width="stretch"):
                st.metric(label, value, help=help_text)


def run_with_status(function, *args):
    with st.status("Starting isolated computation…", expanded=True) as status:
        progress = st.empty()
        last = [-1]

        def update(seconds):
            if int(seconds) != last[0]:
                last[0] = int(seconds)
                progress.caption(
                    f"Computing · {seconds:.0f} s in the current phase · bounded time budget"
                )

        try:
            result = function(*args, progress=update)
        except (ValueError, RuntimeError, TimeoutError) as exc:
            status.update(label="Run could not complete", state="error")
            st.error(str(exc))
            return None
        status.update(label="Computation finished", state="complete", expanded=False)
        return result


def schedule_frame(result):
    return pd.DataFrame(
        {
            "Hour": range(len(result["demand"])),
            "Demand": result["demand"],
            "Gas": result["dispatch"],
            "Solar": result["solar"],
            "Unserved": result["shed"],
            "Active modules": result["active_modules"],
            "Starts": result["startup"],
            "Stops": result["shutdown"],
            "Solar available": result["solar_available"],
        }
    )


def summary(result):
    settings = result["settings"]
    st.caption(
        f"Showing solved inputs {result['input_sha256'][:10]} · {settings['hours']} h · "
        f"demand ×{settings['demand_multiplier']:g} · {settings['module_mw']:g} MW/module · "
        f"cap {settings['max_modules']} modules. Editing controls does not change this saved result."
    )
    with st.expander("Inputs used for this result"):
        st.json(settings)
    if result["status"] in ("infeasible", "error"):
        st.error(f"{result['status'].capitalize()} · {result.get('message', '')}")
        st.caption("No incumbent: objective, capacity and schedules are unavailable.")
        return
    if result["status"] == "feasible":
        st.warning("Verified feasible incumbent; optimality has not been established.")
    else:
        st.success(
            "Verified feasible · HiGHS reports optimal within the configured MIP tolerance."
        )
    if sum(result["shed"]) > 1e-5:
        st.warning(
            "Load shedding is positive. This schedule is feasible only when unmet demand is permitted; it does not serve all load."
        )
    metrics(
        [
            (
                "Horizon cost",
                f"{result['objective']:,.2f}",
                "Illustrative cost units; investment is a horizon charge, not annual economics.",
            ),
            (
                "Installed modules",
                f"{result['modules']:.0f}",
                f"{result['capacity_mw']:,.0f} MW installed",
            ),
            (
                "Unserved energy",
                f"{sum(result['shed']):,.0f} MWh",
                "One-hour snapshots. Zero means all demand was served.",
            ),
            (
                "Full wall time",
                f"{result.get('wall_seconds', result['elapsed_seconds']):.2f} s",
                "Includes process startup, imports, solve, validation and cleanup.",
            ),
        ]
    )
    frame = schedule_frame(result)
    long = frame.melt(
        "Hour", ["Gas", "Solar", "Unserved"], var_name="Source", value_name="MW"
    )
    supply = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("Hour:O", title="Hour"),
            y=alt.Y("MW:Q", title="Power (MW)"),
            color=alt.Color(
                "Source:N",
                scale=alt.Scale(
                    domain=["Gas", "Solar", "Unserved"],
                    range=["#2563eb", "#f5b82e", "#ef4444"],
                ),
            ),
            tooltip=["Hour", "Source", alt.Tooltip("MW:Q", format=",.1f")],
        )
    )
    demand = (
        alt.Chart(frame)
        .mark_line(color="#334155", point=True, strokeWidth=2)
        .encode(x="Hour:O", y="Demand:Q", tooltip=["Hour", "Demand"])
    )
    st.altair_chart(
        (supply + demand).properties(
            title="Hourly balance · line = demand", height=270
        ),
        width="stretch",
    )
    active = (
        alt.Chart(frame)
        .mark_bar(color="#0d9488")
        .encode(
            x="Hour:O",
            y=alt.Y("Active modules:Q", title="Integer modules"),
            tooltip=["Hour", "Active modules", "Starts", "Stops"],
        )
    )
    installed = (
        alt.Chart(pd.DataFrame({"Installed": [result["modules"]]}))
        .mark_rule(strokeDash=[5, 4], color="#64748b")
        .encode(y="Installed:Q")
    )
    st.altair_chart(
        (active + installed).properties(
            title="Commitment · dashed line = installed modules", height=180
        ),
        width="stretch",
    )
    costs = pd.DataFrame(
        {"Cost": list(result["costs"]), "Value": list(result["costs"].values())}
    )
    st.altair_chart(
        alt.Chart(costs)
        .mark_bar(color="#6366f1")
        .encode(
            x=alt.X("Value:Q", title="Horizon cost units"),
            y=alt.Y("Cost:N", sort="-x"),
            tooltip=["Cost", alt.Tooltip("Value", format=",.2f")],
        )
        .properties(height=180, title="What drives the cost?"),
        width="stretch",
    )


experiment, inspect, compare, scale, reproduce = st.tabs(
    ["Experiment", "Inspect", "Compare", "Scale", "Reproduce"]
)
with experiment:
    with st.form(P + "controls"):
        st.subheader("Design a scenario")
        with st.container(horizontal=True):
            hours = st.selectbox("Horizon (hours)", [4, 12, 24], key=P + "hours")
            multiplier = st.number_input(
                "Demand multiplier", 0.1, 2.0, 1.0, 0.1, key=P + "demand"
            )
            module = st.number_input(
                "Module size (MW)", 50.0, 1000.0, 200.0, 50.0, key=P + "module"
            )
            cap = st.number_input("Maximum modules", 1, 100, 50, key=P + "cap")
        with st.expander("Costs and operating limits", expanded=True):
            with st.container(horizontal=True):
                investment = st.number_input(
                    "Investment / MW / horizon",
                    0.0,
                    1000.0,
                    1.0,
                    1.0,
                    key=P + "investment",
                )
                marginal = st.number_input(
                    "Gas cost / MWh", 0.0, 1000.0, 1.0, 1.0, key=P + "marginal"
                )
                startup = st.number_input(
                    "Startup / module", 0.0, 100000.0, 0.0, 100.0, key=P + "startup"
                )
                standby = st.number_input(
                    "Standby / module-hour", 0.0, 10000.0, 1.0, 1.0, key=P + "standby"
                )
            with st.container(horizontal=True):
                minimum = st.slider(
                    "Minimum loading", 0.0, 1.0, 0.1, 0.05, key=P + "minimum"
                )
                solar = st.number_input(
                    "Solar capacity (MW)", 0.0, 12000.0, 0.0, 200.0, key=P + "solar"
                )
                shedding = st.checkbox(
                    "Allow high-cost load shedding",
                    key=P + "shedding",
                    help="Unserved load costs 100,000 units/MWh. A feasible schedule with shedding is not full supply.",
                )
            st.caption(
                "All modules start off. Investment is charged once for this horizon. Solar has a fixed synthetic profile and can be curtailed."
            )
        with st.expander("Solver budget"):
            limit = st.slider(
                "HiGHS time limit (seconds)", 0.1, 10.0, 5.0, 0.1, key=P + "time_limit"
            )
            gap = st.select_slider(
                "Relative MIP tolerance",
                [0.0, 0.0001, 0.001, 0.01, 0.05],
                value=0.0001,
                key=P + "gap",
            )
            st.caption(
                "One solver thread. Reported gaps come from HiGHS; unavailable values remain unavailable."
            )
        submitted = st.form_submit_button(
            "Run analysis", type="primary", width="stretch", key=P + "run"
        )
    inputs = default_settings() | dict(
        hours=hours,
        demand_multiplier=multiplier,
        module_mw=module,
        max_modules=cap,
        investment_cost=investment,
        marginal_cost=marginal,
        startup_cost=startup,
        standby_cost=standby,
        min_loading=minimum,
        solar_capacity=solar,
        allow_shedding=shedding,
        time_limit=limit,
        mip_rel_gap=gap,
    )
    if submitted:
        result = run_with_status(run_scenario, inputs)
        if result is not None:
            st.session_state[P + "result"] = result
    result = st.session_state.get(P + "result")
    if result:
        summary(result)
    else:
        st.info(
            "Ready when you are. The default four-hour case is small enough to check by hand; no solver runs until you click."
        )
    with st.expander("Try a commitment tradeoff"):
        st.markdown(
            "For a clear startup tradeoff, use **12 hours** and compare startup cost **0** with **1,000** per module. "
            "The repeated demand valleys make keeping spare modules online potentially cheaper than restarting them. "
            "Set **Maximum modules = 10** to test shortage, then allow shedding to quantify unserved energy."
        )

with inspect:
    st.subheader("Open the model")
    st.markdown(
        "**Decisions:** installed and active module counts, gas dispatch, solar use, starts, stops and unserved load. "
        "**Balance:** gas + used solar + unserved load = demand each hour. "
        "**Commitment:** active modules cannot exceed installed modules; each active module operates between its minimum loading and rated MW."
    )
    if result:
        st.caption("This inspection belongs to result " + result["input_sha256"][:10])
        solver = result["solver"]
        metrics(
            [
                ("Termination", solver["termination"], "Native HiGHS termination"),
                (
                    "Reported MIP gap",
                    f"{solver['gap']:.4%}"
                    if solver["gap"] is not None
                    else "Unavailable",
                    "Native relative MIP gap, never inferred",
                ),
                (
                    "Objective bound",
                    f"{solver['objective_bound']:,.3f}"
                    if solver["objective_bound"] is not None
                    else "Unavailable",
                    "Native HiGHS MIP dual bound",
                ),
                (
                    "Feasibility checks",
                    "Passed"
                    if result["residuals"]["verified"]
                    else "No verified incumbent",
                    "Independent integrality, balance, capacity, transitions and objective reconstruction",
                ),
            ]
        )
        if result["objective"] is not None:
            st.dataframe(schedule_frame(result), width="stretch", hide_index=True)
        st.json(result["residuals"])
        st.code(result["model_text"], language=None)
    else:
        st.info("Run an analysis to inspect solved values and residuals.")

with compare:
    st.subheader("Keep alternatives side by side")
    st.caption(
        "Up to 10 named scenarios in this browser session. Saving uses the last solved inputs, not edited controls."
    )
    saved = st.session_state.setdefault(P + "saved", [])
    with st.form(P + "save_form"):
        name = st.text_input(
            "Scenario name",
            value=f"Scenario {len(saved) + 1}",
            max_chars=60,
            key=P + "scenario_name",
        )
        save = st.form_submit_button(
            "Save current scenario",
            disabled=result is None or len(saved) >= 10,
            key=P + "save",
        )
    if save and result:
        if not name.strip():
            st.warning("Choose a nonempty scenario name.")
        elif any(x["name"] == name.strip() for x in saved):
            st.warning("That name is already saved. Use a distinct name.")
        else:
            saved.append(dict(name=name.strip(), result=copy.deepcopy(result)))
    if saved:
        rows = []
        for item in saved:
            r, s = item["result"], item["result"]["settings"]
            rows.append(
                dict(
                    Name=item["name"],
                    Status=r["status"],
                    Hours=s["hours"],
                    Demand=s["demand_multiplier"],
                    Cost=r["objective"],
                    MW=r["capacity_mw"],
                    Modules=r["modules"],
                    ModuleMW=s["module_mw"],
                    Cap=s["max_modules"],
                    Minimum=s["min_loading"],
                    Investment=s["investment_cost"],
                    Marginal=s["marginal_cost"],
                    Standby=s["standby_cost"],
                    Startup=s["startup_cost"],
                    Solar=s["solar_capacity"],
                    Shedding=s["allow_shedding"],
                )
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption(
            "Cost comparisons are meaningful only with comparable horizons, demand and service requirements. All exact inputs are included in the download."
        )
        chart = pd.DataFrame(rows).dropna(subset=["Cost"])
        if not chart.empty:
            st.altair_chart(
                alt.Chart(chart)
                .mark_bar(color="#6366f1")
                .encode(
                    x="Name:N",
                    y=alt.Y("Cost:Q", title="Horizon cost"),
                    tooltip=["Name", "Cost", "Hours", "Demand", "Status"],
                )
                .properties(height=240),
                width="stretch",
            )
        if st.button("Clear saved scenarios", key=P + "clear"):
            st.session_state[P + "saved"] = []
            st.rerun()

with scale:
    st.subheader("Does a batch benefit from more workers?")
    st.markdown(
        "Run the **same varied scenarios** sequentially and through the actual AGILAB worker pool. "
        "Each independent MILP uses one HiGHS thread. Process startup and imports count; parallel runs can be slower."
    )
    environment = cpu_limits()
    cpus = environment["effective_cpus"]
    st.caption(
        f"Available worker budget: {cpus} · local spawned processes, not a distributed cluster or acceleration of one MILP."
    )
    with st.expander("Environment limits"):
        st.json(environment)
    with st.form(P + "scale_form"):
        count = st.selectbox("Scenarios", [4, 8, 12], key=P + "count")
        workers = st.selectbox(
            "Parallel workers",
            list(range(2, cpus + 1)) if cpus > 1 else [1],
            key=P + "workers",
            disabled=cpus < 2,
        )
        st.caption(
            "Based on the last solved settings (or defaults). Demand, solar and startup costs vary deterministically across cases. Both runs receive identical inputs; combined budget is 150 s."
        )
        benchmark_clicked = st.form_submit_button(
            "Run scaling experiment",
            disabled=cpus < 2,
            type="primary",
            key=P + "scale_run",
        )
    if cpus < 2:
        st.info(
            "Scaling is unavailable with one effective CPU. Single-scenario analysis remains available."
        )
    if benchmark_clicked:
        batch = make_batch(result["settings"] if result else default_settings(), count)
        report = run_with_status(run_benchmark, batch, workers)
        if report is not None:
            st.session_state[P + "benchmark"] = report
    report = st.session_state.get(P + "benchmark")
    if report:
        st.caption(
            f"Measured batch {report['batch_sha256'][:12]} · {len(report['batch'])} cases · "
            f"1 vs {report['parallel']['workers']} workers. Controls do not relabel this measurement."
        )
        metrics(
            [
                (
                    "Measured speedup",
                    f"{report['speedup']:.2f}×",
                    "Sequential full wall / parallel full wall. Below 1 means parallel was slower.",
                ),
                (
                    "1 worker",
                    f"{report['sequential_cases_per_second']:.2f} cases/s",
                    f"Full wall {report['sequential']['wall_seconds']:.2f} s",
                ),
                (
                    "Parallel",
                    f"{report['parallel_cases_per_second']:.2f} cases/s",
                    f"Full wall {report['parallel']['wall_seconds']:.2f} s",
                ),
                (
                    "Whole experiment",
                    f"{report['total_wall_seconds']:.2f} s",
                    "Both runs, startup/imports and cleanup",
                ),
            ]
        )
        if report["comparison"]["matches"]:
            st.success(
                "All statuses and objectives match within abs 0.0001 / rel 1e-7. Multiple optimal schedules need not match."
            )
        else:
            st.warning(
                "Some cases did not match or return a verified result. Inspect the per-case report; timings do not establish equivalent solutions."
            )
        st.dataframe(
            pd.DataFrame(report["comparison"]["cases"]),
            width="stretch",
            hide_index=True,
        )
        timeline = []
        for label, run in [
            ("Sequential", report["sequential"]),
            ("Parallel", report["parallel"]),
        ]:
            origin = min(row["start_monotonic"] for row in run["rows"])
            for row in run["rows"]:
                timeline.append(
                    dict(
                        Mode=label,
                        Worker=f"{label} · PID {row['pid']}",
                        Case=str(row["case"] + 1),
                        Start=row["start_monotonic"] - origin,
                        End=row["end_monotonic"] - origin,
                    )
                )
        st.altair_chart(
            alt.Chart(pd.DataFrame(timeline))
            .mark_bar()
            .encode(
                x=alt.X("Start:Q", title="Seconds from first work item in each run"),
                x2="End:Q",
                y="Worker:N",
                color="Case:N",
                tooltip=["Mode", "Worker", "Case", "Start", "End"],
            )
            .properties(height=250, title="Measured worker activity"),
            width="stretch",
        )
        st.caption(
            f"Full wall times: sequential {report['sequential']['wall_seconds']:.2f} s; parallel {report['parallel']['wall_seconds']:.2f} s. "
            f"Engine times: sequential {report['sequential']['engine_seconds']:.2f} s; parallel {report['parallel']['engine_seconds']:.2f} s. "
            "Timeline includes per-worker imports and solves, but excludes time before the first work item; full-wall metrics include everything. No timing cache."
        )
        with st.expander("Exact measured batch inputs"):
            st.json(report["batch"])

with reproduce:
    st.subheader("Take the experiment with you")
    st.markdown(
        "Download the exact inputs, checked outputs and mathematical model. These files contain no executable user code."
    )
    if result:
        st.download_button(
            "Settings JSON",
            json_text(result["settings"]),
            "milp-settings.json",
            "application/json",
            key=P + "download_settings",
        )
        st.download_button(
            "Results JSON",
            json_text(result),
            "milp-results.json",
            "application/json",
            key=P + "download_result",
        )
        st.download_button(
            "Exact model text",
            result["model_text"],
            "milp-model.txt",
            "text/plain",
            key=P + "download_model",
        )
    if st.session_state.get(P + "saved"):
        st.download_button(
            "Scenario comparison JSON",
            json_text(st.session_state[P + "saved"]),
            "milp-comparison.json",
            "application/json",
            key=P + "download_comparison",
        )
    if st.session_state.get(P + "benchmark"):
        st.download_button(
            "Benchmark JSON",
            json_text(st.session_state[P + "benchmark"]),
            "milp-benchmark.json",
            "application/json",
            key=P + "download_benchmark",
        )
    st.code(
        "python energy_core.py single --input milp-settings.json --output replay.json\npython tests.py\nstreamlit run app.py --server.address=127.0.0.1",
        language="bash",
    )
    st.caption(
        "Source, licensing and standalone execution instructions are in README.md. The AGILAB gallery supplies its own notebook, workflow ZIP and build evidence."
    )
