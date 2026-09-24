"""Free-threading lab — Streamlit app.

Runs the real six-case AGILAB benchmark (3 execution modes x {1, N} workers)
in separate free-threaded CPython child processes and renders the measured
evidence. The UI process itself never performs the timed work and never
mutates global environment state; child environments are built fresh per
case. First load shows a deterministic, untimed fractal preview only.
"""
from __future__ import annotations

import json
import os
import tempfile

import streamlit as st

import benchmark
import free_threading_core as core
from free_threading_core import (
    APP_TITLE,
    DEFAULT_ITERATIONS,
    FREE_THREADING_DOCS,
    MAX_REPEATS,
    MAX_WORKERS,
    MODE_LABELS,
    MODES,
    SOURCE_CREDIT,
    TILE_ROWS_MAX,
    TILE_ROWS_MIN,
)

WORKLOADS = {
    "small (96 x 64, 80 iterations)": {"width": 96, "height": 64, "iterations": 80},
    "medium (192 x 128, 160 iterations)": {
        "width": 192,
        "height": 128,
        "iterations": 160,
    },
}

PREVIEW = {"width": 160, "height": 100, "iterations": 80}


@st.cache_data(show_spinner=False, ttl=3600)
def _preview_png(width: int, height: int, iterations: int) -> bytes:
    pixels = core.reference_image(width, height, iterations)
    return core.render_preview_png(pixels, width, height, iterations)


@st.cache_data(show_spinner=False, ttl=3600)
def _cpu_allowance() -> int:
    return core.effective_cpu_allowance()


def _signature(params: dict) -> str:
    return json.dumps(params, sort_keys=True)


def _case_label(case: dict) -> str:
    return f"{case['mode']} · {case['workers']} worker(s)"


