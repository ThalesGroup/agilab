from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from tescia_diagnostic import (
    DEFAULT_GPT_OSS_ENDPOINT,
    DEFAULT_GPT_OSS_MODEL,
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_OLLAMA_MODEL,
    TesciaDiagnosticArgs,
    dump_args,
    load_args,
)


PAGE_ID = "tescia_diagnostic_project:app_args_form"
CASE_SOURCE_OPTIONS = ("bundled", "standalone_ai")
AI_PROVIDER_OPTIONS = ("gpt-oss", "ollama")
SCORING_FORMULAS = (
    r"E = 0.6 \cdot \overline{confidence} + 0.4 \cdot \overline{relevance}",
    r"R = 0.65 \cdot discriminator\_rate + 0.35 \cdot automated\_rate",
    r"F = 0.38 \cdot impact + 0.25E + 0.22R + 0.10(1 - blast\_radius) + 0.05 \cdot reversibility",
    r"student\_score = 100 \cdot (0.35E + 0.30R + 0.25F + 0.10 \cdot gate)",
)


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


def _render_scoring_model() -> None:
    """Render the deterministic scoring model with real math layout."""
    with st.expander("Scoring model", expanded=False):
        st.caption(
            "The app scores diagnostic quality deterministically. Thresholds gate whether the "
            "case is actionable; they do not change the formulas below."
        )
        for formula in SCORING_FORMULAS:
            st.latex(formula)
        st.caption(
            "E: evidence quality, R: regression coverage, F: selected-fix quality, "
            "gate: 1 when evidence and regression thresholds pass, otherwise 0."
        )


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
st.session_state.setdefault(_k("case_source"), str(current_payload.get("case_source", "bundled") or "bundled"))
st.session_state.setdefault(
    _k("generated_cases_filename"),
    str(current_payload.get("generated_cases_filename", "tescia_diagnostic_cases.generated.json") or ""),
)
st.session_state.setdefault(_k("regenerate_cases"), bool(current_payload.get("regenerate_cases", False)))
st.session_state.setdefault(_k("ai_provider"), str(current_payload.get("ai_provider", "gpt-oss") or "gpt-oss"))
st.session_state.setdefault(
    _k("ai_endpoint"),
    str(current_payload.get("ai_endpoint", DEFAULT_GPT_OSS_ENDPOINT) or DEFAULT_GPT_OSS_ENDPOINT),
)
st.session_state.setdefault(
    _k("ai_model"),
    str(current_payload.get("ai_model", DEFAULT_GPT_OSS_MODEL) or DEFAULT_GPT_OSS_MODEL),
)
st.session_state.setdefault(_k("ai_topic"), str(current_payload.get("ai_topic", "") or ""))
st.session_state.setdefault(_k("ai_case_count"), int(current_payload.get("ai_case_count", 2) or 2))
st.session_state.setdefault(
    _k("ai_temperature"),
    float(current_payload.get("ai_temperature", 0.2) or 0.2),
)
st.session_state.setdefault(
    _k("ai_timeout_s"),
    float(current_payload.get("ai_timeout_s", 120.0) or 120.0),
)

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

_render_scoring_model()

st.selectbox(
    "Diagnostic case source",
    CASE_SOURCE_OPTIONS,
    key=_k("case_source"),
    format_func=lambda value: {
        "bundled": "Bundled deterministic sample",
        "standalone_ai": "Generate with standalone AI",
    }.get(value, value),
)

if st.session_state.get(_k("case_source")) == "standalone_ai":
    st.caption(
        "Standalone AI generation runs only during AGILAB RUN. Save does not call the model. "
        "If the endpoint is unavailable, RUN fails clearly instead of falling back silently."
    )
    g1, g2, g3 = st.columns([1.2, 2.2, 1.6])
    with g1:
        st.selectbox(
            "AI provider",
            AI_PROVIDER_OPTIONS,
            key=_k("ai_provider"),
            format_func=lambda value: {
                "gpt-oss": "GPT-OSS Responses",
                "ollama": "Ollama generate",
            }.get(value, value),
        )
    with g2:
        st.text_input("AI endpoint", key=_k("ai_endpoint"))
    with g3:
        st.text_input("AI model", key=_k("ai_model"))

    if st.session_state.get(_k("ai_provider")) == "ollama":
        st.caption(f"Typical Ollama endpoint: `{DEFAULT_OLLAMA_ENDPOINT}` with model `{DEFAULT_OLLAMA_MODEL}`.")
    else:
        st.caption(f"Typical GPT-OSS endpoint: `{DEFAULT_GPT_OSS_ENDPOINT}` with model `{DEFAULT_GPT_OSS_MODEL}`.")

    g4, g5, g6, g7 = st.columns([2.0, 1.0, 1.0, 1.0])
    with g4:
        st.text_input("Generated cases filename", key=_k("generated_cases_filename"))
    with g5:
        st.number_input("Generated cases", key=_k("ai_case_count"), min_value=1, max_value=5, step=1)
    with g6:
        st.number_input("AI temperature", key=_k("ai_temperature"), min_value=0.0, max_value=1.0, step=0.05)
    with g7:
        st.number_input("AI timeout (s)", key=_k("ai_timeout_s"), min_value=1.0, max_value=600.0, step=10.0)
    st.checkbox("Regenerate cases on each run", key=_k("regenerate_cases"))
    st.text_area("Generation topic", key=_k("ai_topic"), height=92)

candidate: dict[str, Any] = {
    "files": (st.session_state.get(_k("files")) or "*.json").strip() or "*.json",
    "nfile": st.session_state.get(_k("nfile"), 1),
    "minimum_evidence_confidence": st.session_state.get(_k("minimum_evidence_confidence"), 0.65),
    "minimum_regression_coverage": st.session_state.get(_k("minimum_regression_coverage"), 0.6),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
    "case_source": st.session_state.get(_k("case_source"), "bundled"),
    "generated_cases_filename": (
        st.session_state.get(_k("generated_cases_filename"))
        or "tescia_diagnostic_cases.generated.json"
    ),
    "regenerate_cases": bool(st.session_state.get(_k("regenerate_cases"), False)),
    "ai_provider": st.session_state.get(_k("ai_provider"), "gpt-oss"),
    "ai_endpoint": st.session_state.get(_k("ai_endpoint"), DEFAULT_GPT_OSS_ENDPOINT),
    "ai_model": st.session_state.get(_k("ai_model"), DEFAULT_GPT_OSS_MODEL),
    "ai_topic": st.session_state.get(_k("ai_topic"), ""),
    "ai_case_count": st.session_state.get(_k("ai_case_count"), 2),
    "ai_temperature": st.session_state.get(_k("ai_temperature"), 0.2),
    "ai_timeout_s": st.session_state.get(_k("ai_timeout_s"), 120.0),
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
        if validated.case_source == "standalone_ai":
            st.info("No generated diagnostic JSON exists yet. The standalone AI engine will create it on first run.")
        else:
            st.info("No diagnostic JSON exists yet. The bundled sample will be seeded on first run.")
    st.caption(f"Resolved input: `{resolved_data_in}`  •  reports: `{resolved_data_out}`")
