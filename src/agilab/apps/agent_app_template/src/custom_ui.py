import streamlit as st
from pydantic import ValidationError

from agi_env.streamlit_args import load_args_state, persist_args, render_form
import agent_app as args_module
from agent_app import AgentAppArgs as ArgsModel


env = st.session_state.env

defaults_model, defaults_payload, settings_path = load_args_state(env, args_module=args_module)

if st.session_state.get("toggle_custom", True):
    data_uri = st.text_input(
        "Data directory",
        value=str(defaults_model.data_uri),
        help="Base folder used by the agent application.",
    )

    form_values = {
        "data_uri": data_uri,
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
