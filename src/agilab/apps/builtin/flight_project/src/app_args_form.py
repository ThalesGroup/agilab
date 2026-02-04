from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st
from pydantic import ValidationError

from flight import FlightArgs, apply_source_defaults, dump_args_to_toml, load_args_from_toml


PAGE_ID = "flight_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILab environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _parse_iso_date(value: Any, *, fallback: date) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return fallback
    return fallback


def _load_current_args(settings_path: Path) -> FlightArgs:
    try:
        stored = load_args_from_toml(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load Flight args from `{settings_path}`: {exc}")
        return apply_source_defaults(FlightArgs())
    return apply_source_defaults(stored)


def _on_data_source_change() -> None:
    data_source = (st.session_state.get(_k("data_source")) or "file").strip() or "file"
    try:
        defaults = apply_source_defaults(FlightArgs(data_source=data_source))
    except Exception:
        return
    payload = defaults.to_toml_payload()
    st.session_state[_k("data_in")] = str(payload.get("data_in", "") or "")
    st.session_state[_k("files")] = str(payload.get("files", "") or "")
    st.session_state[_k("data_out")] = ""


env = _get_env()
settings_path = Path(env.app_settings_file)

current_args = _load_current_args(settings_path)
current_payload = current_args.to_toml_payload()

try:
    share_root = env.share_root_path()
except Exception:
    share_root = None

st.caption(
    "Paths are resolved relative to `AGI_SHARE_DIR` (shared storage)."
    + (f" Current share root: `{share_root}`." if share_root else "")
)

# Seed widget state once (never write to widget keys after instantiation)
st.session_state.setdefault(_k("data_source"), str(current_payload.get("data_source", "file") or "file"))
st.session_state.setdefault(_k("data_in"), str(current_payload.get("data_in", "") or ""))
st.session_state.setdefault(_k("data_out"), str(current_payload.get("data_out", "") or ""))
st.session_state.setdefault(_k("files"), str(current_payload.get("files", "*") or "*"))
st.session_state.setdefault(_k("nfile"), int(current_payload.get("nfile", 1) or 1))
st.session_state.setdefault(_k("nskip"), int(current_payload.get("nskip", 0) or 0))
st.session_state.setdefault(_k("nread"), int(current_payload.get("nread", 0) or 0))
st.session_state.setdefault(_k("sampling_rate"), float(current_payload.get("sampling_rate", 1.0) or 1.0))
st.session_state.setdefault(
    _k("datemin"),
    _parse_iso_date(current_payload.get("datemin"), fallback=date(2020, 1, 1)),
)
st.session_state.setdefault(
    _k("datemax"),
    _parse_iso_date(current_payload.get("datemax"), fallback=date(2021, 1, 1)),
)
st.session_state.setdefault(_k("output_format"), str(current_payload.get("output_format", "parquet") or "parquet"))
st.session_state.setdefault(_k("reset_target"), bool(current_payload.get("reset_target", False)))

# --- UI
c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 1.2, 1.2])
with c1:
    st.selectbox(
        "Data source",
        options=["file", "hawk"],
        key=_k("data_source"),
        on_change=_on_data_source_change,
    )
with c2:
    data_source = (st.session_state.get(_k("data_source")) or "file").strip() or "file"
    st.text_input(
        "Data directory" if data_source == "file" else "Hawk cluster URI",
        key=_k("data_in"),
        help="Relative path under shared storage (file) or a Hawk/ELK endpoint (hawk).",
    )
with c3:
    st.text_input(
        "Files filter" if data_source == "file" else "Pipeline name",
        key=_k("files"),
        help="Regex or wildcard (e.g. `*`), depending on the pipeline.",
    )
with c4:
    st.number_input(
        "Number of files to read",
        key=_k("nfile"),
        step=1,
        min_value=0,
        help="Use 0 for “all files” (may be persisted as a large number internally).",
    )
with c5:
    st.number_input(
        "Number of lines to skip",
        key=_k("nskip"),
        step=1,
        min_value=0,
    )

c6, c7, c8, c9, c10 = st.columns([1.2, 1.2, 1.5, 1.5, 1.2])
with c6:
    st.number_input(
        "Number of lines to read",
        key=_k("nread"),
        step=1,
        min_value=0,
    )
with c7:
    st.number_input(
        "Sampling rate",
        key=_k("sampling_rate"),
        step=0.1,
        min_value=0.0,
    )
with c8:
    st.date_input("from Date", key=_k("datemin"))
with c9:
    st.date_input("to Date", key=_k("datemax"))
with c10:
    st.selectbox("Dataset output format", options=["parquet", "csv"], key=_k("output_format"))

c11, c12 = st.columns([3, 1])
with c11:
    st.text_input(
        "Output directory (optional)",
        key=_k("data_out"),
        help="Defaults to `data_in/../dataframe` when left empty.",
    )
with c12:
    st.checkbox(
        "Reset output",
        key=_k("reset_target"),
        help="Delete the output directory before writing the dataframe.",
    )

# --- Validate + persist
data_in_raw = (st.session_state.get(_k("data_in")) or "").strip()
data_out_raw = (st.session_state.get(_k("data_out")) or "").strip()

candidate: dict[str, Any] = {
    "data_source": (st.session_state.get(_k("data_source")) or "file").strip() or "file",
    "files": st.session_state.get(_k("files")) or "",
    "nfile": st.session_state.get(_k("nfile"), 1),
    "nskip": st.session_state.get(_k("nskip"), 0),
    "nread": st.session_state.get(_k("nread"), 0),
    "sampling_rate": st.session_state.get(_k("sampling_rate"), 1.0),
    "datemin": st.session_state.get(_k("datemin")),
    "datemax": st.session_state.get(_k("datemax")),
    "output_format": st.session_state.get(_k("output_format")) or "parquet",
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}
if data_in_raw:
    candidate["data_in"] = data_in_raw
if data_out_raw:
    candidate["data_out"] = data_out_raw

try:
    validated = FlightArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid Flight parameters:")
    if hasattr(env, "humanize_validation_errors"):
        for msg in env.humanize_validation_errors(exc):
            st.markdown(msg)
    else:
        st.code(str(exc))
else:
    validated = apply_source_defaults(validated)
    validated_payload = validated.to_toml_payload()

    if validated_payload != current_payload:
        dump_args_to_toml(validated, settings_path)
        app_settings = st.session_state.get("app_settings")
        if not isinstance(app_settings, dict):
            app_settings = {}
        app_settings.setdefault("cluster", {})
        app_settings["args"] = validated_payload
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    if validated.data_source == "file":
        resolved_data_in = env.resolve_share_path(validated.data_in)
        resolved_data_out = env.resolve_share_path(validated.data_out)
        if not resolved_data_in.exists():
            st.warning(f"Input directory does not exist: `{resolved_data_in}`")
        st.caption(f"Resolved input: `{resolved_data_in}`  •  output: `{resolved_data_out}`")
