import streamlit as st
from pydantic import ValidationError

from agi_env.streamlit_args import load_args_state, persist_args, render_form
import mycode as args_module
from mycode import ArgsModel


env = st.session_state._env

defaults_model, defaults_payload, settings_path = load_args_state(env, args_module=args_module)

if not st.session_state.get("toggle_edit", False):
    col1, col2 = st.columns(2)

    with col1:
        param1 = st.number_input("Parameter 1", value=int(defaults_model.param1))
        param2 = st.text_input("Parameter 2", value=defaults_model.param2)

    with col2:
        param3 = st.number_input("Parameter 3", value=float(defaults_model.param3))
        param4 = st.checkbox("Parameter 4", value=bool(defaults_model.param4))

    form_values = {
        "param1": int(param1),
        "param2": param2,
        "param3": float(param3),
        "param4": bool(param4),
    }
else:
    form_values = render_form(defaults_model)

try:
    parsed = ArgsModel(**form_values)
except ValidationError as exc:
    messages = env.humanize_validation_errors(exc)
    st.warning("\n".join(messages))
    st.session_state.pop("is_args_from_ui", None)
else:
    persist_args(args_module, parsed, settings_path=settings_path, defaults_payload=defaults_payload)
    st.success("All params are valid!")
