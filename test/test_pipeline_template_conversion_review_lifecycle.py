"""Native template toolbar previews, reviews and safely commits source changes."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import tomllib

import pytest
import tomli_w

from agilab.pipeline import pipeline_template_controls as templates


class ToolbarUI:
    def __init__(self):
        self.session_state = {}
        self.clicked = set()
        self.errors = []
        self.successes = []
        self.tables = []
        self.reruns = 0
        self.codes = []
        self.warnings = []

    def expander(self, *_args, **_kwargs):
        return nullcontext()

    def caption(self, *_args, **_kwargs):
        pass

    def selectbox(self, _label, options, **_kwargs):
        assert "generic.configure" in options
        return "generic.configure"

    def warning(self, message):
        self.warnings.append(message)

    def code(self, source, **_kwargs):
        self.codes.append(source)

    def button(self, label, **_kwargs):
        return label in self.clicked

    def dataframe(self, rows, **_kwargs):
        self.tables.append(rows)

    def error(self, message):
        self.errors.append(message)

    def success(self, message):
        self.successes.append(message)

    def rerun(self):
        self.reruns += 1


@pytest.fixture
def toolbar(tmp_path, monkeypatch):
    ui = ToolbarUI()
    directory = tmp_path / "workflow"
    directory.mkdir()
    path = directory / "lab_stages.toml"
    generated = templates.DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY.require("generic.configure").code
    source = "# source notes are retained in the backup\n" + tomli_w.dumps({"demo": [{"C": generated}, {"C": "print('custom Python')"}]})
    path.write_text(source)
    saved = Mock()
    editor = templates.PipelineTemplateEditor(ui=ui, module_path=tmp_path, stages_file=path, total_stages=2,
        key_prefix="owned", save_stage_fn=Mock(), on_saved=saved, rerun_editor=Mock(), execution_error_fn=lambda _: "")
    monkeypatch.setattr(templates, "render_new_pipeline_template", lambda *_args, **_kwargs: None)
    return editor, ui, path, source, saved, SimpleNamespace(app="demo", active_app=tmp_path / "demo")


def test_preview_requires_explicit_apply_and_commit_retains_original_backup(toolbar):
    editor, ui, path, source, saved, env = toolbar
    ui.clicked = {"Preview legacy stage conversion"}
    editor.render_toolbar(env)
    assert path.read_text() == source
    assert [row["kind"] for row in ui.tables[-1]] == ["template", "raw_python"]
    saved.assert_not_called()
    assert ui.reruns == 0
    assert "owned_stage_conversion_preview" in ui.session_state
    ui.clicked = {"Apply reviewed stage conversion"}
    editor.render_toolbar(env)
    backups = [item for item in path.parent.iterdir() if item != path]
    assert len(backups) == 1 and backups[0].read_text() == source
    converted = tomllib.loads(path.read_text())["demo"]
    assert converted[0]["kind"] == "template"
    assert converted[0]["template_id"] == "generic.configure"
    assert converted[1]["C"] == "print('custom Python')"
    assert "owned_stage_conversion_preview" not in ui.session_state
    saved.assert_called_once()
    assert ui.reruns == 1 and ui.successes and not ui.errors


def test_apply_refuses_a_stale_review_without_overwriting_a_second_writer(toolbar):
    editor, ui, path, source, saved, env = toolbar
    ui.clicked = {"Preview legacy stage conversion"}
    editor.render_toolbar(env)
    changed = source + "# another writer\n"
    path.write_text(changed)
    ui.clicked = {"Apply reviewed stage conversion"}
    editor.render_toolbar(env)
    assert path.read_text() == changed
    assert list(path.parent.iterdir()) == [path]
    assert ui.errors and "changed after conversion preview" in ui.errors[-1]
    saved.assert_not_called()
    assert ui.reruns == 0


def test_invalid_source_preview_surfaces_error_without_creating_a_review(toolbar):
    editor, ui, path, _source, saved, env = toolbar
    path.write_text("invalid = [")
    ui.clicked = {"Preview legacy stage conversion"}
    editor.render_toolbar(env)
    assert path.read_text() == "invalid = ["
    assert ui.errors and "Unable to preview" in ui.errors[-1]
    assert "owned_stage_conversion_preview" not in ui.session_state
    saved.assert_not_called()


@pytest.mark.parametrize("skip_save", [False, True])
def test_new_template_refreshes_only_after_a_committed_save(toolbar, monkeypatch, skip_save):
    editor, ui, _path, _source, saved, env = toolbar
    entry = {"D": "Configure", "Q": "setup", "M": "", "C": "print('authored stage')", "stage_id": "configured"}
    ui.session_state["_experiment_last_save_skipped"] = skip_save
    monkeypatch.setattr(templates, "render_new_pipeline_template", lambda *_args, **_kwargs: entry)
    editor.render_toolbar(env)
    editor.save_stage_fn.assert_called_once_with(editor.module_path, ["Configure", "setup", "", "print('authored stage')"],
        2, 2, editor.stages_file, extra_fields=entry)
    assert saved.call_count == (0 if skip_save else 1)
    assert ui.reruns == (0 if skip_save else 1)


def test_absent_stage_file_and_non_review_session_values_do_not_offer_conversion(toolbar):
    editor, ui, path, _source, saved, env = toolbar
    path.unlink()
    ui.clicked = {"Preview legacy stage conversion", "Apply reviewed stage conversion"}
    editor.render_toolbar(env)
    assert not ui.tables and not ui.errors
    saved.assert_not_called()


@pytest.mark.parametrize("submitted,parameter_error", [(False, ""), (True, "review the app parameter"), (True, "")])
def test_new_template_form_returns_a_valid_stage_only_after_explicit_valid_submission(monkeypatch, submitted, parameter_error):
    ui = ToolbarUI()
    captured = []
    app = "données_'quoted'_project"
    def collect(_ui, _template, parameters, **_kwargs):
        captured.append(deepcopy(parameters))
        return parameters, parameter_error, submitted
    monkeypatch.setattr(templates, "render_template_parameter_draft", collect)
    stage = templates.render_new_pipeline_template(ui, key="owned_new", app=app, apps_path="/owned/projects")
    assert captured[0]["APP"] == app
    if submitted and not parameter_error:
        assert stage["kind"] == "template" and stage["template_id"] == "generic.configure"
        assert stage["template_payload"]["parameters"]["APP"] == app
        assert templates.classify_pipeline_stage_template(stage).status is templates.PipelineStageTemplateStatus.CURRENT
        assert not ui.errors
    else:
        assert stage is None
        assert bool(ui.errors) is bool(submitted)
    assert ui.reruns == 0, "The form creates a draft; its caller owns persistence"


def test_new_template_form_rejects_an_unrenderable_parameter_in_the_draft(monkeypatch):
    ui = ToolbarUI()
    def invalid(_ui, _template, parameters, **_kwargs):
        return {**parameters, "APP": object()}, "", True
    monkeypatch.setattr(templates, "render_template_parameter_draft", invalid)
    assert templates.render_new_pipeline_template(ui, key="owned_invalid") is None
    assert ui.errors and "Unable to add template stage" in ui.errors[-1]
    assert ui.reruns == 0


def test_template_drift_displays_the_authored_code_without_saving_or_executing(toolbar, monkeypatch):
    from agilab.pipeline.pipeline_stages import pipeline_stage_execution_error

    editor, ui, _path, _source, saved, _env = toolbar
    entry = templates.DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY.saved_stage("generic.configure")
    entry["C"] += "\n# a deliberate author edit\n"
    original = deepcopy(entry)
    monkeypatch.setattr(templates, "render_template_parameter_draft", lambda _ui, _template, parameters, **_kwargs: (parameters, "", False))
    guarded = replace(editor, execution_error_fn=pipeline_stage_execution_error)
    assert guarded.render_stage(entry, 0) is True
    assert ui.codes == [original["C"]]
    assert ui.warnings and "blocked until reviewed" in ui.warnings[-1]
    assert entry == original
    editor.save_stage_fn.assert_not_called()
    saved.assert_not_called()
