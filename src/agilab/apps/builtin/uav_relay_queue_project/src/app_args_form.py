from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from uav_relay_queue import UavRelayQueueArgs, dump_args, load_args


PAGE_ID = "uav_relay_queue_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILab environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> UavRelayQueueArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load UAV relay queue args from `{settings_path}`: {exc}")
        return UavRelayQueueArgs()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

try:
    share_root = env.share_root_path()
except Exception:
    share_root = None

artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / env.target / "queue_analysis"

st.caption(
    "This built-in app runs a lightweight UAV relay queue simulation with explicit "
    f"packet and queue telemetry. Analysis artifacts are exported to `{artifact_root}`."
)
if share_root:
    st.caption(f"Current shared root: `{share_root}`")

defaults = {
    "data_in": str(current_payload.get("data_in", "") or ""),
    "data_out": str(current_payload.get("data_out", "") or ""),
    "files": str(current_payload.get("files", "*.json") or "*.json"),
    "nfile": int(current_payload.get("nfile", 1) or 1),
    "routing_policy": str(current_payload.get("routing_policy", "shortest_path") or "shortest_path"),
    "sim_time_s": float(current_payload.get("sim_time_s", 30.0) or 30.0),
    "sampling_interval_s": float(current_payload.get("sampling_interval_s", 0.5) or 0.5),
    "source_rate_pps": float(current_payload.get("source_rate_pps", 14.0) or 14.0),
    "queue_weight": float(current_payload.get("queue_weight", 2.5) or 2.5),
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

c5, c6, c7 = st.columns([1.5, 1.2, 1.1])
with c5:
    st.selectbox("Routing policy", options=["shortest_path", "queue_aware"], key=_k("routing_policy"))
with c6:
    st.number_input("Sim time (s)", key=_k("sim_time_s"), min_value=2.0, max_value=600.0, step=1.0)
with c7:
    st.checkbox("Reset output", key=_k("reset_target"))

c8, c9, c10, c11 = st.columns([1.1, 1.1, 1.1, 1.1])
with c8:
    st.number_input("Sampling (s)", key=_k("sampling_interval_s"), min_value=0.1, max_value=10.0, step=0.1)
with c9:
    st.number_input("Source rate (pps)", key=_k("source_rate_pps"), min_value=0.1, max_value=500.0, step=0.5)
with c10:
    st.number_input("Queue weight", key=_k("queue_weight"), min_value=0.0, max_value=20.0, step=0.1)
with c11:
    st.number_input("Random seed", key=_k("random_seed"), min_value=0, step=1)

candidate: dict[str, Any] = {
    "files": (st.session_state.get(_k("files")) or "*.json").strip() or "*.json",
    "nfile": st.session_state.get(_k("nfile"), 1),
    "routing_policy": st.session_state.get(_k("routing_policy")) or "shortest_path",
    "sim_time_s": st.session_state.get(_k("sim_time_s"), 30.0),
    "sampling_interval_s": st.session_state.get(_k("sampling_interval_s"), 0.5),
    "source_rate_pps": st.session_state.get(_k("source_rate_pps"), 14.0),
    "queue_weight": st.session_state.get(_k("queue_weight"), 2.5),
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
    validated = UavRelayQueueArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid UAV relay queue parameters:")
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
        app_settings["pages"]["view_module"] = [
            "view_scenario_cockpit",
            "view_relay_resilience",
            "view_maps_network",
        ]
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    resolved_data_in = env.resolve_share_path(validated.data_in)
    resolved_data_out = env.resolve_share_path(validated.data_out)
    if not any(resolved_data_in.glob(validated.files)):
        st.info("No matching scenario file exists yet. The bundled sample scenario will be seeded on first run.")
    st.caption(
        f"Resolved input: `{resolved_data_in}`  •  results: `{resolved_data_out}`  •  "
        f"analysis artifacts: `{artifact_root}`"
    )
    st.caption(
        "The default sample is tuned to create a queue hotspot on `relay_a` under "
        "`shortest_path`, then improve when you switch to `queue_aware`."
    )
    st.caption(
        "Each run also exports comparison, topology, and trajectory evidence so "
        "`view_scenario_cockpit` and `view_maps_network` can reuse the same scenario."
    )
