import streamlit as st
from pydantic import ValidationError
from agi_env.streamlit_args import load_args_state, persist_args, render_form
import fireducks_app as args_module
from fireducks_app import FireducksAppArgs as ArgsModel

env = st.session_state._env

defaults_model, defaults_payload, settings_path = load_args_state(env, args_module=args_module)

form_values = render_form(defaults_model)
