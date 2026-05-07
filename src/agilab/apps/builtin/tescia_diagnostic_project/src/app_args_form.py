from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from tescia_diagnostic import TesciaDiagnosticArgs, dump_args, load_args


PAGE_ID = "tescia_diagnostic_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> TesciaDiagnosticArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load TeSciA diagnostic args from `{settings_path}`: {exc}")
        return TesciaDiagnosticArgs()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")
artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / env.target / "tescia_diagnostic"

st.caption(
    "Turn a TeSciA-style diagnostic into repeatable evidence: symptom, evidence quality, "
    "root-cause fit, better fix, and regression plan."
)
st.caption(f"Analysis artifacts are exported to `{artifact_root}`.")

st.session_state.setdefault(_k("data_in"), str(current_payload.get("data_in", "") or ""))
st.session_state.setdefault(_k("data_out"), str(current_payload.get("data_out", "") or ""))
st.session_state.setdefault(_k("files"), str(current_payload.get("files", "*.json") or "*.json"))
st.session_state.setdefault(_k("nfile"), int(current_payload.get("nfile", 1) or 1))
st.session_state.setdefault(
    _k("minimum_evidence_confidence"),
    float(current_payload.get("minimum_evidence_confidence", 0.65) or 0.65),
)
st.session_state.setdefault(
    _k("minimum_regression_coverage"),
    float(current_payload.get("minimum_regression_coverage", 0.6) or 0.6),
)
st.session_state.setdefault(_k("reset_target"), bool(current_payload.get("reset_target", False)))

c1, c2, c3, c4 = st.columns([2, 2, 1.2, 1.1])
with c1:
    st.text_input("Diagnostic cases directory", key=_k("data_in"))
with c2:
    st.text_input("Report output directory", key=_k("data_out"))
with c3:
    st.text_input("Files glob", key=_k("files"))
with c4:
    st.number_input("Number of files", key=_k("nfile"), min_value=1, max_value=50, step=1)

c5, c6, c7 = st.columns([1.4, 1.4, 1.0])
with c5:
    st.number_input(
        "Minimum evidence confidence",
        key=_k("minimum_evidence_confidence"),
        min_value=0.0,
        max_value=1.0,
        step=0.05,
    )
with c6:
    st.number_input(
        "Minimum regression coverage",
        key=_k("minimum_regression_coverage"),
        min_value=0.0,
        max_value=1.0,
        step=0.05,
    )
with c7:
    st.checkbox("Reset output", key=_k("reset_target"))

candidate: dict[str, Any] = {
    "files": (st.session_state.get(_k("files")) or "*.json").strip() or "*.json",
    "nfile": st.session_state.get(_k("nfile"), 1),
    "minimum_evidence_confidence": st.session_state.get(_k("minimum_evidence_confidence"), 0.65),
    "minimum_regression_coverage": st.session_state.get(_k("minimum_regression_coverage"), 0.6),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

data_in_raw = (st.session_state.get(_k("data_in")) or "").strip()
data_out_raw = (st.session_state.get(_k("data_out")) or "").strip()
if data_in_raw:
    candidate["data_in"] = data_in_raw
if data_out_raw:
    candidate["data_out"] = data_out_raw

try:
    validated = TesciaDiagnosticArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid TeSciA diagnostic parameters:")
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
        app_settings["args"] = validated_payload
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    resolved_data_in = env.resolve_share_path(validated.data_in)
    resolved_data_out = env.resolve_share_path(validated.data_out)
    if not any(resolved_data_in.glob(validated.files)):
        st.info("No diagnostic JSON exists yet. The bundled sample will be seeded on first run.")
    st.caption(f"Resolved input: `{resolved_data_in}`  •  reports: `{resolved_data_out}`")
