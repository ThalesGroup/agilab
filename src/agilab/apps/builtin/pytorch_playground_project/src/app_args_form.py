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
    disabled: bool = False,
) -> int | float:
    key = _field_key(env, name)
    _seed_widget_value(key, value)
    return container.number_input(
        label,
        min_value=min_value,
        max_value=max_value,
        step=step,
        key=key,
        disabled=disabled,
    )


def _slider(
    container: Any,
    env: Any,
    name: str,
    label: str,
    value: int | float,
    *,
    min_value: int | float,
    max_value: int | float,
    step: int | float,
    disabled: bool = False,
) -> int | float:
    key = _field_key(env, name)
    _seed_widget_value(key, value)
    return container.slider(
        label,
        min_value=min_value,
        max_value=max_value,
        step=step,
        key=key,
        disabled=disabled,
    )


def _selectbox(container: Any, env: Any, name: str, label: str, options: tuple[str, ...], value: str) -> str:
    key = _field_key(env, name)
    _seed_widget_value(key, value if value in options else options[0])
    return str(container.selectbox(label, options=options, key=key))


def _feature_names(container: Any, env: Any, value: str) -> str:
    selected = _coerce_feature_names(value)
    return _text_input(container, env, "feature_names", "Feature names", ",".join(selected))


def _render_dataset_fields(model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any) -> dict[str, Any]:
    dataset_col, samples_col, noise_col, split_col = container.columns([1.25, 1.0, 1.0, 1.0])
    return {
        "dataset": _selectbox(dataset_col, env, "dataset", "Dataset", DATASETS, model.dataset),
        "sample_count": int(
            _slider(samples_col, env, "sample_count", "Samples", model.sample_count, min_value=64, max_value=1000, step=16)
        ),
        "noise": float(
            _slider(noise_col, env, "noise", "Noise", model.noise, min_value=0.0, max_value=0.5, step=0.01)
        ),
        "train_ratio": float(
            _slider(split_col, env, "train_ratio", "Train split", model.train_ratio, min_value=0.5, max_value=0.95, step=0.05)
        ),
    }


def _render_model_fields(model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any) -> dict[str, Any]:
    architecture_col, activation_col, optimizer_col = container.columns([1.6, 1.0, 1.0])
    training_col, batch_col, learning_col, seed_col = container.columns([1.0, 1.0, 1.15, 1.0])
    return {
        "hidden_layers": _text_input(architecture_col, env, "hidden_layers", "Hidden layers", model.hidden_layers),
        "activation": _selectbox(activation_col, env, "activation", "Activation", ACTIVATIONS, model.activation),
        "optimizer": _selectbox(optimizer_col, env, "optimizer", "Optimizer", OPTIMIZERS, model.optimizer),
        "epochs": int(
            _slider(training_col, env, "epochs", "Epochs", model.epochs, min_value=10, max_value=300, step=10)
        ),
        "batch_size": int(
            _slider(batch_col, env, "batch_size", "Batch", model.batch_size, min_value=8, max_value=256, step=8)
        ),
        "learning_rate": float(
            _number_input(
                learning_col,
                env,
                "learning_rate",
                "Learning rate",
                model.learning_rate,
                min_value=0.001,
                max_value=0.2,
                step=0.001,
            )
        ),
        "seed": int(_number_input(seed_col, env, "seed", "Seed", model.seed, min_value=0, max_value=9999, step=1)),
    }


def _render_evidence_fields(model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any) -> dict[str, Any]:
    path_col, grid_col, reset_col = container.columns([1.8, 1.0, 1.0])
    values = {
        "data_out": _text_input(path_col, env, "data_out", "Evidence path", model.data_out),
        "grid_size": int(
            _slider(grid_col, env, "grid_size", "Grid size", model.grid_size, min_value=12, max_value=120, step=4)
        ),
        "reset_target": _checkbox(reset_col, env, "reset_target", "Reset output", model.reset_target),
    }
    loss_col, resolution_col, span_col = container.columns([1.35, 1.0, 1.0])
    compute_loss_landscape = _checkbox(
        loss_col,
        env,
        "compute_loss_landscape",
        "Loss landscape",
        model.compute_loss_landscape,
    )
    values["compute_loss_landscape"] = compute_loss_landscape
    values["landscape_resolution"] = int(
        _slider(
            resolution_col,
            env,
            "landscape_resolution",
            "Resolution",
            model.landscape_resolution,
            min_value=5,
            max_value=31,
            step=2,
            disabled=not compute_loss_landscape,
        )
    )
    values["landscape_span"] = float(
        _slider(
            span_col,
            env,
            "landscape_span",
            "Span",
            model.landscape_span,
            min_value=0.1,
            max_value=1.5,
            step=0.05,
            disabled=not compute_loss_landscape,
        )
    )
    return values


