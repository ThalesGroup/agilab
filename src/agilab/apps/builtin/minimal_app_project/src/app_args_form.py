from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from minimal_app import MinimalAppArgs, dump_args, load_args


PAGE_ID = "minimal_app_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> MinimalAppArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load MinimalApp args from `{settings_path}`: {exc}")
        return MinimalAppArgs()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

st.caption(
    "MinimalApp is the minimal built-in app skeleton. Edit these paths and small run controls "
    "before adapting the manager and worker code to your own workflow."
)

for key, default in (
    ("data_in", str(current_payload.get("data_in", "minimal_app/dataset") or "minimal_app/dataset")),
    ("data_out", str(current_payload.get("data_out", "minimal_app/dataframe") or "minimal_app/dataframe")),
    ("files", str(current_payload.get("files", "*") or "*")),
    ("nfile", int(current_payload.get("nfile", 1) or 1)),
    ("nskip", int(current_payload.get("nskip", 0) or 0)),
    ("nread", int(current_payload.get("nread", 0) or 0)),
    ("reset_target", bool(current_payload.get("reset_target", False))),
):
    st.session_state.setdefault(_k(key), default)

c1, c2, c3 = st.columns([2, 2, 1.2])
with c1:
    st.text_input("Input directory", key=_k("data_in"), help="Relative path under shared storage.")
with c2:
    st.text_input("Output directory", key=_k("data_out"), help="Relative path under shared storage.")
with c3:
    st.text_input("Files filter", key=_k("files"), help="Wildcard or regex consumed by your worker.")

c4, c5, c6, c7 = st.columns([1.1, 1.1, 1.1, 1.1])
with c4:
    st.number_input("Number of files", key=_k("nfile"), min_value=0, step=1)
with c5:
    st.number_input("Lines to skip", key=_k("nskip"), min_value=0, step=1)
with c6:
    st.number_input("Lines to read", key=_k("nread"), min_value=0, step=1)
with c7:
    st.checkbox("Reset output", key=_k("reset_target"))

candidate: dict[str, Any] = {
    "files": (st.session_state.get(_k("files")) or "*").strip() or "*",
    "nfile": st.session_state.get(_k("nfile"), 1),
    "nskip": st.session_state.get(_k("nskip"), 0),
    "nread": st.session_state.get(_k("nread"), 0),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

data_in_raw = (st.session_state.get(_k("data_in")) or "").strip()
data_out_raw = (st.session_state.get(_k("data_out")) or "").strip()
if data_in_raw:
    candidate["data_in"] = data_in_raw
if data_out_raw:
    candidate["data_out"] = data_out_raw

try:
    validated = MinimalAppArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid MinimalApp parameters:")
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

    if hasattr(env, "resolve_share_path"):
        resolved_data_in = env.resolve_share_path(validated.data_in)
        resolved_data_out = env.resolve_share_path(validated.data_out)
        st.caption(f"Resolved input: `{resolved_data_in}`  •  output: `{resolved_data_out}`")
