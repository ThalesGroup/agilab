"""Public, fixed-code showcase of the app produced by a real Tokki agent run."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import threading
import zipfile

import streamlit as st

from agilab.agent_runtime.notebook_demo_evidence import render_build_evidence

_APP_LOCK = threading.RLock()
DEMO_ROOT = Path(__file__).parents[1] / "resources" / "notebook_agent_demo"


def load_report() -> dict:
    report = json.loads((DEMO_ROOT / "result.json").read_text())
    for name, expected in report["files"].items():
        path = DEMO_ROOT / name
        if path.parent != DEMO_ROOT or path.is_symlink():
            raise ValueError("Invalid demo artifact path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Demo artifact changed since verification: {name}")
    return report


@st.cache_data
def download_bundle() -> bytes:
    report = load_report()
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in (*report["files"], "LICENSE", "result.json"):
            archive.write(DEMO_ROOT / name, name)
    return content.getvalue()


def render() -> None:
    selected = st.segmented_control(
        "Choose a demo", ["iris", "forecast", "text", "threading"], default="iris", required=True,
        key="demo", bind="query-params",
    )
    if selected == "threading":
        try:
            from agilab.agent_runtime.free_threading_showcase import render as render_threading
        except ModuleNotFoundError as exc:
            if exc.name != "agilab.agent_runtime.free_threading_showcase":
                raise
            st.error("Free-threading demo unavailable in this distribution.")
            return
        render_threading()
        return
    if selected == "forecast":
        try:
            from agilab.agent_runtime.forecast_showcase import render as render_forecast
        except ModuleNotFoundError as exc:
            if exc.name != "agilab.agent_runtime.forecast_showcase":
                raise
            st.error("Forecast demo unavailable in this distribution.")
            return
        render_forecast()
        return
    if selected == "text":
        try:
            from agilab.agent_runtime.text_showcase import render as render_text
        except ModuleNotFoundError as exc:
            if exc.name != "agilab.agent_runtime.text_showcase":
                raise
            st.error("Text demo unavailable in this distribution.")
            return
        render_text()
        return
    if selected != "iris":
        st.error("Choose one of the available demos.")
        return
    report = load_report()
    st.caption("TOKKI × AGILAB · NOTEBOOK → WORKING APP")
    render_build_evidence(report, extra_metrics=(
        ("Models checked", len({row["model"] for row in report["verification"]["scores"]})),
    ))
    st.write(
        "One request turned Géron's decision-tree notebook into the interactive app below. "
        "Tokki coordinated the agent and verification; AGILAB imported the resulting workflow."
    )
    with st.expander("The request and the proof"):
        st.markdown(
            "> Turn the Iris decision-tree example into an interactive decision lab. "
            "Compare a decision tree, random forest and logistic regression on a held-out split. "
            "Let me change tree depth, inspect errors and classify a flower."
        )
        st.markdown(f"Source: [Aurélien Géron's notebook]({report['source']['url']}) · Apache-2.0")
        st.caption(f"Completed local run: {report['run_id']} · results below are from that run.")
        st.dataframe(report["verification"]["scores"], hide_index=True)
        st.write("Checks passed: held-out model tests, notebook execution, app startup and slider interaction.")
        st.download_button("Download the generated app and workflow", download_bundle(),
                           "tokki-agilab-decision-lab.zip", "application/zip")
        if st.button("Run model and app checks", icon=":material/fact_check:"):
            with st.spinner("Running model, notebook and interface checks…"):
                verifier = Path(__file__).with_name("notebook_verifier.py")
                try:
                    checked = subprocess.run([sys.executable, str(verifier)], cwd=DEMO_ROOT,
                                             text=True, capture_output=True, timeout=180)
                    result = json.loads(checked.stdout.strip().splitlines()[-1])
                    if checked.returncode or result.get("status") != "passed":
                        st.error(result.get("error", "Verification failed"))
                    else:
                        st.success("Model, notebook and interface checks passed in this environment.")
                except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
                    st.error(f"Verification could not complete: {type(exc).__name__}")
    st.divider()
    # The generated app imports a module named models. Serialize this short render
    # and restore import state so other AGILAB pages cannot receive that module.
    with _APP_LOCK:
        previous = sys.modules.pop("models", None)
        sys.path.insert(0, str(DEMO_ROOT))
        try:
            runpy.run_path(str(DEMO_ROOT / "app.py"), run_name="__main__")
        finally:
            sys.path.remove(str(DEMO_ROOT))
            sys.modules.pop("models", None)
            if previous is not None:
                sys.modules["models"] = previous


if __name__ == "__main__":
    render()
