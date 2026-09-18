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
    report = load_report()
    st.caption("TOKKI × AGILAB · NOTEBOOK → WORKING APP")
    st.title("Built by an autonomous agent")
    st.write(
        "One request turned Géron's decision-tree notebook into the interactive app below. "
        "Tokki coordinated the agent and verification; AGILAB imported the resulting workflow."
    )
    st.caption(
        "This public Space runs the completed app. New autonomous builds run in a local "
        "Tokki environment with your configured provider."
    )
    with st.container(horizontal=True):
        st.metric("Autonomous build", f"{report['seconds'] / 60:.2f} min")
        st.metric("Models checked", len({row['model'] for row in report['verification']['scores']}))
        st.metric("AGILAB workflow stages", report["workflow_stages"])
    with st.expander("Build from your own notebook", icon=":material/rocket_launch:"):
        st.write("Run the builder on your computer with your own Tokki installation and configured Codex provider. Start with a self-contained Python notebook using data and dependencies available locally.")
        st.markdown("1. Set up your licensed [Tokki installation](https://github.com/jpmorard/tokki-public/blob/main/RELEASES.md) and provider.\n2. Install the AGILAB builder with [uv](https://docs.astral.sh/uv/getting-started/installation/).\n3. Open the local interface and choose **Local notebook** or **Pinned GitHub notebook**.")
        st.code('uv tool install "agilab[notebook-agent] @ git+https://github.com/ThalesGroup/agilab.git"\nagilab-notebook-demo --ui', language="bash")
        st.caption("Your notebook and provider credentials stay out of this public Space. The local agent reads your notebook through your provider and executes generated Python on your computer. Checks establish execution and interface behavior; review scientific conclusions yourself.")
        st.write("After your first successful build, the local app offers a completion receipt you can voluntarily report on GitHub. It contains no notebook or credentials. Nothing is uploaded automatically; a public report is associated with your GitHub account.")
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
