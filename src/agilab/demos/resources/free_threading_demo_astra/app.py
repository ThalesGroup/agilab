"""Native Streamlit interface; timed execution lives only in benchmark children."""
import io
import json

import altair as alt
from PIL import Image
import streamlit as st

from benchmark import BusyError, LABELS, effective_cpus, run_benchmark
from free_threading_core import reference_image

st.set_page_config(page_title="Free-threading lab", page_icon="🌀", layout="wide")
st.title("Free-threading lab")
st.caption("LOCAL CPU SCALING · PURE PYTHON · REAL AGILAB POOL ENGINE")
st.markdown("Explore the Mandelbrot set while measuring how **the same free-threaded Python build** "
            "scales with GIL-on threads, GIL-off threads and GIL-on processes. "
            "Identical pixels. Identical tiles. Actual measured work.")


@st.cache_data(max_entries=2, show_spinner=False)
def preview(width=192, height=128, iterations=160):
    counts = reference_image(width, height, iterations)
    colors = []
    for n in counts:
        if n == iterations:
            colors.append((9, 14, 35))
        else:
            t = (n / iterations) ** 0.42
            colors.append((int(255 * (1 - t) * t * 3.8) % 256,
                           int(220 * t), int(100 + 155 * (1 - t))))
    image = Image.new("RGB", (width, height))
    image.putdata(colors)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


left, right = st.columns([1.5, 1])
with left:
    st.image(preview(), caption="Mandelbrot escape counts · deterministic preview, not a timed run",
             width="stretch")
with right:
    st.subheader("Choose your experiment")
    workload = st.selectbox("Workload", ["Small · 192 × 128 · 160 iterations",
                                          "Medium · 288 × 192 · 240 iterations"])
    try:
        hardware = effective_cpus()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    cap = hardware["effective_cpus"]
    workers = st.selectbox("Workers (N)", list(range(1, cap + 1)), index=min(4, cap) - 1)
    repeats = st.selectbox("Repeats per case", [1, 2, 3], index=1)
    st.caption(f"Effective CPU limit: {cap} · each mode runs with 1 and {workers} worker(s).")
    if cap == 1:
        st.info("Only one CPU is available: parallel scaling is unavailable. "
                "The two widths are both 1; timing differences are run-to-run variation.")
    elif workers == 1:
        st.info("Choose N > 1 to examine scaling. Both cases currently use one worker.")
    run_clicked = st.button("Run analysis", type="primary", width="stretch")

dimensions = (192, 128, 160) if workload.startswith("Small") else (288, 192, 240)
signature = (*dimensions, workers, repeats)
if run_clicked:
    with st.status("Running isolated CPU measurements…", expanded=True) as status:
        bar = st.progress(0.0, text="Waiting for the local benchmark lock")
        def progress(done, total, label):
            bar.progress(done / total, text=f"{done}/{total} · {label}")
        try:
            report = run_benchmark(*dimensions, workers=workers, repeats=repeats, progress=progress)
        except BusyError as exc:
            status.update(label="CPU lab is busy", state="error")
            st.warning(str(exc))
        except (RuntimeError, ValueError, TimeoutError, OSError) as exc:
            status.update(label="Analysis did not complete", state="error")
            st.error(str(exc))
        else:
            st.session_state["analysis"] = report
            st.session_state["analysis_signature"] = signature
            status.update(label="All cases measured · same-work verification passed", state="complete", expanded=False)

