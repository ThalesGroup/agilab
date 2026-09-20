"""Public forecasting showcase with a verified, self-contained artifact bundle."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
from types import ModuleType
import zipfile

import streamlit as st

from agilab.agent_runtime.notebook_demo_evidence import render_build_evidence
from agilab.agent_runtime.notebook_app_runtime import APP_EXECUTION_LOCK as _APP_LOCK
from agilab.agent_runtime.notebook_app_runtime import app_session_state

DEMO_ROOT = Path(__file__).parents[1] / "resources" / "forecast_notebook_demo"
_REQUIRED_FILES = {"app.py", "forecast_core.py", "solution.ipynb", "lab_stages.toml", "LICENSE"}
MODEL_ID = "autogluon/chronos-2-small"
MODEL_REVISION = "ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a"
MODEL_HASHES = {
    "config.json": "f2780468adc8b16322aa0b6e28b26476c9401ecf64ab53292b6d2b0d3f423722",
    "model.safetensors": "492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd",
}


def _validate_model(path: Path) -> Path:
    if (path / "adapter_config.json").exists():
        raise ValueError("Expected the pinned base model, not an adapter")
    for name, expected in MODEL_HASHES.items():
        with (path / name).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Pinned model artifact changed: {name}")
    return path.resolve()


@st.cache_resource(show_spinner=False, max_entries=4)
def _prepare_model(local_path: str) -> Path:
    """Provision only the public pinned checkpoint; the generated app stays offline."""
    if local_path:
        return _validate_model(Path(local_path).expanduser())
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    options = dict(repo_id=MODEL_ID, revision=MODEL_REVISION,
                   allow_patterns=list(MODEL_HASHES), token=False)
    try:
        path = snapshot_download(**options, local_files_only=True)
    except LocalEntryNotFoundError:
        path = snapshot_download(**options)
    # A cache directory may exist from an earlier metadata-only request.
    if any(not (Path(path) / name).is_file() for name in MODEL_HASHES):
        path = snapshot_download(**options)
    return _validate_model(Path(path))


def _read_verified_bundle() -> tuple[dict, dict[str, bytes]]:
    if DEMO_ROOT.is_symlink():
        raise ValueError("Forecast demo directory must not be a symlink")
    receipt = DEMO_ROOT / "result.json"
    if receipt.is_symlink():
        raise ValueError("Forecast demo receipt must not be a symlink")
    receipt_bytes = receipt.read_bytes()
    report = json.loads(receipt_bytes)
    if not isinstance(report, dict) or report.get("status") != "passed":
        raise ValueError("Forecast demo has no passed public receipt")
    if report.get("schema") != "agilab.notebook_agent.public_demo.v1":
        raise ValueError("Unsupported forecast demo receipt")
    verification = report.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "passed":
        raise ValueError("Forecast demo verification did not pass")
    checks = verification.get("checks")
    if not isinstance(checks, list) or not checks or any(not isinstance(v, str) or not v for v in checks):
        raise ValueError("Forecast demo verification checks are missing")
    forecast_verification = verification.get("forecast")
    if forecast_verification is not None:
        if (not isinstance(forecast_verification, dict)
                or forecast_verification.get("status") != "passed"):
            raise ValueError("Forecast-specific verification did not pass")
        forecast_checks = forecast_verification.get("checks")
        if (not isinstance(forecast_checks, list) or not forecast_checks
                or any(not isinstance(check, str) or not check for check in forecast_checks)):
            raise ValueError("Forecast-specific verification checks are missing")
    for section, keys in (
        ("demo", ("title", "description", "request")),
        ("source", ("repository", "commit", "url", "license")),
        ("model", ("id", "revision", "license")),
    ):
        metadata = report.get(section)
        if not isinstance(metadata, dict) or any(
            not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in keys
        ):
            raise ValueError(f"Forecast demo {section} metadata is incomplete")
    for key in ("run_id", "verification_scope"):
        if not isinstance(report.get(key), str) or not report[key].strip():
            raise ValueError(f"Forecast demo {key} is missing")
    seconds = report.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Forecast demo run duration is invalid")
    stages = report.get("workflow_stages")
    if isinstance(stages, bool) or not isinstance(stages, int) or stages < 1:
        raise ValueError("Forecast demo workflow stages are invalid")
    files = report.get("files")
    if not isinstance(files, dict) or not _REQUIRED_FILES.issubset(files):
        raise ValueError("Forecast demo artifact manifest is incomplete")
    payload = {"result.json": receipt_bytes}
    for name, expected in sorted(files.items()):
        relative = PurePosixPath(name)
        if (not name or "\\" in name or relative.is_absolute()
                or any(part in {".", ".."} for part in name.split("/"))
                or relative.as_posix() != name or name == "result.json"):
            raise ValueError("Invalid forecast demo artifact path")
        path = DEMO_ROOT
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Forecast demo artifact is a symlink: {name}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"Invalid forecast demo artifact hash: {name}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Forecast demo artifact changed since verification: {name}")
        payload[name] = data
    for path in sorted(DEMO_ROOT.rglob("*")):
        if path.is_symlink():
            raise ValueError("Forecast demo contains a symlink")
        if path.is_file():
            relative = path.relative_to(DEMO_ROOT)
            if "__pycache__" in relative.parts and path.suffix == ".pyc":
                continue
            if relative.as_posix() not in payload:
                raise ValueError(f"Unverified forecast demo artifact: {relative.as_posix()}")
    return report, payload


def load_report() -> dict:
    return _read_verified_bundle()[0]


def _zip_bundle(payload: dict[str, bytes]) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(name, data)
    return content.getvalue()


def download_bundle() -> bytes:
    return _zip_bundle(_read_verified_bundle()[1])


def _run_verified_app(payload: dict[str, bytes], model_path: Path | None = None) -> None:
    # Restore process-wide import state even when an app stops, reruns, or fails.
    with _APP_LOCK:
        previous = sys.modules.pop("forecast_core", None)
        previous_model_path = os.environ.get("CHRONOS_MODEL_PATH")
        module = ModuleType("forecast_core")
        module.__file__ = str(DEMO_ROOT / "forecast_core.py")
        sys.modules["forecast_core"] = module
        try:
            if model_path is not None:
                os.environ["CHRONOS_MODEL_PATH"] = str(model_path)
            exec(compile(payload["forecast_core.py"], module.__file__, "exec"), module.__dict__)
            app_path = str(DEMO_ROOT / "app.py")
            with app_session_state(st.session_state, "forecast",
                                   ("analysis", "analysis_error", "committed_parameters")):
                exec(compile(payload["app.py"], app_path, "exec"),
                     {"__name__": "__main__", "__file__": app_path})
        finally:
            sys.modules.pop("forecast_core", None)
            if previous is not None:
                sys.modules["forecast_core"] = previous
            if previous_model_path is None:
                os.environ.pop("CHRONOS_MODEL_PATH", None)
            else:
                os.environ["CHRONOS_MODEL_PATH"] = previous_model_path


def render() -> None:
    try:
        report, payload = _read_verified_bundle()
    except OSError:
        st.error("Forecast demo unavailable: the verified artifact bundle is missing or unreadable.")
        return
    except (ValueError, TypeError) as exc:
        st.error(f"Forecast demo unavailable: {exc}")
        return
    st.caption("TOKKI × AGILAB · FORECASTING DEMO")
    notebook_checks = report["verification"]["checks"]
    forecast_verification = report["verification"].get("forecast", {})
    forecast_checks = forecast_verification.get("checks", [])
    render_build_evidence(report, extra_metrics=(
        ("Recorded checks", len(notebook_checks) + len(forecast_checks)),
    ))
    st.subheader(report["demo"]["title"])
    st.write(report["demo"]["description"])
    with st.expander("Source and verification"):
        source, model = report["source"], report["model"]
        st.markdown(f"Source: [{source['repository']}]({source['url']}) · {source['license']}")
        st.caption(f"Source commit: {source['commit']}")
        st.write(f"Model: {model['id']} · {model['license']}")
        st.caption(f"Model revision: {model['revision']}")
        st.write(report["demo"]["request"])
        st.caption(f"Recorded run: {report['run_id']}")
        st.write("Verification scope: " + report["verification_scope"].replace("_", " "))
        st.write("Notebook and interface checks: " + ", ".join(notebook_checks))
        if forecast_checks:
            st.write("Forecast checks: " + ", ".join(forecast_checks))
            cases = forecast_verification.get("measurements", {}).get("cases", [])
            if cases:
                st.dataframe(
                    [{key: case[key] for key in ("seed", "mae", "baseline_mae", "coverage")} for case in cases],
                    hide_index=True,
                )
                st.caption("MAE and observed interval coverage are measured on synthetic held-out data. "
                           "The interval has nominal 80% coverage; observed coverage can be lower.")
        st.caption("The receipt describes the completed checks. File hashes are checked again before this demo runs.")
        st.download_button(
            "Download the forecast app and workflow",
            _zip_bundle(payload),
            "tokki-agilab-forecast-lab.zip",
            "application/zip",
            key="forecast_bundle",
        )
    st.divider()
    if (report["model"]["id"], report["model"]["revision"]) != (MODEL_ID, MODEL_REVISION):
        st.error("Forecast demo unavailable: unsupported model revision.")
        return
    try:
        with st.spinner("Preparing Chronos-2 Small · the first visit downloads about 112 MB"):
            # Cached provisioning avoids downloads, while hashing on every render
            # still detects a modified checkpoint before the generated app loads it.
            model_path = _validate_model(_prepare_model(os.environ.get("CHRONOS_MODEL_PATH", "")))
    except Exception:
        st.error("Chronos-2 Small could not be prepared. Check that the notebook-agent dependencies "
                 "are installed and the model host is reachable, then retry. For offline use, "
                 "set CHRONOS_MODEL_PATH to the verified checkpoint.")
        return
    _run_verified_app(payload, model_path)


if __name__ == "__main__":
    render()
