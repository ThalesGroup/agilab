"""Template controls used by the existing WORKFLOW stage editor."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agilab.pipeline.pipeline_editor import apply_pipeline_stage_conversion, preview_pipeline_stage_conversion
from agilab.pipeline.pipeline_page_state import hydrate_pipeline_editor_values, prepare_pipeline_editor_updates
from agilab.pipeline.pipeline_stage_templates import (
    DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY,
    PipelineStageTemplateStatus,
    classify_pipeline_stage_template,
    detach_pipeline_stage_template,
    refresh_pipeline_stage_template,
)


@dataclass(frozen=True, kw_only=True)
class PipelineTemplateEditor:
    """Template toolbar and per-stage edits with the workflow's existing effects."""

    ui: Any
    module_path: Path
    stages_file: Path
    total_stages: int
    key_prefix: str
    save_stage_fn: Callable[..., Any]
    on_saved: Callable[[], Any]
    rerun_editor: Callable[[], Any]
    execution_error_fn: Callable[[Mapping[str, Any]], str]

    def stage_widget_keys(self, stage: int) -> tuple[str, ...]:
        """Keep the existing editor widget identities in one ordered contract."""
        names = (
            "q_stage", "code_stage", "venv", "editor_rev", "pending_q", "pending_c",
            "undo", "confirm_delete", "ignore_blank_editor",
        )
        return tuple(f"{self.key_prefix}_{name}_{stage}" for name in names)

    def _save_entry(self, entry: Mapping[str, Any], stage: int) -> bool:
        self.save_stage_fn(
            self.module_path, [entry.get(field, "") for field in ("D", "Q", "M", "C")],
            stage, self.total_stages, self.stages_file, extra_fields=entry,
        )
        return not self.ui.session_state.get("_experiment_last_save_skipped")

    def render_toolbar(self, env: Any) -> None:
        ui = self.ui
        with ui.expander("Versioned stage templates", expanded=False):
            ui.caption("Generated stages use explicit parameters. Custom Python remains editable.")
            active_app_path = Path(str(getattr(env, "active_app", "") or "."))
            new_template = render_new_pipeline_template(
                ui, key=f"{self.key_prefix}_new_template", app=str(getattr(env, "app", "") or ""),
                apps_path=str(active_app_path.parent),
            )
            if new_template is not None and self._save_entry(new_template, self.total_stages):
                self.on_saved()
                ui.rerun()
            if not self.stages_file.is_file():
                return
            conversion_key = f"{self.key_prefix}_stage_conversion_preview"
            if ui.button("Preview legacy stage conversion", key=f"{self.key_prefix}_preview_stage_conversion"):
                try:
                    ui.session_state[conversion_key] = preview_pipeline_stage_conversion(self.stages_file)
                except (OSError, ValueError) as exc:
                    ui.error(f"Unable to preview stage conversion: {exc}")
            conversion_preview = ui.session_state.get(conversion_key)
            if not isinstance(conversion_preview, Mapping):
                return
            ui.dataframe(conversion_preview["rows"], hide_index=True)
            ui.caption("Only exact registered generated shapes become templates. Other Python is preserved. A source backup is retained.")
            if ui.button("Apply reviewed stage conversion", key=f"{self.key_prefix}_apply_stage_conversion"):
                try:
                    backup = apply_pipeline_stage_conversion(self.stages_file, conversion_preview)
                    ui.session_state.pop(conversion_key, None)
                    self.on_saved()
                    ui.success(f"Stage conversion saved. Original source: {backup.name}")
                    ui.rerun()
                except (OSError, ValueError) as exc:
                    ui.error(f"Unable to apply stage conversion: {exc}")

    def render_stage(self, entry: Mapping[str, Any], stage: int) -> bool:
        """Render edit controls; return true if drift stops the rest of the editor."""
        ui = self.ui
        if prepare_pipeline_editor_updates(ui.session_state, self.key_prefix, stage):
            self.rerun_editor()
        hydrate_pipeline_editor_values(ui.session_state, self.key_prefix, stage, entry)
        updated = render_pipeline_template_controls(ui, entry, key=f"{self.key_prefix}_template_{stage}")
        if updated is not None and self._save_entry(updated, stage):
            q_key, code_key, _, revision_key, *_ = self.stage_widget_keys(stage)
            ui.session_state.pop(q_key, None)
            ui.session_state.pop(code_key, None)
            ui.session_state[revision_key] = ui.session_state.get(revision_key, 0) + 1
            self.on_saved()
            ui.rerun()
        if self.execution_error_fn(entry):
            ui.code(entry.get("C", "") or "# No rendered Python", language="python")
            return True
        return False


def render_new_pipeline_template(ui: Any, *, key: str, app: str = "", apps_path: str = ".") -> dict[str, Any] | None:
    registry = DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY
    template_id = ui.selectbox("Stage template", registry.ids(), key=f"{key}_template_id")
    template = registry.require(template_id)
    payload = template.default_payload()
    parameters = payload["parameters"]
    for name in ("app", "APP"):
        if app and name in parameters:
            parameters[name] = app
    if "apps_path" in parameters:
        parameters["apps_path"] = apps_path
    parameter_text = ui.text_area(
        "Template parameters (JSON)", value=json.dumps(parameters, ensure_ascii=False, indent=2),
        key=f"{key}_{template_id}_parameters",
    )
    ui.caption(template.description)
    if not ui.button("Add template stage", key=f"{key}_add_template"):
        return None
    try:
        payload["parameters"] = json.loads(parameter_text)
        return template.saved_stage(template_payload=payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        ui.error(f"Unable to add template stage: {exc}")
        return None


def render_pipeline_template_controls(ui: Any, entry: Mapping[str, Any], *, key: str) -> dict[str, Any] | None:
    classification = classify_pipeline_stage_template(entry)
    if classification.status is PipelineStageTemplateStatus.RAW_PYTHON:
        ui.caption("Custom Python: saved and executed without template regeneration.")
        return None
    if entry.get("kind") != "template":
        ui.caption("Legacy template metadata. Use the conversion preview to classify this saved Python.")
        return None
    ui.caption(f"Template `{classification.template_id}` · version {classification.saved_version}")
    stale = classification.status is PipelineStageTemplateStatus.STALE
    if stale:
        ui.warning(f"Template drift: {classification.reason}. Execution and export are blocked until reviewed.")
    if ui.button("Keep as custom Python", key=f"{key}_keep_python"):
        return detach_pipeline_stage_template(entry)
    template = DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY.get(classification.template_id)
    if template is None:
        return None
    payload = entry.get("template_payload", {})
    parameters = payload.get("parameters", {}) if isinstance(payload, Mapping) else {}
    parameter_text = ui.text_area(
        "Template parameters (JSON)", value=json.dumps(parameters, ensure_ascii=False, indent=2),
        key=f"{key}_{entry.get('payload_fingerprint', '')}_parameters",
    )
    if stale:
        ui.caption("Refreshing replaces the rendered Python with the current template and the reviewed parameters.")
    label = "Refresh from template" if stale else "Apply template parameters"
    if not ui.button(label, key=f"{key}_refresh_template"):
        return None
    try:
        fresh_payload = template.default_payload()
        fresh_payload["parameters"] = json.loads(parameter_text)
        return refresh_pipeline_stage_template(entry, payload=fresh_payload)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        ui.error(f"Unable to refresh template stage: {exc}")
        return None
