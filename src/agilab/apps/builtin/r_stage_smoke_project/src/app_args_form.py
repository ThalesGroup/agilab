from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from r_stage_smoke.app_args import RStageSmokeArgs, dump_args, load_args


PAGE_ID = "r_stage_smoke_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> RStageSmokeArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load R Stage Smoke args from `{settings_path}`: {exc}")
        return RStageSmokeArgs()


def _parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

st.caption(
    "R Stage Smoke runs an external Rscript stage through a JSON input/output and artifact-directory contract. "
    "AGILAB captures stdout, stderr, output.json, artifacts, hashes, and reduce evidence."
)

for key, default in (
    ("data_out", str(current_payload.get("data_out", "r_stage_smoke/evidence") or "r_stage_smoke/evidence")),
    ("script_path", str(current_payload.get("script_path", "scripts/summarize.R") or "scripts/summarize.R")),
    ("rscript", str(current_payload.get("rscript", "Rscript") or "Rscript")),
    ("x", ", ".join(str(value) for value in current_payload.get("x", [1, 2, 3, 4, 5]))),
    ("timeout_seconds", int(current_payload.get("timeout_seconds", 120) or 120)),
    ("reset_target", bool(current_payload.get("reset_target", False))),
):
    st.session_state.setdefault(_k(key), default)

c1, c2 = st.columns([2, 2])
with c1:
    st.text_input("Evidence directory", key=_k("data_out"))
with c2:
    st.text_input("R script", key=_k("script_path"))

c3, c4, c5 = st.columns([1.2, 2.8, 1.2])
with c3:
    st.text_input("Rscript command", key=_k("rscript"))
with c4:
    st.text_input("Input x values", key=_k("x"))
with c5:
    st.number_input("Timeout seconds", key=_k("timeout_seconds"), min_value=1, max_value=3600, step=10)

st.checkbox("Reset output", key=_k("reset_target"))

try:
    candidate: dict[str, Any] = {
        "data_out": (st.session_state.get(_k("data_out")) or "").strip(),
        "script_path": (st.session_state.get(_k("script_path")) or "").strip(),
        "rscript": (st.session_state.get(_k("rscript")) or "Rscript").strip(),
        "x": _parse_float_list(str(st.session_state.get(_k("x")) or "")),
        "timeout_seconds": st.session_state.get(_k("timeout_seconds"), 120),
        "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
    }
    validated = RStageSmokeArgs(**candidate)
except (ValidationError, ValueError) as exc:
    st.error("Invalid R Stage Smoke parameters:")
    if isinstance(exc, ValidationError) and hasattr(env, "humanize_validation_errors"):
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

    st.caption(
        f"Planned R payload: `{len(validated.x)}` values through `{validated.rscript}` and "
        f"`{validated.script_path}`."
    )
