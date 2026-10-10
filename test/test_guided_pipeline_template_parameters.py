from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path
import tomllib

import pytest
import tomli_w

from agi_web.testing import AppTest
from agilab.pipeline.pipeline_stage_templates import (
    DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY as REGISTRY,
    PipelineStageTemplateStatus,
    classify_pipeline_stage_template,
    refresh_pipeline_stage_template,
)


def _control(app: AppTest, kind: str, label: str):
    matches = [control for control in app.get(kind) if control.label == label]
    assert len(matches) == 1, (kind, label, matches)
    return matches[0]


def _stage_app(stage: dict) -> AppTest:
    original = copy.deepcopy(stage)

    def page():
        from agi_web import python_ui as ui
        from agilab.pipeline.pipeline_template_controls import render_pipeline_template_controls
        ui.session_state.setdefault("stage", copy.deepcopy(original))
        result = render_pipeline_template_controls(ui, ui.session_state["stage"], key="stage", draft_scope="demo")
        if result is not None:
            ui.session_state["stage"] = result
            ui.session_state["saves"] = ui.session_state.get("saves", 0) + 1

    return AppTest.from_function(page).run()


def test_workflow_local_python_default_is_saved_as_an_sdk_integer() -> None:
    stage = REGISTRY.saved_stage("generic.configure")
    app = _stage_app(stage)
    assert not app.exception
    assert _control(app, "text_input", "Execution mode").value == "0"
    _control(app, "button", "Apply template parameters").click().run()
    assert not app.exception
    saved = app.session_state["stage"]
    namespace = {}
    exec(saved["C"], namespace)
    assert namespace["mode"] == 0
    assert type(namespace["mode"]) is int
    assert saved["template_payload"]["parameters"]["mode"] == 0


@pytest.mark.parametrize("template_id,labels", [
    ("generic.configure", ["App", "Input path", "Output path", "Execution mode"]),
    ("generic.execute", ["App"]),
    ("generic.export_evidence", ["App", "Evidence folder"]),
    ("pipeline.agi_run.single_action", ["App", "Apps folder", "Action name"]),
])
def test_registered_templates_default_to_readable_guided_fields(template_id: str, labels: list[str]) -> None:
    app = _stage_app(REGISTRY.saved_stage(template_id))
    assert not app.exception
    assert [field.label for field in app.text_input] == labels
    assert len(app.text_area) == 0
    advanced = _control(app, "expander", "Advanced parameters")
    assert advanced.node["props"]["expanded"] is False
    if template_id == "generic.execute":
        assert _control(app, "checkbox", "Reset existing output").value is False


