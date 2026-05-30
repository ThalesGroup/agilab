from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agi_env.streamlit_args import load_args_state, persist_args  # noqa: E402
from pytorch_playground import app_args  # noqa: E402
from pytorch_playground.core import (  # noqa: E402
    ACTIVATIONS,
    DATASETS,
    DEFAULT_FEATURES,
    FEATURES,
    OPTIMIZERS,
    REGULARIZATIONS,
    _coerce_feature_names,
)

APP_FORM_ID = "pytorch_playground_args"


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    section: str
    widget: str
    value_type: str = "str"
    options: tuple[str, ...] = ()
    min_value: int | float | None = None
    max_value: int | float | None = None
    step: int | float | None = None
    wide_row: str = "main"
    wide_weight: float = 1.0
    compact_group: str = "primary"
    disabled_unless: str | None = None


FORM_FIELDS: tuple[FormField, ...] = (
    FormField(
        "dataset",
        "Dataset",
        "Dataset",
        "selectbox",
        options=DATASETS,
        wide_row="dataset",
        wide_weight=1.25,
    ),
    FormField(
        "sample_count",
        "Samples",
        "Dataset",
        "slider",
        value_type="int",
        min_value=64,
        max_value=1000,
        step=16,
        wide_row="dataset",
    ),
    FormField(
        "noise",
        "Noise",
        "Dataset",
        "slider",
        value_type="float",
        min_value=0.0,
        max_value=0.5,
        step=0.01,
        wide_row="dataset",
    ),
    FormField(
        "train_ratio",
        "Train split",
        "Dataset",
        "slider",
        value_type="float",
        min_value=0.5,
        max_value=0.95,
        step=0.05,
        wide_row="dataset",
        compact_group="Advanced model",
    ),
    FormField(
        "feature_names",
        "Feature names",
        "Dataset",
        "feature_names",
        wide_row="features",
        compact_group="Advanced model",
    ),
    FormField(
        "hidden_layers",
        "Hidden layers",
        "Model",
        "text_input",
        wide_row="architecture",
        wide_weight=1.6,
        compact_group="Advanced model",
    ),
    FormField(
        "activation",
        "Activation",
        "Model",
        "selectbox",
        options=ACTIVATIONS,
        wide_row="architecture",
        compact_group="Advanced model",
    ),
    FormField(
        "optimizer",
        "Optimizer",
        "Model",
        "selectbox",
        options=OPTIMIZERS,
        wide_row="architecture",
        compact_group="Advanced model",
    ),
    FormField(
        "regularization",
        "Regularization",
        "Model",
        "selectbox",
        options=REGULARIZATIONS,
        wide_row="regularization",
        compact_group="Advanced model",
    ),
    FormField(
        "regularization_rate",
        "Regularization rate",
        "Model",
        "number_input",
        value_type="float",
        min_value=0.0,
        max_value=1.0,
        step=0.001,
        wide_row="regularization",
        compact_group="Advanced model",
        disabled_unless="regularization",
    ),
    FormField(
        "epochs",
        "Epochs",
        "Model",
        "slider",
        value_type="int",
        min_value=10,
        max_value=300,
        step=10,
        wide_row="training",
    ),
    FormField(
        "batch_size",
        "Batch",
        "Model",
        "slider",
        value_type="int",
        min_value=8,
        max_value=256,
        step=8,
        wide_row="training",
        compact_group="Advanced model",
    ),
    FormField(
        "learning_rate",
        "Learning rate",
        "Model",
        "number_input",
        value_type="float",
        min_value=0.001,
        max_value=0.2,
        step=0.001,
        wide_row="training",
        wide_weight=1.15,
        compact_group="Advanced model",
    ),
    FormField(
        "seed",
        "Seed",
        "Model",
        "number_input",
        value_type="int",
        min_value=0,
        max_value=9999,
        step=1,
        wide_row="training",
        compact_group="Advanced model",
    ),
    FormField(
        "data_out",
        "Evidence path",
        "Evidence",
        "text_input",
        wide_row="output",
        wide_weight=1.8,
        compact_group="Evidence",
    ),
    FormField(
        "grid_size",
        "Grid size",
        "Evidence",
        "slider",
        value_type="int",
        min_value=12,
        max_value=120,
        step=4,
        wide_row="output",
        compact_group="Evidence",
    ),
    FormField(
        "reset_target",
        "Reset output",
        "Evidence",
        "checkbox",
        value_type="bool",
        wide_row="output",
        compact_group="Evidence",
    ),
    FormField(
        "compute_loss_landscape",
        "Loss landscape",
        "Evidence",
        "checkbox",
        value_type="bool",
        wide_row="landscape",
        wide_weight=1.35,
        compact_group="Evidence",
    ),
    FormField(
        "landscape_resolution",
        "Resolution",
        "Evidence",
        "slider",
        value_type="int",
        min_value=5,
        max_value=31,
        step=2,
        wide_row="landscape",
        compact_group="Evidence",
        disabled_unless="compute_loss_landscape",
    ),
    FormField(
        "landscape_span",
        "Span",
        "Evidence",
        "slider",
        value_type="float",
        min_value=0.1,
        max_value=1.5,
        step=0.05,
        wide_row="landscape",
        compact_group="Evidence",
        disabled_unless="compute_loss_landscape",
    ),
)


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error(
            "AGILAB environment is not initialised yet. Return to the main page and try again."
        )
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


