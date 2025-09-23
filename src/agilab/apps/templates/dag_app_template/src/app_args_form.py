import streamlit as st
from pydantic import ValidationError

from agi_env.streamlit_args import load_args_state, persist_args, render_form
import dag_app as args_module
from dag_app import DagAppArgs as ArgsModel


env = st.session_state._env

defaults_model, defaults_payload, settings_path = load_args_state(env, args_module=args_module)

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