def test_guided_parameter_edits_persist_through_actual_save_export_and_reimport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agi_web import python_ui as ui
    from agilab.pipeline import pipeline_editor
    from agilab.notebooks.notebook_export_support import NotebookExportContext, build_notebook_document
    from agilab.notebooks.notebook_pipeline_import import build_lab_stages_preview, build_notebook_pipeline_import, build_notebook_source_export

    path = tmp_path / "lab_stages.toml"
    module = tmp_path / "demo_project"
    path.write_text(tomli_w.dumps({str(module): [REGISTRY.saved_stage("generic.configure")]}))
    monkeypatch.setattr(pipeline_editor, "st", ui)
    # Save's unrelated editor export callback is replaced; both actual export
    # paths are exercised explicitly below against the persisted TOML.
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)

    def page():
        from agi_web import python_ui as ui
        from agilab.pipeline.pipeline_editor import save_stage
        from agilab.pipeline.pipeline_stage_templates import pipeline_stage_execution_error
        from agilab.pipeline.pipeline_template_controls import PipelineTemplateEditor
        data = tomllib.loads(path.read_text())
        entry = data[str(module)][0]
        editor = PipelineTemplateEditor(
            ui=ui, module_path=module, stages_file=path, total_stages=1, key_prefix="editor",
            save_stage_fn=save_stage, on_saved=lambda: None,
            rerun_editor=ui.rerun, execution_error_fn=pipeline_stage_execution_error,
        )
        editor.render_stage(entry, 0)

    app = AppTest.from_function(page).run()
    assert not app.exception
    original = path.read_bytes()
    _control(app, "text_input", "Input path").input("entrée/測試 'quoted'").run()
    assert path.read_bytes() == original
    _control(app, "button", "Apply template parameters").click().run()
    assert not app.exception
    stored = tomllib.loads(path.read_text())[str(module)][0]
    assert stored["template_payload"]["parameters"]["data_in"] == "entrée/測試 'quoted'"
    assert classify_pipeline_stage_template(stored).status is PipelineStageTemplateStatus.CURRENT
    plain = build_notebook_document({"demo_project": [stored]}, path)
    namespace = {}
    exec("".join(plain["cells"][0]["source"]), namespace)
    assert namespace["data_in"] == "entrée/測試 'quoted'"
    notebook = build_notebook_document({"demo_project": [stored]}, path, export_context=NotebookExportContext(
        project_name="demo_project", module_path="demo_project", artifact_dir=str(tmp_path / "artifacts"),
    ))
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook=tmp_path / "edited.ipynb")
    restored = build_lab_stages_preview(imported, module_name="demo_project")["demo_project"][0]
    assert restored["template_payload"] == stored["template_payload"]
    assert restored["C"] == stored["C"]
    assert classify_pipeline_stage_template(restored).status is PipelineStageTemplateStatus.CURRENT
    assert build_notebook_source_export(imported) == notebook


@pytest.mark.parametrize("text", ["{broken", "null", '{"APP": null}', '{"APP": "demo", "unexpected": {"keep": true}}'])
def test_invalid_advanced_json_never_mutates_saved_stage_and_retains_exact_draft(text: str) -> None:
    stage = REGISTRY.saved_stage("generic.configure")
    app = _stage_app(stage)
    _control(app, "button", "Edit complete parameters as JSON").click().run()
    _control(app, "text_area", "Complete parameters (JSON)").input(text).run()
    _control(app, "button", "Apply template parameters").click().run()
    assert not app.exception
    assert app.session_state["stage"] == stage
    assert "saves" not in app.session_state
    assert len(app.error) == 1
    assert _control(app, "text_area", "Complete parameters (JSON)").value == text


def test_guided_boolean_preserves_type_and_rejects_invalid_widget_value() -> None:
    from agi_web.python_view_session import UIError
    stage = REGISTRY.saved_stage("generic.execute")
    app = _stage_app(stage)
    with pytest.raises(UIError, match="Expected a boolean"):
        _control(app, "checkbox", "Reset existing output").set_value("false").run()
    assert app.session_state["stage"] == stage
    assert "saves" not in app.session_state
    _control(app, "checkbox", "Reset existing output").check().run()
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["stage"]["template_payload"]["parameters"]["reset_target"] is True


def test_common_action_fields_keep_nested_and_alternate_literal_values_losslessly() -> None:
    template = REGISTRY.require("pipeline.agi_run.single_action")
    payload = template.default_payload()
    payload["parameters"]["args"] = {"limit": 4, "enabled": False, "nested": {"list": [1, "élève"]}}
    stage = template.saved_stage(template_payload=payload)
    app = _stage_app(stage)
    _control(app, "text_input", "Action name").input("summarize").run()
    _control(app, "text_input", "Action arguments · limit").input("7").run()
    _control(app, "button", "Apply template parameters").click().run()
    saved = app.session_state["stage"]
    assert saved["template_payload"]["parameters"]["action"] == "summarize"
    assert saved["template_payload"]["parameters"]["args"] == {"limit": 7, "enabled": False, "nested": {"list": [1, "élève"]}}
    assert stage["template_payload"]["parameters"]["args"]["limit"] == 4
    # Generic bindings also permit alternate literals. A saved integer is not
    # turned into a displayed string just because the default App is text.
    generic = REGISTRY.saved_stage("generic.configure")
    changed = copy.deepcopy(generic["template_payload"])
    changed["parameters"]["APP"] = 9
    app = _stage_app(refresh_pipeline_stage_template(generic, payload=changed))
    assert "App" not in [field.label for field in app.text_input]
    _control(app, "text_input", "Input path").input("input2").run()
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["stage"]["template_payload"]["parameters"]["APP"] == 9


