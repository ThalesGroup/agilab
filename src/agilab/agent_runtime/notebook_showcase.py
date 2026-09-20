"""Public, fixed-code showcase of the app produced by a real Tokki agent run."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType
import zipfile

import streamlit as st

from agilab.agent_runtime.notebook_demo_evidence import render_build_evidence
from agilab.agent_runtime.notebook_app_runtime import APP_EXECUTION_LOCK as _APP_LOCK

DEMO_ROOT = Path(__file__).parents[1] / "resources" / "notebook_agent_demo"
LOCAL_DEMO_ROOT = DEMO_ROOT.with_name("notebook_agent_local_demo")
VERIFIED_FILES = frozenset({"app.py", "models.py", "solution.ipynb", "lab_stages.toml"})


def _read_verified_bundle(demo_root: Path | None = None) -> tuple[dict, dict[str, bytes]]:
    demo_root = DEMO_ROOT if demo_root is None else demo_root
    if demo_root.is_symlink() or (demo_root / "result.json").is_symlink():
        raise ValueError("Iris demo directory and receipt must not be symlinks")
    receipt = (demo_root / "result.json").read_bytes()
    report = json.loads(receipt)
    if (not isinstance(report, dict) or report.get("status") != "passed"
            or report.get("schema") != "agilab.notebook_agent.public_demo.v1"):
        raise ValueError("Iris demo has no supported passed receipt")
    verification = report.get("verification")
    if (not isinstance(verification, dict) or verification.get("status") != "passed"
            or not isinstance(verification.get("checks"), list) or not verification["checks"]
            or any(not isinstance(check, str) or not check.strip() for check in verification["checks"])):
        raise ValueError("Iris demo verification is incomplete")
    scores = verification.get("scores")
    if (not isinstance(scores, list) or not scores
            or any(not isinstance(row, dict) or not isinstance(row.get("model"), str)
                   or not row["model"].strip() for row in scores)):
        raise ValueError("Iris demo model results are missing")
    source = report.get("source")
    if (not isinstance(source, dict) or not isinstance(source.get("url"), str)
            or not source["url"].strip() or not isinstance(report.get("run_id"), str)
            or not report["run_id"].strip()):
        raise ValueError("Iris demo source or run metadata is missing")
    seconds, stages = report.get("seconds"), report.get("workflow_stages")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds <= 0
            or isinstance(stages, bool) or not isinstance(stages, int) or stages < 1):
        raise ValueError("Iris demo build timing or stages are invalid")
    files = report.get("files")
    if not isinstance(files, dict) or set(files) != VERIFIED_FILES:
        raise ValueError("Iris demo artifact manifest is incomplete or unexpected")
    payload = {"result.json": receipt}
    for name, expected in sorted(files.items()):
        path = demo_root / name
        if path.is_symlink():
            raise ValueError("Invalid demo artifact path")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"Invalid demo artifact hash: {name}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Demo artifact changed since verification: {name}")
        payload[name] = data
    license_path = demo_root / "LICENSE"
    if license_path.is_symlink():
        raise ValueError("Iris demo license must not be a symlink")
    payload["LICENSE"] = license_path.read_bytes()
    for path in demo_root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Iris demo contains a symlink")
        relative = path.relative_to(demo_root)
        if path.is_file() and relative.as_posix() not in payload:
            if "__pycache__" not in relative.parts or path.suffix != ".pyc":
                raise ValueError(f"Unverified Iris demo artifact: {relative}")
    return report, payload


def load_report(demo_root: Path | None = None) -> dict:
    return _read_verified_bundle(demo_root)[0]


def _zip_bundle(payload: dict[str, bytes]) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(name, data)
    return content.getvalue()


def download_bundle(demo_root: Path | None = None) -> bytes:
    return _zip_bundle(_read_verified_bundle(demo_root)[1])


def _run_verified_app(payload: dict[str, bytes], *, demo_root: Path | None = None) -> None:
    demo_root = DEMO_ROOT if demo_root is None else demo_root
    with _APP_LOCK:
        previous = sys.modules.pop("models", None)
        module = ModuleType("models")
        module.__file__ = str(demo_root / "models.py")
        sys.modules["models"] = module
        try:
            exec(compile(payload["models.py"], module.__file__, "exec"), module.__dict__)
            app_path = str(demo_root / "app.py")
            exec(compile(payload["app.py"], app_path, "exec"),
                 {"__name__": "__main__", "__file__": app_path})
        finally:
            sys.modules.pop("models", None)
            if previous is not None:
                sys.modules["models"] = previous


def render() -> None:
    selected = st.segmented_control(
        "Choose a demo", ["iris", "iris_local", "forecast", "text", "threading", "milp"], default="iris", required=True,
        key="demo", bind="query-params",
    )
    if selected == "milp":
        try:
            from agilab.agent_runtime.milp_energy_showcase import render as render_milp
        except ModuleNotFoundError as exc:
            if exc.name != "agilab.agent_runtime.milp_energy_showcase":
                raise
            st.error("MILP energy lab unavailable in this distribution.")
            return
        render_milp()
        return
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
    if selected not in {"iris", "iris_local"}:
        st.error("Choose one of the available demos.")
        return
    demo_root = LOCAL_DEMO_ROOT if selected == "iris_local" else DEMO_ROOT
    try:
        report, payload = _read_verified_bundle(demo_root)
    except (OSError, ValueError, TypeError) as exc:
        st.error(f"Iris demo unavailable: {exc}")
        return
    st.caption("TOKKI × AGILAB · NOTEBOOK → WORKING APP")
    render_build_evidence(report, extra_metrics=(
        ("Models checked", len({row["model"] for row in report["verification"]["scores"]})),
    ))
    st.caption(
        "Build model: Qwen 3.8 27B (4-bit, local MLX)."
        if selected == "iris_local" else "Build model: GPT-6 Astra (OpenAI)."
    )
    if selected == "iris_local":
        st.write(
            "Local Qwen generated and repaired this app. "
            "A coordinating assistant reviewed the outputs; AGILAB imported the workflow."
        )
    else:
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
        st.download_button("Download the generated app and workflow", _zip_bundle(payload),
                           f"tokki-agilab-{selected}-decision-lab.zip", "application/zip")
        if st.button("Run model and app checks", icon=":material/fact_check:"):
            with st.spinner("Running model, notebook and interface checks…"):
                verifier = Path(__file__).with_name("notebook_verifier.py")
                try:
                    checked = subprocess.run([sys.executable, str(verifier)], cwd=demo_root,
                                             text=True, capture_output=True, timeout=180)
                    result = json.loads(checked.stdout.strip().splitlines()[-1])
                    if checked.returncode or result.get("status") != "passed":
                        st.error(result.get("error", "Verification failed"))
                    else:
                        st.success("Model, notebook and interface checks passed in this environment.")
                except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
                    st.error(f"Verification could not complete: {type(exc).__name__}")
    st.divider()
    _run_verified_app(payload, demo_root=demo_root)


if __name__ == "__main__":
    render()
