from pathlib import Path
from typing import Any

import streamlit as st
import tomli
from pydantic import ValidationError

from agi_env.pagelib import diagnose_data_directory
from agi_env.streamlit_args import render_form
from network_sim import NetworkSimArgs, apply_source_defaults, dump_args_to_toml

PREFIX = "network_sim_"


def _load_settings(path: Path) -> dict[str, Any]:
    if path.exists():
        with path.open("rb") as handle:
            return tomli.load(handle)
    return {"args": {}}


def _ensure_streamlit_context() -> Any | None:
    """Return the AGI environment injected by the hosting Streamlit app."""
    return st.session_state.get("_env")


def render() -> None:
    env = _ensure_streamlit_context()
    if env is None:
        return

    settings_path = Path(env.app_settings_file)

    app_settings = st.session_state.get("app_settings")
    if not app_settings or not st.session_state.get("is_args_from_ui"):
        app_settings = _load_settings(settings_path)
        st.session_state.app_settings = app_settings

    try:
        stored_args = NetworkSimArgs(**dict(app_settings.get("args", {})))
    except ValidationError as exc:
        st.warning("\n".join(env.humanize_validation_errors(exc)) + f"\nplease check {settings_path}")
        st.session_state.pop("is_args_from_ui", None)
        stored_args = NetworkSimArgs(data_source="file")

    defaults_model = apply_source_defaults(stored_args, env=env)
    defaults_payload = defaults_model.to_toml_payload()
    st.session_state.app_settings["args"] = defaults_payload

    if not st.session_state.get("toggle_edit", False):
        c1, c2, c3, c4 = st.columns(4)

        data_source = st.selectbox(
            "Data source",
            options=["file", "hawk"],
            index=["file", "hawk"].index(defaults_model.data_source),
            key=f"{PREFIX}data_source",
        )

        with c2:
            data_in = st.text_input(
                "Inputs dir" if data_source == "file" else "Hawk cluster data_in",
                value=str(defaults_model.data_in),
                key=f"{PREFIX}data_in",
                help=f"Workers read from {env.agi_share_dir}/<your path> when running locally.",
            )

        with c3:
            net_size = st.number_input(
                "Number of nodes",
                min_value=4,
                value=int(defaults_model.net_size),
                step=1,
                key=f"{PREFIX}net_size",
            )
            topology_filename = st.text_input(
                "Topology filename",
                value=str(defaults_model.topology_filename),
                key=f"{PREFIX}topology_filename",
            )

        with c4:
            seed = st.number_input(
                "Random seed",
                value=int(defaults_model.seed) if defaults_model.seed is not None else 0,
                step=1,
                key=f"{PREFIX}seed",
            )
            summary_filename = st.text_input(
                "Summary filename",
                value=str(defaults_model.summary_filename),
                key=f"{PREFIX}summary_filename",
            )

        if data_source == "file":
            directory = env.agi_share_dir / data_in
            if not directory.is_dir():
                diagnosis = diagnose_data_directory(directory)
                if not diagnosis:
                    diagnosis = (
                        f"The provided data_in '{directory}' is not a valid directory. "
                        "If this location is a shared file mount, the shared file server may be down."
                    )
                st.error(diagnosis)
                st.stop()

        candidate_args: dict[str, Any] = {
            "data_source": data_source,
            "data_in": data_in,
            "net_size": int(net_size),
            "seed": int(seed),
            "topology_filename": topology_filename,
            "summary_filename": summary_filename,
        }
    else:
        candidate_args = render_form(defaults_model)

    try:
        parsed_args = NetworkSimArgs(**candidate_args)
    except ValidationError as exc:
        st.warning("\n".join(env.humanize_validation_errors(exc)))
        st.session_state.pop("is_args_from_ui", None)
        return

    st.success("All params are valid !")

    payload = parsed_args.to_toml_payload()
    if payload != defaults_payload:
        dump_args_to_toml(parsed_args, settings_path)
        st.session_state.app_settings["args"] = payload
        st.session_state.is_args_from_ui = True
        st.session_state["args_project"] = env.app

render()