def test_guided_json_mode_switch_keeps_latest_draft_and_malformed_json_requires_correction() -> None:
    app = _stage_app(REGISTRY.saved_stage("generic.configure"))
    _control(app, "text_input", "Input path").input("draft-input").run()
    _control(app, "button", "Edit complete parameters as JSON").click().run()
    parameters = json.loads(_control(app, "text_area", "Complete parameters (JSON)").value)
    assert parameters["data_in"] == "draft-input"
    parameters["data_in"] = "json-input"
    _control(app, "text_area", "Complete parameters (JSON)").input(json.dumps(parameters)).run()
    _control(app, "button", "Return to guided fields").click().run()
    assert _control(app, "text_input", "Input path").value == "json-input"
    _control(app, "text_input", "Input path").input("latest-input").run()
    _control(app, "button", "Edit complete parameters as JSON").click().run()
    assert json.loads(_control(app, "text_area", "Complete parameters (JSON)").value)["data_in"] == "latest-input"
    _control(app, "text_area", "Complete parameters (JSON)").input("{malformed").run()
    _control(app, "button", "Return to guided fields").click().run()
    _control(app, "button", "Apply template parameters").click().run()
    assert "saves" not in app.session_state
    _control(app, "button", "Edit complete parameters as JSON").click().run()
    assert _control(app, "text_area", "Complete parameters (JSON)").value == "{malformed"
    _control(app, "text_area", "Complete parameters (JSON)").input(json.dumps(parameters)).run()
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["stage"]["template_payload"]["parameters"]["data_in"] == "json-input"


def test_stage_and_project_switches_isolate_and_restore_unsaved_drafts() -> None:
    def page():
        from agi_web import python_ui as ui
        from agilab.pipeline.pipeline_stage_templates import DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY
        from agilab.pipeline.pipeline_template_controls import render_pipeline_template_controls
        project = ui.selectbox("Project", ["one", "two"], key="project")
        stage_index = ui.selectbox("Stage", [0, 1], key="stage_index")
        entry = DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY.saved_stage("generic.configure")
        result = render_pipeline_template_controls(ui, entry, key=f"stage_{stage_index}", draft_scope=project)
        if result is not None:
            ui.session_state["saved"] = result

    app = AppTest.from_function(page).run()
    _control(app, "text_input", "Input path").input("one-stage-zero").run()
    _control(app, "selectbox", "Stage").select(1).run()
    assert _control(app, "text_input", "Input path").value == "input/path"
    _control(app, "text_input", "Input path").input("one-stage-one").run()
    _control(app, "selectbox", "Project").select("two").run()
    assert _control(app, "text_input", "Input path").value == "input/path"
    _control(app, "text_input", "Input path").input("two-stage-one").run()
    _control(app, "selectbox", "Project").select("one").run()
    assert "saved" not in app.session_state
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["saved"]["template_payload"]["parameters"]["data_in"] == "one-stage-one"
    _control(app, "selectbox", "Stage").select(0).run()
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["saved"]["template_payload"]["parameters"]["data_in"] == "one-stage-zero"
    _control(app, "selectbox", "Project").select("two").run()
    _control(app, "selectbox", "Stage").select(1).run()
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["saved"]["template_payload"]["parameters"]["data_in"] == "two-stage-one"