def _selectbox(
    container: Any,
    env: Any,
    name: str,
    label: str,
    options: tuple[str, ...],
    value: str,
) -> str:
    key = _field_key(env, name)
    _seed_widget_value(key, value if value in options else options[0])
    return str(container.selectbox(label, options=options, key=key))


def _feature_names(container: Any, env: Any, name: str, label: str, value: str) -> str:
    selected = _coerce_feature_names(value)
    if not selected:
        selected = DEFAULT_FEATURES
    key = _field_key(env, name)
    if key not in st.session_state:
        st.session_state[key] = list(selected)
    rendered = container.multiselect(label, FEATURES, key=key)
    chosen = _coerce_feature_names(rendered, default=DEFAULT_FEATURES)
    return ",".join(chosen)


def _state_value(env: Any, name: str, fallback: Any) -> Any:
    return st.session_state.get(_field_key(env, name), fallback)


def _current_form_values(
    model: app_args.PytorchPlaygroundArgs, *, env: Any
) -> dict[str, Any]:
    return {
        field.name: _state_value(env, field.name, getattr(model, field.name))
        for field in FORM_FIELDS
    }


def persist_current_args(*, env: Any | None = None) -> app_args.PytorchPlaygroundArgs:
    active_env = env or _get_env()
    defaults_model, defaults_payload, settings_path = load_args_state(
        active_env, args_module=app_args
    )
    parsed = app_args.ensure_defaults(
        app_args.ArgsModel(**_current_form_values(defaults_model, env=active_env)),
        env=active_env,
    )
    persist_args(
        app_args,
        parsed,
        settings_path=settings_path,
        defaults_payload=defaults_payload,
    )
    return parsed


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _json_load_expr(value: Any) -> str:
    literal = json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)
    return f"json.loads({literal!r})"


def _python_string(value: Any) -> str:
    return json.dumps(str(value))


def _active_app_name(env: Any) -> str:
    app = str(getattr(env, "app", "") or "").strip()
    if app:
        return app
    active_app = getattr(env, "active_app", None)
    if active_app not in (None, ""):
        try:
            return Path(active_app).name
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    return "pytorch_playground_project"


def _snippet_apps_path(env: Any) -> str:
    active_app = getattr(env, "active_app", None)
    if active_app not in (None, ""):
        try:
            active_path = Path(active_app)
        except (OSError, RuntimeError, TypeError, ValueError):
            active_path = None
        if active_path is not None and active_path.name == _active_app_name(env):
            return str(active_path.parent)
    return str(getattr(env, "apps_path", "") or "")


def _cluster_settings() -> dict[str, Any]:
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        return {}
    cluster = app_settings.get("cluster", {})
    return dict(cluster) if isinstance(cluster, dict) else {}


def _coerce_verbose(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _run_mode(cluster: dict[str, Any], *, cluster_enabled: bool) -> int:
    session_mode = st.session_state.get("mode")
    if isinstance(session_mode, int):
        return session_mode
    return (
        int(bool(cluster.get("pool", False)))
        + int(bool(cluster.get("cython", False))) * 2
        + int(cluster_enabled) * 4
        + int(bool(cluster.get("rapids", False))) * 8
    )


def _optional_string_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, ""):
        return "None"
    return _python_string(value)


