"""Guided, lossless parameter drafts for registered Workflow templates."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from agilab.pipeline.pipeline_stage_templates import PipelineStageTemplate


_FIELD_LABELS = {
    "APP": ("App", "App project used by this stage."),
    "app": ("App", "App project containing the named action."),
    "apps_path": ("Apps folder", "Folder containing the app projects; relative paths are kept as entered."),
    "data_in": ("Input path", "File or folder read by the stage; the path is kept as entered."),
    "data_out": ("Output path", "File or folder written by the stage; the path is kept as entered."),
    "mode": ("Execution mode", "Keep the mode supported by your app, for example local."),
    "reset_target": ("Reset existing output", "Allow the stage to reset its existing target."),
    "action": ("Action name", "Named action declared by the selected app."),
    "artifact_dir": ("Evidence folder", "Folder used for the evidence and summary files."),
    "args": ("Action arguments", "Arguments passed to the named action."),
    "workers": ("Workers", "Worker configuration used by this stage."),
}


def parameter_draft_key(*, key: str, template: PipelineStageTemplate, parameters: Any, scope: str) -> str:
    """Separate stage, project, template and saved-source revisions."""
    try:
        identity = json.dumps([template.template_id, scope, parameters], ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        # A TOML date, for example, is not a supported template literal. Give
        # it an isolated review draft without coercing its persisted value.
        identity = repr([template.template_id, scope, parameters])
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{key}_draft_{digest}"


def _parameter_json(parameters: Any) -> str | None:
    try:
        return json.dumps(parameters, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError):
        return None


def _scalar_type(value: Any) -> type | None:
    if type(value) in (str, bool, int):
        return type(value)
    if type(value) is float and math.isfinite(value):
        return float
    return None


def _scalar_widget(ui: Any, *, key: str, label: str, help_text: str, value: Any) -> Any:
    kind = _scalar_type(value)
    if kind is bool:
        edited = ui.checkbox(label, value=value, key=key, help=help_text)
    elif kind is int:
        # The browser Number type cannot carry every Python integer. Text is
        # the wire contract even when the starting value would fit in Number.
        text = ui.text_input(label, value=str(value), key=key, help=f"{help_text} Enter a whole number.")
        if not isinstance(text, str) or re.fullmatch(r"[+-]?[0-9]+", text.strip()) is None:
            raise ValueError(f"{label} must be a whole number.")
        edited = int(text.strip())
    elif kind is float:
        edited = ui.number_input(label, value=value, key=key, help=help_text, step=0.1)
    else:
        edited = ui.text_input(label, value=value, key=key, help=help_text)
    if _scalar_type(edited) is not kind:
        raise ValueError(f"{label} must remain a {kind.__name__} value. Use Advanced parameters to change its type.")
    return edited


def _clear_field_widgets(state: Any, key: str) -> None:
    for name in tuple(state):
        if str(name).startswith(f"{key}_field_"):
            state.pop(name, None)


def render_template_parameter_draft(
    ui: Any, template: PipelineStageTemplate, parameters: Any, *, key: str, scope: str = "",
    submit_label: str, submit_key: str,
) -> tuple[Any, str | None, bool]:
    """Render drafts without changing a saved stage or repairing its values.

    Types come from registered defaults, not coercion of a loaded payload.
    Unsupported, missing and null values remain in the complete JSON draft;
    the template renderer still decides whether the final payload is valid.
    """
    draft_key = parameter_draft_key(key=key, template=template, parameters=parameters, scope=scope)
    draft = ui.session_state.setdefault(draft_key, {
        "parameters": copy.deepcopy(parameters), "advanced": False, "error": None,
    })
    current = copy.deepcopy(draft["parameters"])
    defaults = template.default_payload()["parameters"]
    json_key = f"{draft_key}_parameters"
    error = None
    submitted = False
    advanced = draft["advanced"]
    with ui.form(f"{draft_key}_form"):
        if not advanced:
            if isinstance(current, Mapping):
                for name, default in defaults.items():
                    if name not in current:
                        continue
                    label, help_text = _FIELD_LABELS.get(name, (name.replace("_", " ").capitalize(), ""))
                    value = current[name]
                    if _scalar_type(default) is not None and _scalar_type(value) is _scalar_type(default):
                        try:
                            current[name] = _scalar_widget(
                                ui, key=f"{draft_key}_field_{name}", label=label,
                                help_text=help_text, value=value,
                            )
                        except (TypeError, ValueError) as exc:
                            error = str(exc)
                    elif isinstance(default, Mapping) and isinstance(value, Mapping):
                        for child, child_value in value.items():
                            if _scalar_type(child_value) is not None:
                                try:
                                    current[name][child] = _scalar_widget(
                                        ui, key=f"{draft_key}_field_{name}_{child}",
                                        label=f"{label} · {child}", help_text=help_text, value=child_value,
                                    )
                                except (TypeError, ValueError) as exc:
                                    error = str(exc)
                        ui.caption(f"{label}: add keys or edit nested values in Advanced parameters.")
                    else:
                        ui.caption(f"{label} keeps its saved value. Edit it in Advanced parameters.")
                extra = set(current) - set(defaults)
                if extra:
                    ui.caption("Additional saved parameters are preserved in Advanced parameters.")
            else:
                ui.caption("The saved parameters require review in Advanced parameters.")
            draft["parameters"] = copy.deepcopy(current)
            submitted = ui.form_submit_button(submit_label, key=submit_key)
            with ui.expander("Advanced parameters", expanded=False):
                switch_editor = ui.form_submit_button("Edit complete parameters as JSON", key=f"{draft_key}_advanced")
                ui.caption("Switching editors keeps your draft; Apply or Add saves the stage.")
            if switch_editor:
                if error:
                    ui.error(error)
                else:
                    if not draft["error"]:
                        ui.session_state[json_key] = _parameter_json(current) or ""
                    draft["advanced"] = True
                    ui.rerun()
        else:
            formatted = _parameter_json(current)
            if formatted is None:
                ui.warning("Some saved values cannot be represented as JSON. Enter a complete replacement explicitly to repair them.")
            text = ui.text_area("Complete parameters (JSON)", value=formatted or "", key=json_key)
            try:
                current = json.loads(text)
                draft["parameters"] = copy.deepcopy(current)
                draft["error"] = None
            except (TypeError, ValueError) as exc:
                draft["error"] = f"Complete parameters must be valid JSON: {exc}"
            submitted = ui.form_submit_button(submit_label, key=submit_key)
            ui.caption("All saved values are retained. JSON null and missing required fields are not replaced by defaults.")
            if ui.form_submit_button("Return to guided fields", key=f"{draft_key}_guided"):
                # JSON owns every field in this mode. Seed fresh guided
                # widgets instead of reviving values from an earlier draft.
                _clear_field_widgets(ui.session_state, draft_key)
                draft["advanced"] = False
                ui.rerun()
    if draft["error"]:
        ui.warning("Correct the retained JSON draft in Advanced parameters before applying changes.")
    return current, error or draft["error"], submitted
