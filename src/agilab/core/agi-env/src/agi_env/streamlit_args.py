"""Streamlit helpers for managing app argument forms."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal, get_args, get_origin

import streamlit as st
from pydantic import BaseModel, ValidationError
from annotated_types import Ge, Le, MultipleOf


def load_args_state(
    env,
    *,
    args_module,
    section: str = "args",
) -> tuple[BaseModel, dict[str, Any], Path]:
    """Load persisted args into session state and return defaults."""

    settings_path = Path(env.app_settings_file)

    app_settings = st.session_state.get("app_settings")
    if not app_settings or not st.session_state.get("is_args_from_ui"):
        if settings_path.exists():
            with settings_path.open("rb") as handle:
                app_settings = tomllib.load(handle)
        else:
            app_settings = {}
        st.session_state.app_settings = app_settings

    raw_payload = dict(app_settings.get(section, {}))
    try:
        stored_args = args_module.ArgsModel(**raw_payload)
    except ValidationError as exc:
        messages = env.humanize_validation_errors(exc)
        st.warning("\n".join(messages) + f"\nplease check {settings_path}")
        st.session_state.pop("is_args_from_ui", None)
        stored_args = args_module.ArgsModel()

    ensure_defaults: Callable[..., BaseModel] = getattr(args_module, "ensure_defaults", lambda args, **_: args)
    defaults_model = ensure_defaults(stored_args, env=env)
    payload = defaults_model.model_dump(mode="json")
    st.session_state.app_settings[section] = payload

    return defaults_model, payload, settings_path


def _constraint_value(field, constraint_type, attr: str) -> Any | None:
    for meta in getattr(field, "metadata", ()):  # Pydantic v2 stores constraints here
        if isinstance(meta, constraint_type):
            return getattr(meta, attr)
    return None


def render_form(model: BaseModel) -> dict[str, Any]:
    """Render Streamlit widgets for each field in ``model`` and return values."""

    from datetime import date, datetime
    from pathlib import Path as _Path

    values: dict[str, Any] = {}
    fields = model.model_fields

    for name, field in fields.items():
        annotation = field.annotation
        label = field.title or name.replace("_", " ").title()
        current = getattr(model, name)
        origin = get_origin(annotation)

        if origin is not None:
            if origin is list:
                options = list(get_args(annotation))
                st.write(f"Unsupported field type for '{label}', falling back to text input")
                values[name] = st.text_area(label, value=str(current))
                continue

            if origin is tuple:
                values[name] = st.text_area(label, value=str(current))
                continue

            if origin is type(None):
                values[name] = st.text_input(label, value=str(current or ""))
                continue

        if origin is None and annotation is not None:
            if annotation is bool:
                values[name] = st.checkbox(label, value=bool(current))
                continue

            if annotation in (int,):
                kwargs: dict[str, Any] = {
                    "value": int(current),
                    "step": 1,
                }
                ge_value = _constraint_value(field, Ge, "ge")
                le_value = _constraint_value(field, Le, "le")
                if ge_value is not None:
                    kwargs["min_value"] = int(ge_value)
                if le_value is not None:
                    kwargs["max_value"] = int(le_value)
                values[name] = st.number_input(label, **kwargs)
                continue

            if annotation in (float,):
                step = _constraint_value(field, MultipleOf, "multiple_of") or 0.1
                kwargs = {
                    "value": float(current),
                    "step": float(step),
                }
                ge_value = _constraint_value(field, Ge, "ge")
                le_value = _constraint_value(field, Le, "le")
                if ge_value is not None:
                    kwargs["min_value"] = float(ge_value)
                if le_value is not None:
                    kwargs["max_value"] = float(le_value)
                values[name] = st.number_input(label, **kwargs)
                continue

            if annotation in (str,):
                values[name] = st.text_input(label, value=str(current))
                continue

            if annotation in (_Path, Path):
                values[name] = st.text_input(label, value=str(current))
                continue

            if annotation in (date,):
                values[name] = st.date_input(label, value=current)
                continue

            if annotation in (datetime,):
                values[name] = st.text_input(label, value=current.isoformat() if current else "")
                continue

        if origin is Literal:
            options = list(get_args(annotation))
            index = options.index(current) if current in options else 0
            values[name] = st.selectbox(label, options=options, index=index)
            continue

        values[name] = st.text_input(label, value=str(current))

    return values


def persist_args(
    args_module,
    parsed: BaseModel,
    *,
    settings_path: Path,
    defaults_payload: dict[str, Any],
    section: str = "args",
) -> None:
    payload = parsed.model_dump(mode="json")
    if payload != defaults_payload:
        args_module.dump_args(parsed, settings_path, section=section)
        st.session_state.app_settings[section] = payload
        st.session_state.is_args_from_ui = True
        env = st.session_state.get("env")
        if env is not None and hasattr(env, "app"):
            st.session_state["args_project"] = env.app


try:  # lazy import to avoid mandatory dependency where unused
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - runtime on python<3.11
    import tomli as tomllib  # type: ignore[assignment]
