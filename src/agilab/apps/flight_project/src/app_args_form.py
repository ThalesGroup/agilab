from pathlib import Path
from typing import Any

import streamlit as st
import tomli
from pydantic import ValidationError

from agi_env.pagelib import diagnose_data_directory
from agi_env.streamlit_args import render_form
from flight import FlightArgs, apply_source_defaults, dump_args_to_toml

PREFIX = "flight_"


def load_app_settings(path: Path) -> dict[str, Any]:
    if path.exists():
        with path.open("rb") as handle:
            return tomli.load(handle)
    return {}


def _ensure_streamlit_context() -> Any | None:
    return st.session_state.get("_env")


def render() -> None:
    env = _ensure_streamlit_context()
    if env is None:
        return

    settings_path = Path(env.app_settings_file)

    app_settings = st.session_state.get("app_settings")
    if not app_settings or not st.session_state.get("is_args_from_ui"):
        app_settings = load_app_settings(settings_path)
        st.session_state.app_settings = app_settings

    try:
        stored_args = FlightArgs(**dict(app_settings.get("args", {})))
    except ValidationError as exc:
        st.warning("\n".join(env.humanize_validation_errors(exc)) + f"\nplease check {settings_path}")
        st.session_state.pop("is_args_from_ui", None)
        stored_args = FlightArgs()

    defaults_model = apply_source_defaults(stored_args)
    defaults_payload = defaults_model.to_toml_payload()
    st.session_state.app_settings["args"] = defaults_payload

    if st.session_state.get("toggle_edit", True):
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1.0, 1, 1])

        with c1:
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
                help=f"Manager workers read from {env.agi_share_dir}/<your path> when running locally.",
            )

        with c3:
            data_out = st.text_input(
                "Outputs dir",
                value=str(defaults_model.data_out),
                key=f"{PREFIX}data_out",
                help=f"Outputs will be written under {env.agi_share_dir}/<your path>.",
            )

        with c4:
            files = st.text_input(
                "Files filter" if data_source == "file" else "Select the pipeline",
                value=defaults_model.files,
                key=f"{PREFIX}files",
            )

        with c5:
            nfile = st.number_input(
                "Number of files to read",
                value=defaults_model.nfile,
                key=f"{PREFIX}nfile",
                step=1,
                min_value=0,
            )

        with c6:
            nskip = st.number_input(
                "Number of line to skip",
                value=defaults_model.nskip,
                key=f"{PREFIX}nskip",
                step=1,
                min_value=0,
            )

        c6, c7, c8, c9, c10 = st.columns([1, 1, 1, 1, 1])

        with c6:
            nread = st.number_input(
                "Number of lines to read",
                value=defaults_model.nread,
                key=f"{PREFIX}nread",
                step=1,
                min_value=0,
            )

        with c7:
            sampling_rate = st.number_input(
                "Sampling rate",
                value=defaults_model.sampling_rate,
                key=f"{PREFIX}sampling_rate",
                step=0.1,
                min_value=0.0,
            )

        with c8:
            datemin = st.date_input("from Date", value=defaults_model.datemin, key=f"{PREFIX}datemin")

        with c9:
            datemax = st.date_input("to Date", value=defaults_model.datemax, key=f"{PREFIX}datemax")

        with c10:
            output_format = st.selectbox(
                "Dataset output format",
                options=["parquet", "csv"],
                index=["parquet", "csv"].index(defaults_model.output_format),
                key=f"{PREFIX}output_format",
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
            "data_out": data_out,
            "files": files,
            "nfile": int(nfile),
            "nskip": int(nskip),
            "nread": int(nread),
            "sampling_rate": float(sampling_rate),
            "datemin": datemin,
            "datemax": datemax,
            "output_format": output_format,
        }
    else:
        candidate_args = render_form(defaults_model)

    try:
        parsed_args = FlightArgs(**candidate_args)
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
