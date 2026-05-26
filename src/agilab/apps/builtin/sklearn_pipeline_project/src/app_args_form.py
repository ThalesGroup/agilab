from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from sklearn_pipeline import SklearnPipelineArgs, dump_args, load_args  # noqa: E402


PAGE_ID = "sklearn_pipeline_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> SklearnPipelineArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load Scikit-Learn Pipeline args from `{settings_path}`: {exc}")
        return SklearnPipelineArgs()


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / env.target / "sklearn_pipeline"
st.caption(
    "Scikit-Learn Pipeline trains a deterministic local classifier and writes a "
    f"model, metrics, predictions, and hash manifest. Analysis artifacts are exported to `{artifact_root}`."
)

for key, default in (
    ("data_out", str(current_payload.get("data_out", "sklearn_pipeline/evidence") or "sklearn_pipeline/evidence")),
    ("sample_count", int(current_payload.get("sample_count", 240) or 240)),
    ("test_size", float(current_payload.get("test_size", 0.25) or 0.25)),
    ("regularization_c", float(current_payload.get("regularization_c", 1.0) or 1.0)),
    ("seed", int(current_payload.get("seed", 2026) or 2026)),
    ("reset_target", bool(current_payload.get("reset_target", False))),
):
    st.session_state.setdefault(_k(key), default)

c1, c2, c3 = st.columns([2.0, 1.2, 1.2])
with c1:
    st.text_input("Evidence directory", key=_k("data_out"))
with c2:
    st.number_input("Samples", key=_k("sample_count"), min_value=40, max_value=5000, step=20)
with c3:
    st.number_input("Seed", key=_k("seed"), min_value=0, step=1)

c4, c5, c6 = st.columns([1.2, 1.2, 1.2])
with c4:
    st.slider("Test split", key=_k("test_size"), min_value=0.10, max_value=0.50, step=0.05)
with c5:
    st.number_input("Regularization C", key=_k("regularization_c"), min_value=0.01, max_value=100.0, step=0.1)
with c6:
    st.checkbox("Reset output", key=_k("reset_target"))

candidate: dict[str, Any] = {
    "data_out": (st.session_state.get(_k("data_out")) or "").strip(),
    "sample_count": st.session_state.get(_k("sample_count"), 240),
    "test_size": st.session_state.get(_k("test_size"), 0.25),
    "regularization_c": st.session_state.get(_k("regularization_c"), 1.0),
    "seed": st.session_state.get(_k("seed"), 2026),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

try:
    validated = SklearnPipelineArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid Scikit-Learn Pipeline parameters:")
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
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    resolved_data_out = env.resolve_share_path(validated.data_out)
    expected_test_rows = max(1, round(validated.sample_count * validated.test_size))
    st.caption(
        f"Resolved evidence directory: `{resolved_data_out}`  -  "
        f"about `{expected_test_rows}` prediction rows will be written."
    )