def test_new_template_project_drafts_are_isolated_and_templates_have_readable_titles() -> None:
    def page():
        from agi_web import python_ui as ui
        from agilab.pipeline.pipeline_template_controls import render_new_pipeline_template
        project = ui.selectbox("Project", ["one", "two"], key="project")
        result = render_new_pipeline_template(ui, key="new", app=project, apps_path="/apps")
        if result is not None:
            ui.session_state["stage"] = result

    app = AppTest.from_function(page).run()
    choices = _control(app, "selectbox", "Stage template")
    assert "Configure Workflow Inputs" in choices.options
    assert "generic.configure" not in choices.options
    choices.select("generic.configure").run()
    assert _control(app, "text_input", "App").value == "one"
    _control(app, "text_input", "Input path").input("one-input").run()
    _control(app, "selectbox", "Project").select("two").run()
    assert _control(app, "text_input", "App").value == "two"
    assert _control(app, "text_input", "Input path").value == "input/path"
    _control(app, "selectbox", "Project").select("one").run()
    assert "stage" not in app.session_state
    _control(app, "button", "Add template stage").click().run()
    assert app.session_state["stage"]["template_payload"]["parameters"]["data_in"] == "one-input"


@pytest.mark.parametrize("change", [
    lambda p: p["parameters"].pop("data_out"),
    lambda p: p["parameters"].update(data_out=None),
    lambda p: p.update(unknown={"nested": ["preserve"]}),
])
def test_invalid_saved_payload_is_not_repaired_or_dropped_by_guided_controls(change) -> None:
    stage = REGISTRY.saved_stage("generic.configure")
    change(stage["template_payload"])
    original = copy.deepcopy(stage)
    app = _stage_app(stage)
    assert app.session_state["stage"] == original
    _control(app, "text_input", "Input path").input("reviewed-input").run()
    _control(app, "button", "Refresh from template").click().run()
    assert not app.exception
    assert app.session_state["stage"] == original
    assert len(app.error) == 1
    _control(app, "button", "Edit complete parameters as JSON").click().run()
    parameters = json.loads(_control(app, "text_area", "Complete parameters (JSON)").value)
    if "data_out" not in original["template_payload"]["parameters"]:
        assert "data_out" not in parameters
    elif original["template_payload"]["parameters"]["data_out"] is None:
        assert parameters["data_out"] is None


def test_unsupported_toml_value_remains_exact_and_needs_explicit_json_replacement() -> None:
    stage = REGISTRY.saved_stage("generic.configure")
    stage["template_payload"]["parameters"]["data_out"] = date(2026, 10, 4)
    original = copy.deepcopy(stage)
    app = _stage_app(stage)
    assert not app.exception
    _control(app, "text_input", "Input path").input("changed-input").run()
    _control(app, "button", "Refresh from template").click().run()
    assert not app.exception
    assert app.session_state["stage"] == original
    _control(app, "button", "Edit complete parameters as JSON").click().run()
    assert not app.exception
    assert _control(app, "text_area", "Complete parameters (JSON)").value == ""
    _control(app, "button", "Refresh from template").click().run()
    assert app.session_state["stage"] == original
    _control(app, "text_area", "Complete parameters (JSON)").input(json.dumps(REGISTRY.require("generic.configure").default_payload()["parameters"])).run()
    _control(app, "button", "Refresh from template").click().run()
    assert app.session_state["stage"]["template_payload"]["parameters"]["data_out"] == "output/path"


def test_primary_form_submission_commits_all_pending_fields_atomically() -> None:
    stage = REGISTRY.saved_stage("generic.configure")
    app = _stage_app(stage)
    _control(app, "text_input", "Input path").input("last-input")
    _control(app, "text_input", "Output path").input("last-output")
    assert app.session_state["stage"] == stage
    _control(app, "button", "Apply template parameters").click().run()
    saved = app.session_state["stage"]["template_payload"]["parameters"]
    assert (saved["data_in"], saved["data_out"]) == ("last-input", "last-output")