def _render_results(payload: dict, stale: bool) -> None:
    results = payload["results"]
    if stale:
        st.warning(
            "Controls changed since this run finished. These results are stale; "
            "press Run analysis again to measure the current configuration."
        )

    st.subheader("Measured speedup vs each mode's 1-worker baseline")
    speedups = results["speedups"]
    cols = st.columns(len(MODES))
    for col, mode in zip(cols, MODES):
        entry = speedups[mode]
        col.metric(
            MODE_LABELS[mode].split(" (")[0],
            f"{entry['speedup']:.2f}x" if entry["speedup"] is not None else "n/a",
            f"{entry['workers']} workers",
        )

    metric_cols = st.columns(4)
    metric_cols[0].metric(
        "Effective CPUs", str(results["hardware"]["effective_cpu_allowance"])
    )
    metric_cols[1].metric(
        "Image digest", results["digest"][:16], help="sha256 of the full pixel array"
    )
    metric_cols[2].metric(
        "Same work across modes", "yes" if results["same_work"] else "no"
    )
    metric_cols[3].metric(
        "Matches serial reference",
        "yes" if results["same_as_serial_reference"] else "no",
    )

    st.subheader("Throughput")
    cases = results["cases"]
    throughput_cols = st.columns(len(cases))
    for col, case in zip(throughput_cols, cases):
        tput = case.get("throughput_pixels_per_s")
        col.metric(
            f"{case['workers']}w · {case['mode'].split('-')[1]}",
            f"{tput:,.0f}" if tput else "n/a",
            "pixels/s (median)",
        )

    st.subheader("Engine time per case (median over repeats)")
    chart_data = [
        {
            "case": f"{case['mode']} ({case['workers']}w)",
            "seconds": round(case.get("median_engine_seconds") or 0.0, 4),
        }
        for case in cases
        if case["status"] == "ok"
    ]
    if chart_data:
        st.bar_chart(chart_data, x="case", y="seconds")

    st.subheader("Recorded task activity after each run")
    for case in cases:
        if case["status"] != "ok":
            continue
        with st.expander(
            f"{case['mode_label']} · {case['workers']} worker(s) — "
            f"engine width {case.get('engine_width')} ({case.get('engine_backend')})"
        ):
            timeline = []
            for rep_index, rep in enumerate(case["repeats"]):
                first_start = min(t["start"] for t in rep["tiles"])
                for tile in rep["tiles"]:
                    timeline.append(
                        {
                            "repeat": rep_index,
                            "rows": f"{tile['row_start']}-{tile['row_end'] - 1}",
                            "start_offset_s": round(tile["start"] - first_start, 4),
                            "duration_s": round(tile["duration_seconds"], 4),
                            "pid": tile["pid"],
                            "thread": str(tile["thread"]),
                        }
                    )
            st.dataframe(timeline, width="stretch", hide_index=True)
            st.caption(
                "Wall-clock tile intervals recorded inside the child process; "
                "pid/thread identify the executor that ran each tile."
            )

    with st.expander("Hardware and interpreter"):
        hardware = results["hardware"]
        interpreter = results["interpreter"]
        st.markdown(
            f"- Platform: `{hardware['platform']}`  \n"
            f"- CPU count: {hardware['cpu_count']} (process view: "
            f"{hardware['process_cpu_count']}, affinity: {hardware['affinity_size']})  \n"
            f"- Effective CPU allowance (cap applied): "
            f"**{hardware['effective_cpu_allowance']}**  \n"
            f"- Interpreter: `{interpreter['executable']}`  \n"
            f"- Version: {interpreter['version']} "
            f"(free-threaded build: {interpreter['free_threaded_build']}, "
            f"Py_GIL_DISABLED: {interpreter['py_gil_disabled_build']})  \n"
            f"- Interpreter startup probe: "
            f"{results.get('interpreter_startup_probe_seconds', 0):.3f}s  \n"
            f"- Total benchmark wall time: {results['total_seconds']}s"
        )

    with st.expander("Methodology"):
        st.markdown(
            "1. All six measured cases run in the **same** free-threaded CPython "
            "build. Modes differ only by the GIL flag and the AGILAB pool backend:\n"
            f"   - {MODE_LABELS[MODES[0]]}\n"
            f"   - {MODE_LABELS[MODES[1]]}\n"
            f"   - {MODE_LABELS[MODES[2]]}\n"
            "2. Each case is a separate child process (private environment, "
            "`PYTHON_GIL` and `AGILAB_POOL_*` scrubbed, then set per mode) that "
            "drives the AGILAB engine (`agilab_pool.run_works`) over "
            "deterministically interleaved row tiles.\n"
            "3. The engine dispatches tiles through a thread or spawn process "
            "pool; reduction reassembles pixels in row-major order. Every mode "
            "and repeat must produce the identical image digest and match the "
            "serial reference — otherwise the run is reported as failed.\n"
            "4. Speedups are medians over repeats, relative to each mode's own "
            "one-worker baseline. Per-child and total timeouts terminate the "
            "whole process group.\n"
            "5. Nothing is simulated; timings are wall-clock measurements of "
            "this machine, and the app never falls back to ordinary Python.\n\n"
            f"Source: {SOURCE_CREDIT}  \n"
            f"Docs: <{FREE_THREADING_DOCS}>"
        )

    st.download_button(
        "Download evidence JSON",
        data=json.dumps(payload, indent=2).encode("utf-8"),
        file_name="free-threading-lab-results.json",
        mime="application/json",
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption(SOURCE_CREDIT)
    st.markdown(
        "This lab measures how the same Mandelbrot escape-count workload scales "
        "on this machine across three execution strategies — **GIL-on threads**, "
        "**GIL-off threads** (free-threaded CPython), and **GIL-on processes** — "
        "using the included AGILAB pool engine for dispatch and reduction. "
        "Everything below is measured live in separate free-threaded child "
        "processes; the first load shows an untimed preview only."
    )

    preview = _preview_png(PREVIEW["width"], PREVIEW["height"], PREVIEW["iterations"])
    st.image(
        preview,
        caption=f"Deterministic preview ({PREVIEW['width']}x{PREVIEW['height']}, "
        f"{PREVIEW['iterations']} iterations) — not a timed run",
    )

    allowance = _cpu_allowance()
    with st.sidebar:
        st.header("Controls")
        workload = st.selectbox(
            "Workload", list(WORKLOADS.keys()), index=1, label_visibility="collapsed"
        )
        workers = st.slider(
            "Workers (N)", min(1, allowance), allowance, min(4, allowance), step=1
        )
        repeats = st.slider("Repeats", 1, MAX_REPEATS, 2, step=1)
        tile_rows = st.slider("Tile rows", TILE_ROWS_MIN, TILE_ROWS_MAX, TILE_ROWS_MAX, step=1)
        run_requested = st.button("Run analysis", type="primary")
        st.caption(f"Effective CPU allowance on this machine: {allowance}")
        st.caption("The app never writes into its own bundle; evidence lands in a temp dir.")

    workload_params = WORKLOADS[workload]
    current_params = {
        "width": workload_params["width"],
        "height": workload_params["height"],
        "iterations": workload_params["iterations"],
        "workers": workers,
        "repeats": repeats,
        "tile_rows": tile_rows,
    }

    def _run_benchmark() -> dict | None:
        try:
            core.validate_params(**current_params)
            if workers > allowance:
                raise ValueError(
                    f"workers={workers} exceeds the effective CPU allowance {allowance}"
                )
        except ValueError as exc:
            st.error(f"Invalid configuration: {exc}")
            return None

        out_dir = tempfile.mkdtemp(prefix="free-threading-lab-")
        out_path = os.path.join(out_dir, "results.json")

        status = st.status("Running six-case benchmark", expanded=True)
        progress = status.progress(0.0, text="starting child processes")

        def on_progress(done: int, total: int, label: str) -> None:
            progress.progress(done / total, text=f"{label} — done")

        try:
            payload = benchmark.run_benchmark(
                width=current_params["width"],
                height=current_params["height"],
                iterations=current_params["iterations"],
                workers=workers,
                repeats=repeats,
                tile_rows=tile_rows,
                child_timeout=60.0,
                total_timeout=150.0,
                root=out_dir,
                out_path=out_path,
                progress_cb=on_progress,
            )
        except (ValueError, RuntimeError, core.FreeThreadingInterpreterError) as exc:
            status.update(label="Benchmark failed", state="error", expanded=True)
            st.error(f"Benchmark failed: {exc}")
            return None

        status.update(label="Benchmark complete", state="complete", expanded=False)
        st.session_state["last_results"] = payload
        st.session_state["last_signature"] = _signature(current_params)
        st.success(
            "Measured run complete — same image digest across all modes and "
            f"repeats. Evidence written to {out_path}"
        )
        return payload

    payload = None
    if run_requested:
        payload = _run_benchmark()
    else:
        payload = st.session_state.get("last_results")

    if payload is not None:
        stale = st.session_state.get("last_signature") != _signature(current_params)
        _render_results(payload, stale)


if __name__ == "__main__":
    main()
