"""Packaged local demo: one request, a notebook, a verified application."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from queue import Empty, Queue
import re
from threading import Thread

from agi_web import python_ui as st

from agilab.agent_runtime.notebook_agent import (
    DEFAULT_REQUEST,
    GENERIC_REQUEST,
    SOURCE_URL,
    build,
    create_run,
    digest,
    read_events,
    recover_build,
)
from agilab.agent_runtime.notebook_adoption import github_report_url
from agilab.demos.notebook_app_runtime import run_app
from agilab.ui.page_bootstrap import configure_page_config

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--output", default=str(Path.home() / "agilab-demo-runs"))
parser.add_argument("--tokki", default="tokki")
parser.add_argument("--timeout", type=int, default=1200)
parser.add_argument("--request")
parser.add_argument("--notebook")
parser.add_argument("--notebook-url")
parser.add_argument("--resume", type=Path)
defaults, _ = parser.parse_known_args()


def _run_operation(target, root, arguments, results):
    """Return worker outcomes without accessing the UI's session state."""
    try:
        report = target(root, **arguments)
        if not isinstance(report, dict) or report.get("status") not in {
            "passed",
            "failed",
        }:
            raise ValueError("The operation returned no terminal result")
    except Exception as exc:
        report = {
            "status": "failed",
            "failed_phase": "ui_worker",
            "error": str(exc) or type(exc).__name__,
            "recovery": {
                "eligible": False,
                "reason": "The operation did not complete. Review its saved execution evidence.",
            },
        }
    results.put(report)


def _collect_operation_result():
    results = st.session_state.get("run_result_queue")
    if results is None:
        return False
    try:
        report = results.get_nowait()
    except Empty:
        thread = st.session_state.get("build_thread")
        if thread is None or thread.is_alive():
            return False
        # The worker may publish between the first queue read and its exit.
        try:
            report = results.get_nowait()
        except Empty:
            report = {
                "status": "failed",
                "failed_phase": "ui_worker",
                "error": "The operation stopped without a terminal result. Review its saved execution evidence.",
                "recovery": {
                    "eligible": False,
                    "reason": "Operation termination is unverified.",
                },
            }
    st.session_state.run_operation_result = report
    st.session_state.run_result_queue = None
    st.session_state.build_thread = None
    return True


def _start_operation(root, operation, target, **arguments):
    results = Queue(maxsize=1)
    thread = Thread(
        target=_run_operation, args=(target, root, arguments, results), daemon=True
    )
    st.session_state.run_root = str(root)
    st.session_state.run_operation_root = str(root)
    st.session_state.run_operation = operation
    st.session_state.run_operation_report_sha256 = _report_identity(root)
    st.session_state.run_operation_result = None
    st.session_state.run_result_queue = results
    st.session_state.show_generated = False
    st.session_state.build_thread = thread
    thread.start()


def _report_identity(root):
    try:
        return digest(root / "result.json")
    except FileNotFoundError:
        return None


def _operation_result(root):
    if st.session_state.get("run_operation_root") == str(root):
        if st.session_state.get(
            "run_operation_result"
        ) is not None and _report_identity(root) != st.session_state.get(
            "run_operation_report_sha256"
        ):
            st.session_state.run_operation_result = None
        return st.session_state.get("run_operation_result")
    return None


def _operation_busy(root=None):
    thread = st.session_state.get("build_thread")
    if thread is not None and thread.is_alive():
        return True
    return bool(
        root is not None
        and _operation_result(root) is None
        and read_events(root)
        and not (root / "result.json").exists()
    )


configure_page_config(st, page_title="Tokki × AGILAB · Notebook to app")
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

if "run_root" not in st.session_state and defaults.resume is not None:
    candidate = defaults.resume.expanduser().absolute()
    if candidate.is_dir() and not candidate.is_symlink():
        st.session_state.run_root = str(candidate)
    else:
        st.error("The saved run directory is missing or is a symbolic link.")
run_query = st.query_params.get("run", "")
if "run_root" not in st.session_state and re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", run_query):
    candidate = Path(output).expanduser().absolute() / run_query
    if candidate.is_dir() and not candidate.is_symlink():
        st.session_state.run_root = str(candidate)
_collect_operation_result()
current_root = (
    Path(st.session_state.run_root) if "run_root" in st.session_state else None
)
busy = _operation_busy(current_root)
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
    _start_operation(
        root,
        "build",
        build,
        intent=intent,
        tokki=tokki,
        timeout=int(timeout),
        notebook=Path(notebook_path).expanduser() if notebook_path else None,
        notebook_url=notebook_url or None,
    )
    st.rerun()


@st.fragment(run_every="2s")
def live_run():
    if _collect_operation_result():
        # A full rerender also updates controls outside this polling fragment.
        st.rerun()
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
    saved_result = json.loads(result_file.read_text()) if result_file.exists() else None
    result = _operation_result(root)
    if result is None:
        result = saved_result
    running = _operation_busy(root)
    state = (
        "running"
        if running
        else "error"
        if result and result["status"] == "failed"
        else "complete"
        if result
        else "running"
    )
    message = (
        "Retrying verification using the saved generated files"
        if running and st.session_state.get("run_operation") == "recovery"
        else last["message"]
    )
    panel = st.status(message, state=state, expanded=running or not bool(result))
    with panel:
        for item in events:
            st.write(f"{item['time'][11:19]} · {item['message']}")
        project = Path(result["project"]) if result and result.get("project") else next(root.glob("*_project"), root / "decision_lab_project")
        generated = [p.name for p in project.glob("*") if p.is_file()]
        if generated:
            st.caption("Files created: " + ", ".join(sorted(generated)))
    panel.update(state=state)
    st.caption(f"Run evidence: {root}")
    if not running and result and result["status"] == "passed":
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
    elif not running and result:
        st.error(result["error"])
        if result.get("failed_phase"):
            st.caption("Stopped during: " + result["failed_phase"].replace("_", " "))
        with st.expander("Execution evidence"):
            for name in ("agent/stderr.txt", "verification.log"):
                path = root / name
                if path.is_file():
                    st.code(path.read_text(errors="replace")[-6000:], language="text")
    if result and result["status"] == "failed":
        recovery_result = (
            saved_result
            if saved_result and saved_result["status"] == "failed"
            else result
        )
        recovery = recovery_result.get("recovery", {})
        eligible = recovery.get("eligible") is True
        if eligible:
            st.caption(
                "Retry verification uses the saved generated files without another provider call."
            )
        elif not running:
            st.caption(
                "Verification retry unavailable: "
                + recovery.get(
                    "reason", "No verified provider checkpoint is available."
                )
            )
        if st.button(
            "Retry verification",
            disabled=running or not eligible,
            key="retry_verification",
        ):
            _start_operation(root, "recovery", recover_build)
            st.rerun()


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