def _optional_python_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, "", {}, []):
        return "None"
    return repr(value)


def _split_run_request_payload(
    run_args: dict[str, Any],
) -> tuple[dict[str, Any], list[Any], Any, Any, bool | None]:
    payload = dict(run_args)
    stages = payload.pop("stages", [])
    if "args" in payload:
        stages = payload.pop("args")
    if stages is None:
        stages = []
    data_in = payload.pop("data_in", None)
    data_out = payload.pop("data_out", None)
    reset_target = payload.pop("reset_target", None)
    return (
        payload,
        list(stages) if isinstance(stages, list) else [],
        data_in,
        data_out,
        reset_target,
    )


def _fallback_run_snippet(*, env: Any, run_args: dict[str, Any]) -> str:
    cluster = _cluster_settings()
    cluster_enabled = bool(cluster.get("cluster_enabled", False))
    params, stages, data_in, data_out, reset_target = _split_run_request_payload(
        run_args
    )
    snippet_lines = [
        "import asyncio",
        "import json",
        "",
        "from agi_cluster.agi_distributor import AGI, RunRequest, StageRequest",
        "from agi_env import AgiEnv",
        "",
        f"APPS_PATH = {_python_string(_snippet_apps_path(env))}",
        f"APP = {_python_string(_active_app_name(env))}",
        f"RUN_PARAMS = {_json_load_expr(params)}",
        f"RUN_STAGES_PAYLOAD = {_json_load_expr(stages)}",
        f"RUN_DATA_IN = {_json_load_expr(data_in)}",
        f"RUN_DATA_OUT = {_json_load_expr(data_out)}",
        f"RUN_RESET_TARGET = {_json_load_expr(reset_target)}",
        "",
        "async def main():",
        f"    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={_coerce_verbose(cluster.get('verbose', 1))})",
        "    run_stages = [",
        "        StageRequest(name=stage['name'], args=stage.get('args') or {})",
        "        for stage in RUN_STAGES_PAYLOAD",
        "    ]",
        "    request = RunRequest(",
        "        params=RUN_PARAMS,",
        "        stages=run_stages,",
        "        data_in=RUN_DATA_IN,",
        "        data_out=RUN_DATA_OUT,",
        "        reset_target=RUN_RESET_TARGET,",
        f"        mode={_run_mode(cluster, cluster_enabled=cluster_enabled)!r},",
        f"        scheduler={_optional_string_expr(cluster_enabled, cluster.get('scheduler'))},",
        f"        workers={_optional_python_expr(cluster_enabled, cluster.get('workers'))},",
        f"        workers_data_path={_optional_string_expr(cluster_enabled, cluster.get('workers_data_path'))},",
        f"        rapids_enabled={bool(cluster.get('rapids', False))!r},",
        "    )",
        "    res = await AGI.run(app_env, request=request)",
        "    print(res)",
        "    return res",
        "",
        'if __name__ == "__main__":',
        "    asyncio.run(main())",
    ]
    return "\n".join(snippet_lines).strip()


def _build_synced_run_snippet(
    parsed: app_args.PytorchPlaygroundArgs, *, env: Any
) -> str:
    run_args = dict(parsed.model_dump(mode="json"))
    cluster = _cluster_settings()
    cluster_enabled = bool(cluster.get("cluster_enabled", False))
    try:
        from agilab.orchestrate_page_support import build_run_snippet

        return build_run_snippet(
            env=env,
            verbose=_coerce_verbose(cluster.get("verbose", 1)),
            run_mode=_run_mode(cluster, cluster_enabled=cluster_enabled),
            scheduler=_optional_string_expr(cluster_enabled, cluster.get("scheduler")),
            workers=_optional_python_expr(cluster_enabled, cluster.get("workers")),
            workers_data_path=_optional_string_expr(
                cluster_enabled, cluster.get("workers_data_path")
            ),
            rapids_enabled=bool(cluster.get("rapids", False)),
            benchmark_best_single_node=False,
            run_args=run_args,
        )
    except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return _fallback_run_snippet(env=env, run_args=run_args)


