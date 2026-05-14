from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from meteo_forecast import MeteoForecastArgs, dump_args, load_args


PAGE_ID = "weather_forecast_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILab environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> MeteoForecastArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load Weather Forecast args from `{settings_path}`: {exc}")
        return MeteoForecastArgs()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

try:
    share_root = env.share_root_path()
except Exception:
    share_root = None

artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / env.target / "forecast_analysis"

st.caption(
    "This app turns the notebook migration pilot into a reproducible AGILAB workflow. "
    "Input and output paths are resolved under shared storage, while analysis artifacts are "
    f"exported to `{artifact_root}`."
)
if share_root:
    st.caption(f"Current shared root: `{share_root}`")

st.session_state.setdefault(_k("data_in"), str(current_payload.get("data_in", "") or ""))
st.session_state.setdefault(_k("data_out"), str(current_payload.get("data_out", "") or ""))
st.session_state.setdefault(_k("files"), str(current_payload.get("files", "*.csv") or "*.csv"))
st.session_state.setdefault(_k("nfile"), int(current_payload.get("nfile", 1) or 1))
st.session_state.setdefault(_k("station"), str(current_payload.get("station", "Paris-Montsouris") or "Paris-Montsouris"))
st.session_state.setdefault(_k("target_column"), str(current_payload.get("target_column", "tmax_c") or "tmax_c"))
st.session_state.setdefault(_k("lags"), int(current_payload.get("lags", 7) or 7))
st.session_state.setdefault(_k("horizon_days"), int(current_payload.get("horizon_days", 7) or 7))
st.session_state.setdefault(_k("validation_days"), int(current_payload.get("validation_days", 9) or 9))
st.session_state.setdefault(_k("n_estimators"), int(current_payload.get("n_estimators", 100) or 100))
st.session_state.setdefault(_k("random_state"), int(current_payload.get("random_state", 42) or 42))
st.session_state.setdefault(_k("reset_target"), bool(current_payload.get("reset_target", False)))

c1, c2, c3, c4 = st.columns([2, 2, 1.2, 1.2])
with c1:
    st.text_input("Dataset directory", key=_k("data_in"))
with c2:
    st.text_input("Results directory", key=_k("data_out"))
with c3:
    st.text_input("Files glob", key=_k("files"))
with c4:
    st.number_input("Number of files", key=_k("nfile"), min_value=1, step=1)

c5, c6, c7 = st.columns([2, 1.2, 1.2])
with c5:
    st.text_input("Station", key=_k("station"))
with c6:
    st.selectbox("Target", options=["tmax_c", "tmoy_c", "tmin_c"], key=_k("target_column"))
with c7:
    st.checkbox("Reset output", key=_k("reset_target"))

c8, c9, c10, c11 = st.columns([1.1, 1.1, 1.1, 1.1])
with c8:
    st.number_input("Lags", key=_k("lags"), min_value=1, max_value=30, step=1)
with c9:
    st.number_input("Horizon days", key=_k("horizon_days"), min_value=1, max_value=30, step=1)
with c10:
    st.number_input("Validation days", key=_k("validation_days"), min_value=7, max_value=120, step=1)
with c11:
    st.number_input("Trees", key=_k("n_estimators"), min_value=10, max_value=500, step=10)

st.number_input("Random state", key=_k("random_state"), min_value=0, step=1)

candidate: dict[str, Any] = {
    "files": (st.session_state.get(_k("files")) or "*.csv").strip() or "*.csv",
    "nfile": st.session_state.get(_k("nfile"), 1),
    "station": (st.session_state.get(_k("station")) or "").strip(),
    "target_column": st.session_state.get(_k("target_column")) or "tmax_c",
    "lags": st.session_state.get(_k("lags"), 7),
    "horizon_days": st.session_state.get(_k("horizon_days"), 7),
    "validation_days": st.session_state.get(_k("validation_days"), 9),
    "n_estimators": st.session_state.get(_k("n_estimators"), 100),
    "random_state": st.session_state.get(_k("random_state"), 42),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

data_in_raw = (st.session_state.get(_k("data_in")) or "").strip()
data_out_raw = (st.session_state.get(_k("data_out")) or "").strip()
if data_in_raw:
    candidate["data_in"] = data_in_raw
if data_out_raw:
    candidate["data_out"] = data_out_raw

try:
    validated = MeteoForecastArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid Weather Forecast parameters:")
    if hasattr(env, "humanize_validation_errors"):
        for msg in env.humanize_validation_errors(exc):
            st.markdown(msg)
    else:
        st.code(str(exc))
else:
    validated_payload = validated.model_dump(mode="json")
    if validated_payload != current_payload:
        dump_args(validated, settings_path)
        app_settings = st.session_state.get("app_settings")
        if not isinstance(app_settings, dict):
            app_settings = {}
        app_settings.setdefault("cluster", {})
        app_settings["args"] = validated_payload
        app_settings.setdefault("pages", {})
        app_settings["pages"]["view_module"] = ["view_forecast_analysis"]
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    resolved_data_in = env.resolve_share_path(validated.data_in)
    resolved_data_out = env.resolve_share_path(validated.data_out)
    if not any(resolved_data_in.glob(validated.files)):
        st.info("No matching CSV file exists yet in the dataset directory. The bundled sample will be seeded on first run.")
    st.caption(
        f"Resolved input: `{resolved_data_in}`  •  results: `{resolved_data_out}`  •  "
        f"analysis artifacts: `{artifact_root}`"
    )
