from pathlib import Path
from typing import Any
import streamlit as st
import tomli
from pydantic import ValidationError
from agi_env.streamlit_args import render_form
from flight import (
    FlightArgs,
    apply_source_defaults,
    dump_args_to_toml,
)

def change_data_source(*args: Any, **kwargs: Any) -> Any: ...

def load_app_settings(*args: Any, **kwargs: Any) -> Any: ...

env = st.session_state._env

settings_path = Path(env.app_settings_file)

app_settings = st.session_state.get("app_settings")

stored_payload = dict(app_settings.get("args", {}))

defaults_model = apply_source_defaults(stored_args)

defaults_payload = defaults_model.to_toml_payload()

st.session_state.app_settings["args"] = defaults_payload