def _store_synced_run_snippet(env: Any, snippet: str) -> None:
    key = f"orchestrate:notebook_snippet:{_active_app_name(env)}:run"
    st.session_state[key] = snippet


def _render_synced_run_snippet(
    container: Any, *, env: Any, parsed: app_args.PytorchPlaygroundArgs, compact: bool
) -> None:
    snippet = _build_synced_run_snippet(parsed, env=env)
    _store_synced_run_snippet(env, snippet)
    label = "Synced RUN snippet" if compact else "Generated RUN snippet"
    with container.expander(label, expanded=False) as snippet_container:
        snippet_container.code(snippet, language="python")


def _coerce_field_value(field: FormField, value: Any) -> Any:
    if field.value_type == "bool":
        return bool(value)
    if field.value_type == "int":
        return int(value)
    if field.value_type == "float":
        return float(value)
    return value


def _field_disabled(
    field: FormField,
    values: dict[str, Any],
    model: app_args.PytorchPlaygroundArgs,
    *,
    env: Any,
) -> bool:
    if field.disabled_unless is None:
        return False
    if field.disabled_unless == "regularization":
        return str(values.get("regularization", getattr(model, "regularization", "None"))) == "None"
    fallback = getattr(model, field.disabled_unless)
    return not bool(
        values.get(
            field.disabled_unless, _state_value(env, field.disabled_unless, fallback)
        )
    )


def _render_form_field(
    field: FormField,
    model: app_args.PytorchPlaygroundArgs,
    *,
    env: Any,
    container: Any,
    values: dict[str, Any],
) -> Any:
    value = getattr(model, field.name)
    disabled = _field_disabled(field, values, model, env=env)
    if field.widget == "selectbox":
        rendered = _selectbox(
            container, env, field.name, field.label, field.options, value
        )
    elif field.widget == "slider":
        rendered = _slider(
            container,
            env,
            field.name,
            field.label,
            value,
            min_value=field.min_value,
            max_value=field.max_value,
            step=field.step,
            disabled=disabled,
        )
    elif field.widget == "number_input":
        rendered = _number_input(
            container,
            env,
            field.name,
            field.label,
            value,
            min_value=field.min_value,
            max_value=field.max_value,
            step=field.step,
            disabled=disabled,
        )
    elif field.widget == "checkbox":
        rendered = _checkbox(container, env, field.name, field.label, value)
    elif field.widget == "feature_names":
        rendered = _feature_names(container, env, field.name, field.label, value)
    else:
        rendered = _text_input(container, env, field.name, field.label, value)
    return _coerce_field_value(field, rendered)


def _fields_for_section(section: str) -> list[FormField]:
    return [field for field in FORM_FIELDS if field.section == section]


def _fields_for_compact_group(group: str) -> list[FormField]:
    return [field for field in FORM_FIELDS if field.compact_group == group]


def _form_sections() -> list[str]:
    return list(dict.fromkeys(field.section for field in FORM_FIELDS))


def _compact_expander_groups() -> list[str]:
    return list(
        dict.fromkeys(
            field.compact_group
            for field in FORM_FIELDS
            if field.compact_group != "primary"
        )
    )


def _render_stacked_fields(
    fields: list[FormField],
    model: app_args.PytorchPlaygroundArgs,
    *,
    env: Any,
    container: Any,
    values: dict[str, Any],
) -> None:
    for field in fields:
        values[field.name] = _render_form_field(
            field, model, env=env, container=container, values=values
        )


def _render_field_row(
    fields: list[FormField],
    model: app_args.PytorchPlaygroundArgs,
    *,
    env: Any,
    container: Any,
    values: dict[str, Any],
) -> None:
    if len(fields) == 1:
        _render_stacked_fields(
            fields, model, env=env, container=container, values=values
        )
        return
    columns = container.columns([field.wide_weight for field in fields])
    for column, field in zip(columns, fields, strict=False):
        values[field.name] = _render_form_field(
            field, model, env=env, container=column, values=values
        )