report = st.session_state.get("analysis")
if report:
    if st.session_state.get("analysis_signature") != signature:
        st.warning("Previous results: controls have changed. Run analysis again to measure these settings.")
    st.subheader("Measured local CPU scaling")
    st.caption(f"Recorded {report['created_utc']} · {report['parameters']['repeats']} repeat(s) per case · "
               f"{report['parameters']['width']} × {report['parameters']['height']} pixels · "
               f"{report['parameters']['iterations']} iterations maximum")
    scaled = [row for row in report["summary"] if row["role"] == "scaled"]
    for column, row in zip(st.columns(3), scaled):
        with column:
            with st.container(border=True):
                st.markdown(f"**{row['label']}**")
                st.metric("End-to-end speedup", f"{row['speedup']:.2f}×")
                st.metric("Throughput", f"{row['pixels_per_second']:,.0f} pixels/s")
                st.caption(f"Median wall: {row['wall_seconds']:.3f} s · "
                           f"engine: {row['engine_seconds']:.3f} s · "
                           f"engine speedup: {row['engine_speedup']:.2f}×")
    st.caption("Each speedup uses that mode’s own one-worker median. "
               "Values below 1× mean slower. Startup and scheduling can dominate small workloads; "
               "linear speedup is not guaranteed.")
    timing_rows = [{"Case": f"{r['label']} / {r['role']} ({r['workers']})",
                    "Timing": timing, "Seconds": r[key]}
                   for r in report["summary"]
                   for timing, key in (("End-to-end", "wall_seconds"), ("Engine", "engine_seconds"))]
    chart = alt.Chart(alt.Data(values=timing_rows)).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("Seconds:Q", title="Median elapsed seconds"),
        y=alt.Y("Case:N", sort=None, title=None), yOffset="Timing:N",
        color=alt.Color("Timing:N", scale=alt.Scale(range=["#3b82f6", "#22c5ad"])),
        tooltip=["Case:N", "Timing:N", alt.Tooltip("Seconds:Q", format=".4f")],
    ).properties(height=350)
    st.altair_chart(chart, width="stretch")
    st.success(f"Same-work verified: every tile occurred exactly once and all {len(report['runs'])} "
               "complete-image digests match across modes, widths and repeats.")
    st.code(report["digest"], language=None)

    st.subheader("Recorded task activity")
    st.caption("Collected from real workers and displayed after each run; this is not a live timeline. "
               "Bars show tile computation only, excluding dispatch and idle time.")
    runs = report["runs"]
    selected = st.selectbox("Recorded run", range(len(runs)),
                            format_func=lambda i: f"{LABELS[runs[i]['mode']]} · "
                            f"{runs[i]['role']} · {runs[i]['actual_workers']} workers · repeat {runs[i]['repeat']}")
    chosen = runs[selected]
    activity = [{"Worker": f"PID {r['pid']} / TID {r['thread_id']}", "Tile": r["tile"],
                 "Start": (r["start_ns"] - chosen["origin_ns"]) / 1e9,
                 "End": (r["end_ns"] - chosen["origin_ns"]) / 1e9}
                for r in chosen["records"]]
    timeline = alt.Chart(alt.Data(values=activity)).mark_bar().encode(
        x=alt.X("Start:Q", title="Seconds since engine start", scale=alt.Scale(zero=True)),
        x2="End:Q", y=alt.Y("Worker:N", title=None), color=alt.Color("Worker:N", legend=None),
        tooltip=["Worker:N", "Tile:Q", alt.Tooltip("Start:Q", format=".5f"),
                 alt.Tooltip("End:Q", format=".5f")],
    ).properties(height=max(100, 35 * chosen["observed_workers"]))
    st.altair_chart(timeline, width="stretch")
    st.caption(f"Resolved pool width: {chosen['actual_workers']} · observed active workers: "
               f"{chosen['observed_workers']} · backend: {chosen['backend']} · "
               f"actual GIL before/after: {chosen['before']['gil_enabled']}/{chosen['after']['gil_enabled']}")
    with st.expander("Hardware, build and methodology"):
        st.json(report["hardware"])
        st.code(report["python_build"], language=None)
        st.markdown("All cases use the **same free-threaded build**, including the GIL-on controls. "
                    "The included unchanged AGILAB pool engine dispatches and reduces fixed three-row tiles, "
                    "interleaved by bit-reversal order. GIL-off uses AGILAB’s automatic thread selection; "
                    "process cases explicitly use spawn. Build capability and actual GIL state are checked "
                    "before and after execution, and the GIL state is checked in each task. "
                    "End-to-end time includes child startup, imports, dispatch, computation, reduction, "
                    "checksum and result transfer. Engine time covers AGILAB run_works including pool startup "
                    "and image reduction. Each run uses a fresh pool, with no warmup or cached timings. "
                    "Mode and width order rotate between repeats. The lock serializes this app’s visitors; "
                    "unrelated system workloads may still affect results. CPU limits are rounded down "
                    "and capped at eight; fractional quotas below one still need one worker. "
                    "This tests the included engine only, not compatibility of the entire AGILAB dependency stack.")
        st.dataframe([{k: r[k] for k in ("mode", "role", "repeat", "actual_workers", "observed_workers",
                                         "backend", "wall_seconds", "engine_seconds", "digest")}
                      for r in runs], width="stretch", hide_index=True)
    st.download_button("Download JSON evidence", json.dumps(report, indent=2, allow_nan=False),
                       file_name="free-threading-evidence.json", mime="application/json", width="stretch")
else:
    st.info("Ready when you are. The preview is deterministic; no timed benchmark has run yet.")

st.caption("Source: original AGILAB notebook created September 19, 2026 · BSD-3-Clause. "
           "[Python free-threading documentation](https://docs.python.org/3.14/howto/free-threading-python.html)")
