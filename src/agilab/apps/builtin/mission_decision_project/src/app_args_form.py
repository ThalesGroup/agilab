from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from data_io_2026 import DataIo2026Args, dump_args, load_args


PAGE_ID = "mission_decision_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILab environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> DataIo2026Args:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load Mission Decision args from `{settings_path}`: {exc}")
        return DataIo2026Args()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

try:
    share_root = env.share_root_path()
except Exception:
    share_root = None

artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / env.target / "data_io_decision"

st.caption(
    "This built-in app runs the public Mission Decision demo: "
    "ingest mission data, generate the pipeline, inject a failure, re-plan, and export evidence."
)
if share_root:
    st.caption(f"Current shared root: `{share_root}`")
st.caption(f"Analysis artifacts are exported to `{artifact_root}`.")

defaults = {
    "data_in": str(current_payload.get("data_in", "") or ""),
    "data_out": str(current_payload.get("data_out", "") or ""),
    "files": str(current_payload.get("files", "*.json") or "*.json"),
    "nfile": int(current_payload.get("nfile", 1) or 1),
    "objective": str(current_payload.get("objective", "balanced_mission") or "balanced_mission"),
    "adaptation_mode": str(current_payload.get("adaptation_mode", "auto_replan") or "auto_replan"),
    "failure_kind": str(current_payload.get("failure_kind", "bandwidth_drop") or "bandwidth_drop"),
    "latency_weight": float(current_payload.get("latency_weight", 0.65) or 0.65),
    "cost_weight": float(current_payload.get("cost_weight", 0.12) or 0.12),
    "reliability_weight": float(current_payload.get("reliability_weight", 0.16) or 0.16),
    "risk_weight": float(current_payload.get("risk_weight", 0.07) or 0.07),
    "random_seed": int(current_payload.get("random_seed", 2026) or 2026),
    "reset_target": bool(current_payload.get("reset_target", False)),
}
for key, value in defaults.items():
    st.session_state.setdefault(_k(key), value)

c1, c2, c3, c4 = st.columns([2, 2, 1.2, 1.2])
with c1:
    st.text_input("Scenario directory", key=_k("data_in"))
with c2:
    st.text_input("Results directory", key=_k("data_out"))
with c3:
    st.text_input("Files glob", key=_k("files"))
with c4:
    st.number_input("Number of files", key=_k("nfile"), min_value=1, step=1)

c5, c6, c7, c8 = st.columns([1.4, 1.4, 1.3, 1.0])
with c5:
    st.selectbox(
        "Objective",
        options=["balanced_mission", "latency_first", "resilience_first"],
        key=_k("objective"),
    )
with c6:
    st.selectbox("Adaptation", options=["auto_replan", "observe_only"], key=_k("adaptation_mode"))
with c7:
    st.selectbox("Failure mode", options=["bandwidth_drop", "node_failure", "combined"], key=_k("failure_kind"))
with c8:
    st.checkbox("Reset output", key=_k("reset_target"))

c9, c10, c11, c12, c13 = st.columns([1, 1, 1, 1, 1])
with c9:
    st.number_input("Latency weight", key=_k("latency_weight"), min_value=0.0, max_value=1.0, step=0.01)
with c10:
    st.number_input("Cost weight", key=_k("cost_weight"), min_value=0.0, max_value=1.0, step=0.01)
with c11:
    st.number_input("Reliability weight", key=_k("reliability_weight"), min_value=0.0, max_value=1.0, step=0.01)
with c12:
    st.number_input("Risk weight", key=_k("risk_weight"), min_value=0.0, max_value=1.0, step=0.01)
with c13:
    st.number_input("Random seed", key=_k("random_seed"), min_value=0, step=1)

candidate: dict[str, Any] = {
    "files": (st.session_state.get(_k("files")) or "*.json").strip() or "*.json",
    "nfile": st.session_state.get(_k("nfile"), 1),
    "objective": st.session_state.get(_k("objective")) or "balanced_mission",
    "adaptation_mode": st.session_state.get(_k("adaptation_mode")) or "auto_replan",
    "failure_kind": st.session_state.get(_k("failure_kind")) or "bandwidth_drop",
    "latency_weight": st.session_state.get(_k("latency_weight"), 0.65),
    "cost_weight": st.session_state.get(_k("cost_weight"), 0.12),
    "reliability_weight": st.session_state.get(_k("reliability_weight"), 0.16),
    "risk_weight": st.session_state.get(_k("risk_weight"), 0.07),
    "random_seed": st.session_state.get(_k("random_seed"), 2026),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

data_in_raw = (st.session_state.get(_k("data_in")) or "").strip()
data_out_raw = (st.session_state.get(_k("data_out")) or "").strip()
if data_in_raw:
    candidate["data_in"] = data_in_raw
if data_out_raw:
    candidate["data_out"] = data_out_raw

try:
    validated = DataIo2026Args(**candidate)
except ValidationError as exc:
    st.error("Invalid Mission Decision parameters:")
    if hasattr(env, "humanize_validation_errors"):
        for msg in env.humanize_validation_errors(exc):
            st.markdown(msg)
    else:
        st.code(str(exc))
else:
    validated_payload = validated.model_dump(mode="json")
    if validated_payload != current_payload:
        dump_args(validated, settings_path)
        app_settings = st.session_state.get("app_settings")
        if not isinstance(app_settings, dict):
            app_settings = {}
        app_settings.setdefault("cluster", {})
        app_settings["args"] = validated_payload
        app_settings.setdefault("pages", {})
        app_settings["pages"]["default_view"] = "view_data_io_decision"
        app_settings["pages"]["view_module"] = ["view_data_io_decision"]
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    resolved_data_in = env.resolve_share_path(validated.data_in)
    resolved_data_out = env.resolve_share_path(validated.data_out)
    if not any(resolved_data_in.glob(validated.files)):
        st.info("No matching scenario file exists yet. The bundled public scenario will be seeded on first run.")
    st.caption(
        f"Resolved input: `{resolved_data_in}`  -  results: `{resolved_data_out}`  -  "
        f"analysis artifacts: `{artifact_root}`"
    )
    st.caption(
        "Default behavior selects a fast direct route first, injects a bandwidth drop, "
        "then re-plans toward a more reliable relay route."
    )
