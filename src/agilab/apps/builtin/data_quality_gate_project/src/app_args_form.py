from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from data_quality_gate import DataQualityGateArgs, dump_args, load_args  # noqa: E402


PAGE_ID = "data_quality_gate_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> DataQualityGateArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load Data Quality Gate args from `{settings_path}`: {exc}")
        return DataQualityGateArgs()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / env.target / "data_quality_gate"
st.caption(
    "Data Quality Gate validates a deterministic candidate dataset against a "
    f"contract, drift thresholds, and promotion decision. Analysis artifacts are exported to `{artifact_root}`."
)

for key, default in (
    ("data_out", str(current_payload.get("data_out", "data_quality_gate/evidence") or "data_quality_gate/evidence")),
    ("baseline_rows", int(current_payload.get("baseline_rows", 240) or 240)),
    ("candidate_rows", int(current_payload.get("candidate_rows", 220) or 220)),
    ("drift_strength", float(current_payload.get("drift_strength", 0.35) or 0.35)),
    ("seed", int(current_payload.get("seed", 2026) or 2026)),
    ("include_quality_issues", bool(current_payload.get("include_quality_issues", False))),
    ("reset_target", bool(current_payload.get("reset_target", False))),
):
    st.session_state.setdefault(_k(key), default)

c1, c2, c3 = st.columns([2.0, 1.0, 1.0])
with c1:
    st.text_input("Evidence directory", key=_k("data_out"))
with c2:
    st.number_input("Baseline rows", key=_k("baseline_rows"), min_value=50, max_value=10000, step=10)
with c3:
    st.number_input("Candidate rows", key=_k("candidate_rows"), min_value=50, max_value=10000, step=10)

c4, c5, c6 = st.columns([1.0, 1.0, 1.0])
with c4:
    st.slider("Drift strength", key=_k("drift_strength"), min_value=0.0, max_value=1.0, step=0.05)
with c5:
    st.number_input("Seed", key=_k("seed"), min_value=0, step=1)
with c6:
    st.checkbox("Inject quality issues", key=_k("include_quality_issues"))
    st.checkbox("Reset output", key=_k("reset_target"))

candidate: dict[str, Any] = {
    "data_out": (st.session_state.get(_k("data_out")) or "").strip(),
    "baseline_rows": st.session_state.get(_k("baseline_rows"), 240),
    "candidate_rows": st.session_state.get(_k("candidate_rows"), 220),
    "drift_strength": st.session_state.get(_k("drift_strength"), 0.35),
    "seed": st.session_state.get(_k("seed"), 2026),
    "include_quality_issues": bool(st.session_state.get(_k("include_quality_issues"), False)),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

try:
    validated = DataQualityGateArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid Data Quality Gate parameters:")
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
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    resolved_data_out = env.resolve_share_path(validated.data_out)
    st.caption(
        f"Resolved evidence directory: `{resolved_data_out}`  -  "
        f"candidate/baseline rows: `{validated.candidate_rows}/{validated.baseline_rows}`."
    )
