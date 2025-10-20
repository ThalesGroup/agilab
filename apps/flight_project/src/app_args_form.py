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


def change_data_source() -> None:
    """Reset dependent fields when the data source toggles."""

    st.session_state.pop("data_uri", None)
    st.session_state.pop("files", None)


def load_app_settings(path: Path) -> dict[str, Any]:
    """Load the full Streamlit app settings TOML into a dictionary."""

    if path.exists():
        with path.open("rb") as handle:
            return tomli.load(handle)
    return {}


env = st.session_state._env
settings_path = Path(env.app_settings_file)

# Ensure app_settings is available in session state
app_settings = st.session_state.get("app_settings")
if not app_settings or not st.session_state.get("is_args_from_ui"):
    app_settings = load_app_settings(settings_path)
    st.session_state.app_settings = app_settings

stored_payload = dict(app_settings.get("args", {}))
try:
    stored_args = FlightArgs(**stored_payload)
except ValidationError as exc:
    messages = env.humanize_validation_errors(exc)
    st.warning("\n".join(messages) + f"\nplease check {settings_path}")
    st.session_state.pop("is_args_from_ui", None)
    stored_args = FlightArgs()

defaults_model = apply_source_defaults(stored_args)
defaults_payload = defaults_model.to_toml_payload()
st.session_state.app_settings["args"] = defaults_payload

if st.session_state.get("toggle_custom", True):
    # Streamlit User Interface
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1.0, 1])

    with c1:
        st.selectbox(
            label="Data source",
            options=["file", "hawk"],
            index=["file", "hawk"].index(defaults_model.data_source),
            key="data_source",
            on_change=change_data_source,
        )

    with c2:
        if st.session_state.data_source == "file":
            st.text_input(
                label="Data directory",
                value=str(defaults_model.data_uri),
                key="data_uri",
            )
        else:
            st.text_input(
                label="Hawk cluster data_uri",
                value=str(defaults_model.data_uri),
                key="data_uri",
            )

    with c3:
        if st.session_state.data_source == "file":
            st.text_input(
                label="Files filter",
                value=defaults_model.files,
                key="files",
            )
        else:
            st.text_input(
                label="Select the pipeline",
                value=defaults_model.files,
                key="files",
            )

    with c4:
        st.number_input(
            label="Number of files to read",
            value=defaults_model.nfile,
            key="nfile",
            step=1,
            min_value=0,
        )

    with c5:
        st.number_input(
            label="Number of line to skip",
            value=defaults_model.nskip,
            key="nskip",
            step=1,
            min_value=0,
        )

    c6, c7, c8, c9, c10 = st.columns([1, 1, 1, 1, 1])

    with c6:
        st.number_input(
            label="Number of lines to read",
            value=defaults_model.nread,
            key="nread",
            step=1,
            min_value=0,
        )

    with c7:
        st.number_input(
            label="Sampling rate",
            value=defaults_model.sampling_rate,
            key="sampling_rate",
            step=0.1,
            min_value=0.0,
        )

    with c8:
        st.date_input(
            label="from Date",
            value=defaults_model.datemin,
            key="datemin",
        )

    with c9:
        st.date_input(
            label="to Date",
            value=defaults_model.datemax,
            key="datemax",
        )

    with c10:
        st.selectbox(
            label="Dataset output format",
            options=["parquet", "csv"],
            index=["parquet", "csv"].index(defaults_model.output_format),
            key="output_format",
        )

    if st.session_state.data_source == "file":
        directory = env.home_abs / st.session_state.data_uri
        if not directory.is_dir():
            st.error(f"The provided data_uri '{directory}' is not a valid directory.")
            st.stop()
    validated_path = st.session_state.data_uri

    candidate_args: dict[str, Any] = {
        "data_source": st.session_state.data_source,
        "data_uri": validated_path,
        "files": st.session_state.files,
        "nfile": st.session_state.nfile,
        "nskip": st.session_state.nskip,
        "nread": st.session_state.nread,
        "sampling_rate": st.session_state.sampling_rate,
        "datemin": st.session_state.datemin,
        "datemax": st.session_state.datemax,
        "output_format": st.session_state.output_format,
    }
else:
    form_values = render_form(defaults_model)
    candidate_args = form_values

try:
    parsed_args = FlightArgs(**candidate_args)
except ValidationError as exc:
    messages = env.humanize_validation_errors(exc)
    st.warning("\n".join(messages))
    st.session_state.pop("is_args_from_ui", None)
else:
    st.success("All params are valid !")

    payload = parsed_args.to_toml_payload()
    if payload != defaults_payload:
        dump_args_to_toml(parsed_args, settings_path)
        st.session_state.app_settings["args"] = payload
        st.session_state.is_args_from_ui = True
        st.session_state["args_project"] = env.app
