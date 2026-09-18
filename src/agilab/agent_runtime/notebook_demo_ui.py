"""Packaged local demo: one request, a notebook, a verified application."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from threading import Thread

import streamlit as st

from agilab.agent_runtime.notebook_agent import (
    DEFAULT_REQUEST, GENERIC_REQUEST, SOURCE_URL, build, create_run, digest, read_events,
)
from agilab.agent_runtime.notebook_adoption import github_report_url
from agilab.agent_runtime.notebook_app_runtime import run_app

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--output", default=str(Path.home() / "agilab-demo-runs"))
parser.add_argument("--tokki", default="tokki")
parser.add_argument("--timeout", type=int, default=1200)
parser.add_argument("--request")
parser.add_argument("--notebook")
parser.add_argument("--notebook-url")
defaults, _ = parser.parse_known_args()

st.set_page_config(page_title="Tokki × AGILAB · Notebook to app", page_icon=":material/rocket_launch:", layout="wide")
st.caption("TOKKI × AGILAB  /  LIVE BUILD")
st.title("A notebook goes in. A working app comes out.")
st.write("Give the agent an objective. Tokki coordinates the build and verification; AGILAB turns the result into a reusable workflow.")

with st.sidebar:
    st.subheader("The starting point")
    source_choice = st.radio("Notebook source", ["Géron demo", "Local notebook", "Pinned GitHub notebook"],
                             index=1 if defaults.notebook else 2 if defaults.notebook_url else 0)
    notebook_path = notebook_url = None
    upload = None
    if source_choice == "Géron demo":
        st.markdown(f"[Hands-On Machine Learning · Decision trees]({SOURCE_URL})")
        st.caption("Aurélien Géron · Apache-2.0 · handson-ml3 has 14,163 GitHub stars, checked 18 Sep 2026.")
        st.caption("The source is pinned to a commit. This demo uses the Iris example and runs on CPU.")
    elif source_choice == "Local notebook":
        upload = st.file_uploader("Your notebook", type=["ipynb"])
        notebook_path = st.text_input("Or use a local notebook path", defaults.notebook or "")
    else:
        notebook_url = st.text_input("GitHub notebook URL", defaults.notebook_url or "",
                                     placeholder="https://github.com/owner/repo/blob/<commit SHA>/example.ipynb")
        st.caption("Use a full 40-character commit SHA so the source stays reproducible.")
    with st.expander("Run settings"):
        output = st.text_input("Run folder", defaults.output)
        tokki = st.text_input("Tokki executable", defaults.tokki)
        timeout = st.number_input("Time limit (seconds)", 60, 3600, defaults.timeout, 60)
    st.caption("Uses your configured Codex provider through Tokki. The agent can read your selected notebook. Starting a build executes generated Python locally and may consume provider quota.")

run_query = st.query_params.get("run", "")
if "run_root" not in st.session_state and re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", run_query):
    candidate = Path(output).expanduser().resolve() / run_query
    if candidate.is_dir() and not candidate.is_symlink():
        st.session_state.run_root = str(candidate)
thread = st.session_state.get("build_thread")
busy = thread is not None and thread.is_alive()
if "run_root" in st.session_state:
    current_root = Path(st.session_state.run_root)
    busy = busy or (bool(read_events(current_root)) and not (current_root / "result.json").exists())
custom = source_choice != "Géron demo"
if custom:
    st.info("Start with a self-contained Python notebook whose data and dependencies are available locally. Checks cover execution and interface behavior; review the scientific conclusions yourself.")
    acknowledged = st.checkbox("I trust this notebook and agree to let my configured provider read it and run generated code locally.")
else:
    acknowledged = True
intent = st.text_area("What should the agent build?", defaults.request or (GENERIC_REQUEST if custom else DEFAULT_REQUEST),
                      height=115, disabled=busy, key=f"objective_{source_choice}")
source_ready = not custom or bool(upload or notebook_path or notebook_url)
if upload and upload.size > 16 * 1024 * 1024:
    st.error("Choose a notebook smaller than 16 MiB.")
    source_ready = False
if st.button("Build my app", type="primary", icon=":material/rocket_launch:", disabled=busy or not intent.strip() or not source_ready or not acknowledged):
    root = create_run(Path(output))
    if upload:
        saved = root / "input.ipynb"
        saved.write_bytes(upload.getvalue())
        notebook_path = str(saved)
    thread = Thread(target=build, kwargs={"root": root, "intent": intent, "tokki": tokki,
                                        "timeout": int(timeout),
                                        "notebook": Path(notebook_path).expanduser() if notebook_path else None,
                                        "notebook_url": notebook_url or None}, daemon=True)
    st.session_state.run_root = str(root)
    st.session_state.show_generated = False
    st.session_state.build_thread = thread
    thread.start()
    st.rerun()


@st.fragment(run_every="2s")
def live_run():
    if "run_root" not in st.session_state:
        with st.container(border=True):
            st.subheader("One action. Four observable steps.")
            st.write("Import the notebook → build the app → run and repair → verify the result")
            st.caption("No prerecorded outputs. A successful result requires fresh model tests and a working interface.")
        return
    root = Path(st.session_state.run_root)
    events = read_events(root)
    last = events[-1] if events else {"phase": "starting", "message": "Starting the agent"}
    result_file = root / "result.json"
    result = json.loads(result_file.read_text()) if result_file.exists() else None
    state = "error" if result and result["status"] == "failed" else "complete" if result else "running"
    panel = st.status(last["message"], state=state, expanded=not bool(result))
    with panel:
        for item in events:
            st.write(f"{item['time'][11:19]} · {item['message']}")
        project = Path(result["project"]) if result and result.get("project") else next(root.glob("*_project"), root / "decision_lab_project")
        generated = [p.name for p in project.glob("*") if p.is_file()]
        if generated:
            st.caption("Files created: " + ", ".join(sorted(generated)))
    panel.update(state=state)
    st.caption(f"Run evidence: {root}")
    if result and result["status"] == "passed":
        with st.container(horizontal=True):
            st.metric("Build time", f"{result['seconds']:.0f} s")
            st.metric("Workflow stages", result["workflow_stages"])
            st.metric("Acceptance checks", len(result["verification"]["checks"]))
        if result["verification"].get("scores"):
            st.dataframe(result["verification"]["scores"], hide_index=True)
        st.caption("Verification scope: " + result.get("verification_scope", "iris_model_acceptance").replace("_", " "))
        st.download_button("Download generated notebook", (project / "solution.ipynb").read_bytes(),
                           "solution.ipynb", "application/x-ipynb+json")
        receipt = root / "completion_receipt.json"
        if receipt.exists():
            with st.expander("Help measure first builds (optional)"):
                st.write("This receipt contains random run/workspace identifiers, build outcome, source type, duration bucket and AGILAB version. It contains no notebook, prompt, path or credentials. Nothing is sent automatically.")
                st.json(json.loads(receipt.read_text()))
                st.download_button("Download completion receipt", receipt.read_bytes(),
                                   f"{root.name}-completion.json", "application/json")
                st.link_button("Share this receipt on GitHub (public)", github_report_url(json.loads(receipt.read_text())))
                st.caption("This opens a draft issue. Posting is optional and associates the receipt with your GitHub account. Review it before submitting.")
        if st.button("Try the app", type="primary", icon=":material/play_arrow:"):
            st.session_state.show_generated = True
            st.rerun()
    elif result:
        st.error(result["error"])
        with st.expander("Execution evidence"):
            for name in ("agent/stderr.txt", "verification.log"):
                path = root / name
                if path.is_file():
                    st.code(path.read_text(errors="replace")[-6000:], language="text")


live_run()
if st.session_state.get("show_generated") and "run_root" in st.session_state:
    root = Path(st.session_state.run_root)
    result = json.loads((root / "result.json").read_text())
    project = Path(result["project"])
    if result["status"] == "passed" and all(digest(project / name) == value for name, value in result["files"].items()):
        st.divider()
        st.caption("THE GENERATED APP · Running the verified source below")
        run_app(project)
    else:
        st.error("The app changed after verification. Start a new build to verify it again.")
