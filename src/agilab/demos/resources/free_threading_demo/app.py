"""Free-threading Mandelbrot lab – Streamlit application."""

import hashlib
import json
import time
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from free_threading_core import reference_image, image_digest
from benchmark import effective_cpus, run_benchmark


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_signature(params: dict) -> str:
    """Deterministic signature from a committed parameter dict."""
    canonical = json.dumps(params, sort_keys=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _compute_image_digest(counts: np.ndarray) -> str:
    """SHA-256 digest using the core image_digest over flat pixel values."""
    return image_digest([int(v) for v in counts.ravel()])


def _counts_to_rgb(counts: np.ndarray, max_iter: int) -> np.ndarray:
    """Map iteration counts to a uint8 RGB array using a simple viridis-like ramp."""
    h, w = counts.shape
    norm = counts.astype(np.float64) / max(max_iter, 1)
    # Simple 3-stop gradient: dark blue -> cyan -> yellow
    r = np.clip(norm * 1.8, 0, 1) * 255
    g = np.clip(norm * 1.2, 0, 1) * 255
    b = np.clip(1.0 - norm * 0.6, 0, 1) * 255
    rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
    return rgb


def _render_cpu_quota() -> None:
    """Always-visible CPU quota report."""
    caps = effective_cpus()
    count = caps["effective_cpus"]
    st.subheader("CPU quota")
    if count <= 1:
        st.warning(
            f"Only {count} CPU available. Parallel scaling is unavailable; "
            "a single-worker test is still possible but no speedup is expected."
        )
    else:
        st.success(f"{count} CPUs available for parallel work.")
    st.caption(
        "Worker count is capped at min(8, effective CPUs). "
        "No speedup guarantee – actual scaling depends on workload granularity."
    )


# ---------------------------------------------------------------------------
# Explore tab
# ---------------------------------------------------------------------------

@st.cache_data
def _cached_reference_image(width: int, height: int, iterations: int) -> np.ndarray:
    """Compute and cache the Mandelbrot reference image."""
    flat = reference_image(width, height, iterations)
    return np.asarray(flat, dtype=np.int64).reshape(height, width)


def _render_explore() -> None:
    max_workers = min(8, effective_cpus()["effective_cpus"])
    default_workers = min(2, max_workers)

    with st.form("threading_controls"):
        width = st.slider("Width", 2, 384, 96, step=2)
        height = st.slider("Height", 2, 256, 64, step=2)
        iterations = st.slider("Iterations", 1, 300, 100, step=1)
        if max_workers <= 1:
            workers = st.number_input("Workers", min_value=1, max_value=1, value=1, disabled=True)
            st.caption("Only 1 CPU available; workers fixed at 1.")
        else:
            workers = st.slider("Workers", 1, max_workers, default_workers, step=1)
        repeats = st.slider("Repeats", 1, 3, 1, step=1)
        submitted = st.form_submit_button("Run analysis")

    if submitted:
        params = {
            "width": int(width),
            "height": int(height),
            "iterations": int(iterations),
            "workers": int(workers),
            "repeats": int(repeats),
        }
        signature = _compute_signature(params)

        # If the committed analysis changes, clear stale benchmark
        prev_sig = st.session_state.get("analysis_signature")
        if prev_sig is not None and prev_sig != signature:
            st.session_state.pop("benchmark_result", None)
            st.session_state.pop("benchmark_signature", None)

        st.session_state["analysis"] = params
        st.session_state["analysis_signature"] = signature

    # Render preview (always available, even before first submit)
    preview_w = st.session_state.get("analysis", {}).get("width", 96)
    preview_h = st.session_state.get("analysis", {}).get("height", 64)
    preview_iter = st.session_state.get("analysis", {}).get("iterations", 100)

    counts = _cached_reference_image(preview_w, preview_h, preview_iter)
    rgb = _counts_to_rgb(counts, preview_iter)

    st.subheader("Preview")
    st.caption(
        f"Width={preview_w}  Height={preview_h}  Iterations={preview_iter}"
    )
    st.image(rgb, width="stretch")

    # Committed analysis results – only after submission
    if "analysis" in st.session_state:
        analysis = st.session_state["analysis"]
        a_w = analysis["width"]
        a_h = analysis["height"]
        a_iter = analysis["iterations"]

        a_counts = _cached_reference_image(a_w, a_h, a_iter)
        pixels = a_w * a_h
        mean_esc = float(np.mean(a_counts))
        interior = int(np.sum(a_counts == a_iter))
        digest = _compute_image_digest(a_counts)

        st.subheader("Analysis results")
        c1, c2, c3 = st.columns(3)
        c1.metric("Pixels", f"{pixels:,}")
        c2.metric("Mean escape iterations", f"{mean_esc:.2f}")
        c3.metric("Interior pixels", f"{interior:,}")

        st.caption(f"Image digest: `{digest[:32]}…`")

        # Data table
        table = pd.DataFrame(
            {
                "metric": ["pixels", "mean_escape_iterations", "interior_pixels", "image_digest"],
                "value": [f"{pixels:,}", f"{mean_esc:.4f}", f"{interior:,}", digest[:32] + "…"],
            }
        )
        st.dataframe(table, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Benchmark tab
# ---------------------------------------------------------------------------

def _render_benchmark() -> None:
    analysis = st.session_state.get("analysis")
    analysis_sig = st.session_state.get("analysis_signature")

    if analysis is None:
        st.info("Run an analysis in the Explore tab first to enable benchmarking.")
        return

    st.subheader("Benchmark")
    st.caption(
        f"Committed parameters: {analysis['width']}×{analysis['height']}, "
        f"{analysis['iterations']} iters, {analysis['workers']} workers, "
        f"{analysis['repeats']} repeats"
    )

    # Benchmark button (outside form)
    if st.button("Run benchmark", type="primary"):
        _execute_benchmark(analysis, analysis_sig)

    # Display stored benchmark result
    result = st.session_state.get("benchmark_result")
    result_sig = st.session_state.get("benchmark_signature")
    if result is not None and result_sig == analysis_sig:
        _display_benchmark_result(result)
    elif result is not None:
        st.caption("Benchmark result is stale (parameters changed). Re-run to refresh.")


def _execute_benchmark(analysis: dict, signature: str) -> None:
    """Execute the benchmark with progress and error handling."""
    w = analysis["width"]
    h = analysis["height"]
    iters = analysis["iterations"]
    workers = analysis["workers"]
    repeats = analysis["repeats"]

    progress_bar = st.progress(0.0, text="Starting benchmark…")

    def _progress(done: int, total: int, label: str) -> None:
        frac = done / max(total, 1)
        progress_bar.progress(frac, text=f"{label}: {done}/{total}")

    try:
        with st.spinner("Running benchmark…"):
            result = run_benchmark(
                width=w,
                height=h,
                iterations=iters,
                workers=workers,
                repeats=repeats,
                progress=_progress,
            )
    except Exception as exc:
        progress_bar.empty()
        st.error(f"Benchmark failed: {exc}")
        return

    progress_bar.progress(1.0, text="Complete")
    st.session_state["benchmark_result"] = result
    st.session_state["benchmark_signature"] = signature


def _display_benchmark_result(result: dict) -> None:
    """Render the full benchmark result."""
    summary = result["summary"]
    runs = result["runs"]
    hardware = result["hardware"]
    python_build = result["python_build"]
    same_work_verified = result["same_work_verified"]
    scaling_available = result["scaling_available"]

    # Build version and hardware
    st.subheader("Environment")
    st.write(f"**Python build:** {python_build}")
    st.write(f"**Hardware:** {hardware}")
    st.write(f"**Same work verified:** {same_work_verified}")
    st.write(f"**Scaling available:** {scaling_available}")

    # GIL before/after table
    st.subheader("GIL state")
    gil_rows = []
    for r in runs:
        before = r.get("before", {})
        after = r.get("after", {})
        gil_rows.append(
            {
                "mode": r.get("mode", ""),
                "role": r.get("role", ""),
                "repeat": r.get("repeat", ""),
                "gil_before": str(before.get("gil_enabled", "")),
                "gil_after": str(after.get("gil_enabled", "")),
                "free_threaded_build": str(before.get("free_threaded_build", "")),
            }
        )
    gil_df = pd.DataFrame(gil_rows)
    st.dataframe(gil_df, width="stretch", hide_index=True)

    # 6 summary rows
    st.subheader("Summary")
    summary_rows = []
    for s in summary:
        summary_rows.append(
            {
                "mode": s.get("mode", ""),
                "role": s.get("role", ""),
                "requested_workers": str(s.get("workers", "")),
                "resolved_workers": str(s.get("pool_width", "")),
                "observed_workers": str(s.get("actual_workers", "")),
                "observed_worker_counts": str(s.get("observed_worker_counts", "")),
                "median_wall_s": f"{s.get('wall_seconds', 0):.6f}",
                "median_engine_s": f"{s.get('engine_seconds', 0):.6f}",
                "speedup": f"{s.get('speedup', 1.0):.4f}",
                "engine_speedup": f"{s.get('engine_speedup', 1.0):.4f}",
            }
        )
    summary_df = pd.DataFrame(summary_rows)
    st.dataframe(summary_df, width="stretch", hide_index=True)

    # Speedup chart
    if len(summary) >= 2:
        chart_data = pd.DataFrame(
            {
                "label": [f"{s['mode']}/{s['role']}" for s in summary],
                "speedup": [s.get("speedup", 1.0) for s in summary],
                "engine_speedup": [s.get("engine_speedup", 1.0) for s in summary],
            }
        )
        melted = chart_data.melt(
            id_vars="label", var_name="series", value_name="value"
        )
        chart = (
            alt.Chart(melted)
            .mark_bar()
            .encode(
                x=alt.X("label:N", title="Mode / Role"),
                xOffset="series:N",
                y=alt.Y("value:Q", title="Speedup"),
                color=alt.Color("series:N", title="Metric"),
                tooltip=["label", "series", "value"],
            )
            .properties(height=220)
        )
        st.altair_chart(chart, width="stretch")


# ---------------------------------------------------------------------------
# Inspect tab
# ---------------------------------------------------------------------------

def _render_inspect() -> None:
    result = st.session_state.get("benchmark_result")
    if result is None:
        st.info("No benchmark result available. Run a benchmark first.")
        return

    runs = result["runs"]
    digest = result["digest"]
    same_work_verified = result["same_work_verified"]

    st.subheader("Tile coverage / records")

    # Build a compact record table (omit large counts)
    record_rows = []
    for r in runs:
        records = r.get("records", [])
        for rec in records:
            record_rows.append(
                {
                    "mode": r.get("mode", ""),
                    "role": r.get("role", ""),
                    "repeat": r.get("repeat", ""),
                    "row_start": rec.get("row_start", ""),
                    "row_stop": rec.get("row_stop", ""),
                    "pid": rec.get("pid", ""),
                    "thread_id": rec.get("thread_id", ""),
                    "gil_before": rec.get("gil_before", ""),
                    "gil_after": rec.get("gil_after", ""),
                    "runtime_before": rec.get("runtime_before", ""),
                    "runtime_after": rec.get("runtime_after", ""),
                }
            )

    if record_rows:
        rec_df = pd.DataFrame(record_rows)
        st.dataframe(rec_df, width="stretch", hide_index=True)
        st.caption(f"Total records: {len(record_rows)}")
    else:
        st.caption("No records available.")

    # Runtime states
    st.subheader("Runtime states")
    runtime_rows = []
    for r in runs:
        before = r.get("before", {})
        after = r.get("after", {})
        records = r.get("records", [])
        for rec in records:
            runtime_rows.append(
                {
                    "mode": r.get("mode", ""),
                    "role": r.get("role", ""),
                    "repeat": r.get("repeat", ""),
                    "runtime_before": str(rec.get("runtime_before", "")),
                    "runtime_after": str(rec.get("runtime_after", "")),
                    "free_threaded_build": str(before.get("free_threaded_build", "")),
                }
            )
    if runtime_rows:
        rt_df = pd.DataFrame(runtime_rows)
        st.dataframe(rt_df, width="stretch", hide_index=True)

    # Digest
    st.subheader("Digest")
    st.code(digest, language="text")
    st.write(f"Same work verified: {same_work_verified}")

    # Optional full JSON
    with st.expander("Full JSON"):
        full_json = json.dumps(result, indent=2, allow_nan=False, default=str)
        st.code(full_json, language="json")

    # Downloads
    st.subheader("Downloads")
    json_bytes = json.dumps(result, indent=2, allow_nan=False, default=str).encode("utf-8")
    st.download_button(
        "Download result JSON",
        data=json_bytes,
        file_name="benchmark_result.json",
        mime="application/json",
    )

    # CSV summary
    summary = result.get("summary", [])
    if summary:
        csv_df = pd.DataFrame(summary)
        csv_bytes = csv_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download summary CSV",
            data=csv_bytes,
            file_name="benchmark_summary.csv",
            mime="text/csv",
        )


# ---------------------------------------------------------------------------
# Reproduce tab
# ---------------------------------------------------------------------------

def _render_reproduce() -> None:
    st.subheader("Reproduction notes")

    st.markdown(
        """
**Source:** Original AGILAB benchmark (BSD-3-Clause license).

**Scope:** The AGILAB pool is used unchanged. The workload is a stdlib pure-Python
Mandelbrot computation running on the same free-threaded Python 3.14t interpreter.

**Three modes:**
- `gil_on_threads` – threads with GIL enabled
- `gil_off_threads` – threads with GIL disabled (free-threaded build)
- `gil_on_processes` – spawned processes with GIL enabled

Each mode runs a 1-worker baseline and an N-worker parallel configuration on the
same interpreter and work image.

**Caveats:**
- Actual worker count may be lower than requested capacity (pool saturation /
  task granularity). All tiles are always required; no tasks are dropped.
- CPU quotas apply; no speedup is guaranteed.
- This does **not** certify the whole AGILAB stack – only the specific
  free-threaded Python workload described here.
"""
    )

    st.caption(
        "For full reproduction, use the same free-threaded Python 3.14t build "
        "and the AGILAB pool with identical parameters."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("Free-threading lab")
    st.caption(
        "Explore Mandelbrot set rendering under Python's free-threaded build. "
        "Observe GIL state transitions, parallel scaling, and engine-level timing."
    )

    # CPU quota (always visible)
    _render_cpu_quota()

    # Tabs in stable order
    tab_explore, tab_benchmark, tab_inspect, tab_reproduce = st.tabs(
        ["Explore", "Benchmark", "Inspect", "Reproduce"]
    )

    with tab_explore:
        _render_explore()

    with tab_benchmark:
        _render_benchmark()

    with tab_inspect:
        _render_inspect()

    with tab_reproduce:
        _render_reproduce()


if __name__ == "__main__":
    main()