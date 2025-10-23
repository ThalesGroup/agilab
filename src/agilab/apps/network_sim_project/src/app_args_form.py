from pathlib import Path
from typing import Any

import streamlit as st
import tomli
from pydantic import ValidationError

from agi_env.pagelib import diagnose_data_directory
from agi_env.streamlit_args import render_form
from network_sim import (
    NetworkSimArgs,
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
    stored_args = NetworkSimArgs(**stored_payload)
except ValidationError as exc:
    messages = env.humanize_validation_errors(exc)
    st.warning("\n".join(messages) + f"\nplease check {settings_path}")
    st.session_state.pop("is_args_from_ui", None)
    stored_args = NetworkSimArgs()

defaults_model = apply_source_defaults(stored_args)
defaults_payload = defaults_model.to_toml_payload()
st.session_state.app_settings["args"] = defaults_payload

if not st.session_state.get("toggle_edit", False):
    c1, c2, c3, c4 = st.columns(4)

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
        net_size = st.number_input(
            "Number of nodes",
            min_value=4,
            value=int(defaults_model.net_size),
            step=1,
        )
        topology_filename = st.text_input(
            "Topology filename",
            value=str(defaults_model.topology_filename),
        )

    with c4:
        seed = st.number_input("Random seed", value=int(defaults_model.seed), step=1)
        summary_filename = st.text_input(
            "Summary filename",
            value=str(defaults_model.summary_filename),
        )

    if st.session_state.data_source == "file":
        directory = env.home_abs / st.session_state.data_uri
        if not directory.is_dir():
            diagnosis = diagnose_data_directory(directory)
            if not diagnosis:
                diagnosis = (
                    f"The provided data_uri '{directory}' is not a valid directory. "
                    "If this location is a shared file mount, the shared file server may be down."
                )
            st.error(diagnosis)
            st.stop()
    validated_path = st.session_state.data_uri

    candidate_args: dict[str, Any] = {
        "data_source": st.session_state.data_source,
        "data_uri": validated_path,
        "net_size": int(net_size),
        "seed": int(seed),
        "topology_filename": topology_filename,
        "summary_filename": summary_filename,
        "data_uri": validated_path,
    }
else:
    form_values = render_form(defaults_model)
    candidate_args = form_values

try:
    parsed_args = NetworkSimArgs(**candidate_args)
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