def _render_section_fields(
    section: str,
    model: app_args.PytorchPlaygroundArgs,
    *,
    env: Any,
    container: Any,
    values: dict[str, Any],
    columns: bool,
) -> None:
    fields = _fields_for_section(section)
    if not columns:
        _render_stacked_fields(
            fields, model, env=env, container=container, values=values
        )
        return
    rows: dict[str, list[FormField]] = {}
    for field in fields:
        rows.setdefault(field.wide_row, []).append(field)
    for row_fields in rows.values():
        _render_field_row(
            row_fields, model, env=env, container=container, values=values
        )


def _render_wide_args_form(
    model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for section in _form_sections():
        container.markdown(f"#### {section}")
        _render_section_fields(
            section, model, env=env, container=container, values=values, columns=True
        )
    return values


def _render_compact_args_form(
    model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    _render_stacked_fields(
        _fields_for_compact_group("primary"),
        model,
        env=env,
        container=container,
        values=values,
    )
    for group in _compact_expander_groups():
        with container.expander(group, expanded=False) as group_container:
            _render_stacked_fields(
                _fields_for_compact_group(group),
                model,
                env=env,
                container=group_container,
                values=values,
            )
    return values


def _render_sidebar_args_form(
    model: app_args.PytorchPlaygroundArgs, *, env: Any, container: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for section in _form_sections():
        container.markdown(f"#### {section}")
        _render_section_fields(
            section, model, env=env, container=container, values=values, columns=False
        )
    return values


def _render_args_form(
    model: app_args.PytorchPlaygroundArgs,
    *,
    env: Any,
    container: Any,
    wide: bool = False,
) -> dict[str, Any]:
    if wide:
        return _render_wide_args_form(model, env=env, container=container)
    return _render_sidebar_args_form(model, env=env, container=container)


def render(
    *,
    env: Any | None = None,
    container: Any | None = None,
    wide: bool | None = None,
    compact: bool = False,
) -> None:
    active_env = env or _get_env()
    defaults_model, defaults_payload, settings_path = load_args_state(
        active_env, args_module=app_args
    )

    artifact_target = str(
        getattr(active_env, "target", "")
        or getattr(active_env, "app", "")
        or "pytorch_playground_project"
    )
    artifact_root = (
        Path(getattr(active_env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
        / artifact_target
        / "pytorch_playground"
    )
    output_container = container or st
    if not compact:
        output_container.caption(
            "PyTorch Playground is an executable app: ORCHESTRATE runs the configured "
            "training job and exports replayable evidence."
        )
        output_container.caption(
            f"Analysis artifacts are exported to `{artifact_root}`."
        )
    snippet_rendered = False
    if compact and container is not None:
        try:
            current_parsed = app_args.ensure_defaults(
                app_args.ArgsModel(
                    **_current_form_values(defaults_model, env=active_env)
                ),
                env=active_env,
            )
        except ValidationError:
            pass
        else:
            _render_synced_run_snippet(
                output_container, env=active_env, parsed=current_parsed, compact=True
            )
            snippet_rendered = True

    form_container = container or st.sidebar
    use_wide_form = container is not None if wide is None else wide
    if container is None:
        with st.sidebar:
            st.markdown("### PyTorch Playground")
            st.caption("These fields are persisted as app arguments.")
            form_values = _render_args_form(
                defaults_model, env=active_env, container=st.sidebar
            )
    else:
        if compact:
            form_container.markdown("**Settings**")
            form_values = _render_compact_args_form(
                defaults_model, env=active_env, container=form_container
            )
        else:
            form_container.markdown("### Settings")
            form_container.caption("These fields are persisted as app arguments.")
            form_values = _render_args_form(
                defaults_model,
                env=active_env,
                container=form_container,
                wide=use_wide_form,
            )

    try:
        parsed = app_args.ensure_defaults(
            app_args.ArgsModel(**form_values), env=active_env
        )
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
            if not snippet_rendered:
                _render_synced_run_snippet(
                    output_container, env=active_env, parsed=parsed, compact=compact
                )
            payload = json.dumps(
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
            )
            if compact:
                with output_container.expander(
                    "Current run payload", expanded=False
                ) as payload_container:
                    payload_container.code(payload, language="json")
            else:
                output_container.code(payload, language="json")


if not globals().get("_AGILAB_APP_ARGS_FORM_IMPORT_ONLY", False):
    render(env=globals().get("env"))
