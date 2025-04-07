import os
import sys
import streamlit as st
import tomli
import tomli_w
from pydantic import ValidationError
import socket
import datetime
from pathlib import Path
from flight import FlightArgs

def change_data_source():
    """
    Change the data source by deleting 'path' and 'files' keys from the session state if they exist.
    """
    st.session_state.pop("path", None)
    st.session_state.pop("files", None)

def initialize_defaults(app_settings):
    """
    Initialize default parameters for the application settings.

    Args:
        app_settings (dict): A dictionary containing the application settings.

    Returns:
        dict: A dictionary containing the updated default parameters.
    """
    args_default = app_settings.get("args", {})

    defaults = {
        "data_source": "file",
        "path": (
            "data/flight"
            if args_default.get("data_source", "file") == "file"
            else f"https://admin:admin@{socket.gethostbyname(socket.gethostname())}:9200/"
        ),
        "files": (
            "*" if args_default.get("data_source", "file") == "file" else "hawk.user-admin.1"
        ),
        "nfile": 1,
        "nskip": 0,
        "nread": 0,
        "sampling_rate": 1.0,
        "datemin": "2020-01-01",
        "datemax": "2021-01-01",
        "output_format": "parquet",
    }

    for key, value in defaults.items():
        args_default.setdefault(key, value)

    app_settings["args"] = args_default
    return args_default


# Get the app settings file from the environment stored in session state
app_settings_file = st.session_state.env.app_settings_file

# Load settings using tomli (reading in binary mode)
if "is_args_from_ui" not in st.session_state:
    with open(app_settings_file, "rb") as f:
        app_settings = tomli.load(f)
    args_default = initialize_defaults(app_settings)
    st.session_state.app_settings = app_settings
else:
    app_settings = st.session_state.app_settings
    args_default = app_settings.get("args", {})
    args_default = initialize_defaults(app_settings)

result = st.session_state.env.check_args(FlightArgs, args_default)
if result:
    st.warning("\n".join(result) + f"\nplease check {app_settings_file}")
    st.session_state.pop("is_args_from_ui", None)

# Streamlit User Interface
c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1.0, 1])

with c1:
    st.selectbox(
        label="Data source",
        options=["file", "hawk"],
        key="data_source",
        on_change=change_data_source,
    )

with c2:
    if st.session_state.data_source == "file":
        st.text_input(label="Data directory", value=args_default["path"], key="path")
    else:
        st.text_input(label="Hawk cluster path", value=args_default["path"], key="path")

with c3:
    if st.session_state.data_source == "file":
        st.text_input(label="Files filter", value=args_default["files"], key="files")
    else:
        st.text_input(label="Select the pipeline", value=args_default["files"], key="files")

with c4:
    st.number_input(
        label="Number of files to read",
        value=args_default.get("nfile", 1),
        key="nfile",
        step=1,
        min_value=0,
    )

with c5:
    st.number_input(
        label="Number of line to skip",
        value=args_default.get("nskip", 0),
        key="nskip",
        step=1,
        min_value=0,
    )

c6, c7, c8, c9, c10 = st.columns([1, 1, 1, 1, 1])

with c6:
    st.number_input(
        label="Number of lines to read",
        value=args_default.get("nread", 0),
        key="nread",
        step=1,
        min_value=0,
    )

with c7:
    st.number_input(
        label="Sampling rate",
        value=args_default.get("sampling_rate", 1.0),
        key="sampling_rate",
        step=0.1,
        min_value=0.0,
    )

with c8:
    st.date_input(
        label="from Date",
        value=datetime.date.fromisoformat(args_default.get("datemin", "2020-01-01")),
        key="datemin",
    )

with c9:
    st.date_input(
        label="to Date",
        value=datetime.date.fromisoformat(args_default.get("datemax", "2021-01-01")),
        key="datemax",
    )

with c10:
    st.selectbox(
        label="Dataset output format",
        options=["parquet", "csv"],
        index=["parquet", "csv"].index(args_default.get("output_format", "parquet")),
        key="output_format",
    )

# Collect UI inputs into a dictionary and validate the path
if st.session_state.data_source == "file":
    # Expand the user path
    directory = Path(st.session_state.path).expanduser()
    if not directory.is_dir():
        st.error(f"The provided path '{directory}' is not a valid directory.")
        st.stop()
    validated_path = directory.as_posix()
else:
    validated_path = st.session_state.path

args_from_ui = {
    "data_source": st.session_state.data_source,
    "path": validated_path,
    "files": st.session_state.files,
    "nfile": st.session_state.nfile,
    "nskip": st.session_state.nskip,
    "nread": st.session_state.nread,
    "sampling_rate": st.session_state.sampling_rate,
    "datemin": st.session_state.datemin.isoformat(),
    "datemax": st.session_state.datemax.isoformat(),
    "output_format": st.session_state.output_format,
}

result = st.session_state.env.check_args(FlightArgs, args_from_ui)
if result:
    st.warning("\n".join(result))
else:
    st.success("All params are valid !")

    # Update settings if UI inputs differ from defaults
    if args_from_ui != args_default:
        st.session_state.is_args_from_ui = True
        with open(app_settings_file, "wb") as file:
            st.session_state.app_settings["args"] = args_from_ui
            tomli_w.dump(st.session_state.app_settings, file)
