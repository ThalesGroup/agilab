from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agi_env.streamlit_args import load_args_state, persist_args
from pytorch_playground import app_args
from pytorch_playground.core import ACTIVATIONS, DATASETS, OPTIMIZERS, _coerce_feature_names

APP_FORM_ID = "pytorch_playground_args"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _project_key(env: Any) -> str:
    return str(
        getattr(env, "active_app", "")
        or getattr(env, "app", "")
        or getattr(env, "target", "")
        or "pytorch_playground_project"
    )


def _field_key(env: Any, name: str) -> str:
    return f"{APP_FORM_ID}:{_project_key(env)}:{name}"


def _seed_widget_value(key: str, value: Any) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def _text_input(container: Any, env: Any, name: str, label: str, value: Any) -> str:
    key = _field_key(env, name)
    _seed_widget_value(key, str(value))
    return str(container.text_input(label, key=key))


def _checkbox(container: Any, env: Any, name: str, label: str, value: bool) -> bool:
    key = _field_key(env, name)
    _seed_widget_value(key, bool(value))
    return bool(container.checkbox(label, key=key))


def _number_input(
    container: Any,
    env: Any,
    name: str,
    label: str,
    value: int | float,
    *,
    min_value: int | float,
    max_value: int | float,
    step: int | float,
) -> int | float:
    key = _field_key(env, name)
    _seed_widget_value(key, value)
    return container.number_input(label, min_value=min_value, max_value=max_value, step=step, key=key)


def _selectbox(container: Any, env: Any, name: str, label: str, options: tuple[str, ...], value: str) -> str:
    key = _field_key(env, name)
    _seed_widget_value(key, value if value in options else options[0])
    return str(container.selectbox(label, options=options, key=key))


def _feature_names(container: Any, env: Any, value: str) -> str:
    selected = _coerce_feature_names(value)
    return _text_input(container, env, "feature_names", "Feature names", ",".join(selected))


def _render_args_form(model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any) -> dict[str, Any]:
    return {
        "data_out": _text_input(container, env, "data_out", "Data out", model.data_out),
        "dataset": _selectbox(container, env, "dataset", "Dataset", DATASETS, model.dataset),
        "sample_count": _number_input(container, env, "sample_count", "Sample count", model.sample_count, min_value=64, max_value=1000, step=16),
        "noise": _number_input(container, env, "noise", "Noise", model.noise, min_value=0.0, max_value=0.5, step=0.01),
        "train_ratio": _number_input(container, env, "train_ratio", "Train ratio", model.train_ratio, min_value=0.5, max_value=0.95, step=0.05),
        "hidden_layers": _text_input(container, env, "hidden_layers", "Hidden layers", model.hidden_layers),
        "activation": _selectbox(container, env, "activation", "Activation", ACTIVATIONS, model.activation),
        "optimizer": _selectbox(container, env, "optimizer", "Optimizer", OPTIMIZERS, model.optimizer),
        "learning_rate": _number_input(container, env, "learning_rate", "Learning rate", model.learning_rate, min_value=0.001, max_value=0.2, step=0.001),
        "epochs": _number_input(container, env, "epochs", "Epochs", model.epochs, min_value=10, max_value=300, step=10),
        "batch_size": _number_input(container, env, "batch_size", "Batch size", model.batch_size, min_value=8, max_value=256, step=8),
        "seed": _number_input(container, env, "seed", "Seed", model.seed, min_value=0, max_value=9999, step=1),
        "feature_names": _feature_names(container, env, model.feature_names),
        "grid_size": _number_input(container, env, "grid_size", "Grid size", model.grid_size, min_value=12, max_value=120, step=4),
        "compute_loss_landscape": _checkbox(container, env, "compute_loss_landscape", "Compute loss landscape", model.compute_loss_landscape),
        "landscape_resolution": _number_input(container, env, "landscape_resolution", "Landscape resolution", model.landscape_resolution, min_value=5, max_value=31, step=2),
        "landscape_span": _number_input(container, env, "landscape_span", "Landscape span", model.landscape_span, min_value=0.1, max_value=1.5, step=0.05),
        "reset_target": _checkbox(container, env, "reset_target", "Reset target", model.reset_target),
    }


env = _get_env()
defaults_model, defaults_payload, settings_path = load_args_state(env, args_module=app_args)

artifact_target = str(getattr(env, "target", "") or getattr(env, "app", "") or "pytorch_playground_project")
artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / artifact_target / "pytorch_playground"

st.caption(
    "PyTorch Playground is an executable app: ORCHESTRATE runs the configured "
    "training job and exports replayable evidence."
)
st.caption(f"Analysis artifacts are exported to `{artifact_root}`.")

with st.sidebar:
    st.markdown("### PyTorch Playground")
    st.caption("These fields are persisted as app arguments.")
    form_values = _render_args_form(defaults_model, env=env, container=st.sidebar)

try:
    parsed = app_args.ensure_defaults(app_args.ArgsModel(**form_values), env=env)
except ValidationError as exc:
    st.error("\n".join(env.humanize_validation_errors(exc)))
else:
    try:
        config = app_args.to_playground_config(parsed)
    except ValueError as exc:
        st.error(str(exc))
    else:
        persist_args(
            app_args,
            parsed,
            settings_path=settings_path,
            defaults_payload=defaults_payload,
        )
        st.code(
            json.dumps(
                {
                    "dataset": config.dataset,
                    "samples": config.sample_count,
                    "features": list(config.feature_names),
                    "hidden_layers": list(config.hidden_layers),
                    "epochs": config.epochs,
                    "loss_landscape": parsed.compute_loss_landscape,
                },
                indent=2,
                sort_keys=True,
            ),
            language="json",
        )
