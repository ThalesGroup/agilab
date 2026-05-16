from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from global_dag.app_args import GlobalDagArgs, dump_args, load_args


PAGE_ID = "global_dag_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> GlobalDagArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load Global DAG args from `{settings_path}`: {exc}")
        return GlobalDagArgs()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

st.caption(
    "Global DAG is a planning project: edit the template path and preview output, "
    "then use WORKFLOW to inspect the cross-app DAG."
)

for key, default in (
    ("dag_path", str(current_payload.get("dag_path", "dag_templates/flight_to_meteo_global_dag.json"))),
    ("output_path", str(current_payload.get("output_path", "~/log/execute/global_dag/runner_state.json"))),
    ("reset_target", bool(current_payload.get("reset_target", False))),
):
    st.session_state.setdefault(_k(key), default)

c1, c2 = st.columns([2, 2])
with c1:
    st.text_input("DAG template", key=_k("dag_path"))
with c2:
    st.text_input("Preview output", key=_k("output_path"))

c3, _ = st.columns([1.2, 2.8])
with c3:
    st.checkbox("Reset preview output", key=_k("reset_target"))

candidate: dict[str, Any] = {
    "dag_path": (st.session_state.get(_k("dag_path")) or "").strip(),
    "output_path": (st.session_state.get(_k("output_path")) or "").strip(),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

try:
    validated = GlobalDagArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid Global DAG parameters:")
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

    st.caption(
        f"Template `{validated.dag_path}` will write preview state to `{validated.output_path}`."
    )