def test_add_form_submission_captures_last_pending_field_before_any_stage_exists() -> None:
    def page():
        from agi_web import python_ui as ui
        from agilab.pipeline.pipeline_template_controls import render_new_pipeline_template
        result = render_new_pipeline_template(ui, key="new", app="demo")
        if result is not None:
            ui.session_state["stage"] = result

    app = AppTest.from_function(page).run()
    _control(app, "text_input", "Input path").input("add-input")
    _control(app, "text_input", "Output path").input("unblurred-add-output")
    assert "stage" not in app.session_state
    _control(app, "button", "Add template stage").click().run()
    saved = app.session_state["stage"]["template_payload"]["parameters"]
    assert (saved["data_in"], saved["data_out"]) == ("add-input", "unblurred-add-output")


def test_mode_form_submission_captures_all_pending_fields_without_persisting_stage() -> None:
    stage = REGISTRY.saved_stage("generic.configure")
    app = _stage_app(stage)
    _control(app, "text_input", "Input path").input("draft-input")
    _control(app, "text_input", "Output path").input("draft-output")
    _control(app, "button", "Edit complete parameters as JSON").click().run()
    assert app.session_state["stage"] == stage
    assert "saves" not in app.session_state
    parameters = json.loads(_control(app, "text_area", "Complete parameters (JSON)").value)
    assert (parameters["data_in"], parameters["data_out"]) == ("draft-input", "draft-output")
    parameters["data_out"] = "json-draft-output"
    _control(app, "text_area", "Complete parameters (JSON)").input(json.dumps(parameters))
    _control(app, "button", "Return to guided fields").click().run()
    assert app.session_state["stage"] == stage
    assert "saves" not in app.session_state
    assert _control(app, "text_input", "Output path").value == "json-draft-output"
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["stage"]["template_payload"]["parameters"]["data_out"] == "json-draft-output"


@pytest.mark.parametrize("starting,requested", [
    (2, "9007199254740993"),
    (9007199254740993, "-9007199254740995"),
    (0, "123456789012345678901234567890123456789"),
])
def test_guided_integer_text_wire_preserves_exact_values_beyond_browser_number_range(starting: int, requested: str) -> None:
    template = REGISTRY.require("generic.execute")
    payload = template.default_payload()
    payload["parameters"]["workers"] = {"localhost": starting}
    stage = template.saved_stage(template_payload=payload)
    app = _stage_app(stage)
    field = _control(app, "text_input", "Workers · localhost")
    assert field.value == str(starting)
    assert len(app.number_input) == 0
    field.input(requested)
    assert app.session_state["stage"] == stage
    _control(app, "button", "Apply template parameters").click().run()
    saved = app.session_state["stage"]["template_payload"]["parameters"]["workers"]["localhost"]
    assert type(saved) is int
    assert saved == int(requested)


@pytest.mark.parametrize("requested", ["", "1.2", "1e6", "not-an-integer"])
def test_invalid_integer_text_blocks_apply_and_can_be_corrected(requested: str) -> None:
    template = REGISTRY.require("generic.execute")
    payload = template.default_payload()
    payload["parameters"]["workers"] = {"localhost": 2}
    stage = template.saved_stage(template_payload=payload)
    app = _stage_app(stage)
    _control(app, "text_input", "Workers · localhost").input(requested)
    _control(app, "button", "Apply template parameters").click().run()
    assert not app.exception
    assert app.session_state["stage"] == stage
    assert "saves" not in app.session_state
    assert "must be a whole number" in app.error[0].value
    _control(app, "text_input", "Workers · localhost").input("9007199254740993")
    _control(app, "button", "Apply template parameters").click().run()
    assert app.session_state["stage"]["template_payload"]["parameters"]["workers"]["localhost"] == 9007199254740993