def _render_wide_args_form(model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    container.markdown("#### Dataset")
    values.update(_render_dataset_fields(model, env=env, container=container))
    values["feature_names"] = _feature_names(container, env, model.feature_names)
    container.markdown("#### Model")
    values.update(_render_model_fields(model, env=env, container=container))
    container.markdown("#### Evidence")
    values.update(_render_evidence_fields(model, env=env, container=container))
    return values


def _render_sidebar_args_form(model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    container.markdown("#### Dataset")
    values.update(
        {
            "dataset": _selectbox(container, env, "dataset", "Dataset", DATASETS, model.dataset),
            "sample_count": int(
                _slider(container, env, "sample_count", "Samples", model.sample_count, min_value=64, max_value=1000, step=16)
            ),
            "noise": float(_slider(container, env, "noise", "Noise", model.noise, min_value=0.0, max_value=0.5, step=0.01)),
            "train_ratio": float(
                _slider(container, env, "train_ratio", "Train split", model.train_ratio, min_value=0.5, max_value=0.95, step=0.05)
            ),
            "feature_names": _feature_names(container, env, model.feature_names),
        }
    )
    container.markdown("#### Model")
    values.update(
        {
            "hidden_layers": _text_input(container, env, "hidden_layers", "Hidden layers", model.hidden_layers),
            "activation": _selectbox(container, env, "activation", "Activation", ACTIVATIONS, model.activation),
            "optimizer": _selectbox(container, env, "optimizer", "Optimizer", OPTIMIZERS, model.optimizer),
            "learning_rate": float(
                _number_input(
                    container,
                    env,
                    "learning_rate",
                    "Learning rate",
                    model.learning_rate,
                    min_value=0.001,
                    max_value=0.2,
                    step=0.001,
                )
            ),
            "epochs": int(_slider(container, env, "epochs", "Epochs", model.epochs, min_value=10, max_value=300, step=10)),
            "batch_size": int(_slider(container, env, "batch_size", "Batch", model.batch_size, min_value=8, max_value=256, step=8)),
            "seed": int(_number_input(container, env, "seed", "Seed", model.seed, min_value=0, max_value=9999, step=1)),
        }
    )
    container.markdown("#### Evidence")
    compute_loss_landscape = _checkbox(
        container,
        env,
        "compute_loss_landscape",
        "Loss landscape",
        model.compute_loss_landscape,
    )
    values.update(
        {
            "data_out": _text_input(container, env, "data_out", "Evidence path", model.data_out),
            "grid_size": int(_slider(container, env, "grid_size", "Grid size", model.grid_size, min_value=12, max_value=120, step=4)),
            "compute_loss_landscape": compute_loss_landscape,
            "landscape_resolution": int(
                _slider(
                    container,
                    env,
                    "landscape_resolution",
                    "Resolution",
                    model.landscape_resolution,
                    min_value=5,
                    max_value=31,
                    step=2,
                    disabled=not compute_loss_landscape,
                )
            ),
            "landscape_span": float(
                _slider(
                    container,
                    env,
                    "landscape_span",
                    "Span",
                    model.landscape_span,
                    min_value=0.1,
                    max_value=1.5,
                    step=0.05,
                    disabled=not compute_loss_landscape,
                )
            ),
            "reset_target": _checkbox(container, env, "reset_target", "Reset output", model.reset_target),
        }
    )
    return values


def _render_args_form(model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any, wide: bool = False) -> dict[str, Any]:
    if wide:
        return _render_wide_args_form(model, env=env, container=container)
    return _render_sidebar_args_form(model, env=env, container=container)


def render(*, env: Any | None = None, container: Any | None = None) -> None:
    active_env = env or _get_env()
    defaults_model, defaults_payload, settings_path = load_args_state(active_env, args_module=app_args)

    artifact_target = str(getattr(active_env, "target", "") or getattr(active_env, "app", "") or "pytorch_playground_project")
    artifact_root = (
        Path(getattr(active_env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
        / artifact_target
        / "pytorch_playground"
    )
    output_container = container or st
    output_container.caption(
        "PyTorch Playground is an executable app: ORCHESTRATE runs the configured "
        "training job and exports replayable evidence."
    )
    output_container.caption(f"Analysis artifacts are exported to `{artifact_root}`.")

    form_container = container or st.sidebar
    if container is None:
        with st.sidebar:
            st.markdown("### PyTorch Playground")
            st.caption("These fields are persisted as app arguments.")
            form_values = _render_args_form(defaults_model, env=active_env, container=st.sidebar)
    else:
        form_container.markdown("### PyTorch Playground")
        form_container.caption("These fields are persisted as app arguments.")
        form_values = _render_args_form(defaults_model, env=active_env, container=form_container, wide=True)

    try:
        parsed = app_args.ensure_defaults(app_args.ArgsModel(**form_values), env=active_env)
    except ValidationError as exc:
        output_container.error("\n".join(active_env.humanize_validation_errors(exc)))
    else:
        try:
            config = app_args.to_playground_config(parsed)
        except ValueError as exc:
            output_container.error(str(exc))
        else:
            persist_args(
                app_args,
                parsed,
                settings_path=settings_path,
                defaults_payload=defaults_payload,
            )
            output_container.code(
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


if not globals().get("_AGILAB_APP_ARGS_FORM_IMPORT_ONLY", False):
    render(env=globals().get("env"))
