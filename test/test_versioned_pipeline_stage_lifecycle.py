from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tomllib
import types

import pytest
import tomli_w

from agilab.pipeline.pipeline_stage_templates import (
    DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY as REGISTRY,
    PIPELINE_STAGE_PAYLOAD_SCHEMA,
    PipelineStageTemplate,
    PipelineStageTemplateRegistry,
    PipelineStageTemplateStatus,
    classify_pipeline_stage_template,
    convert_legacy_pipeline_stages,
    normalize_pipeline_stage_for_save,
    reconcile_imported_pipeline_template_stage,
    refresh_pipeline_stage_template,
    rendered_pipeline_stage_code,
)


def _stage() -> dict:
    return REGISTRY.saved_stage("generic.configure")


def test_structured_stage_roundtrips_toml_and_executes_literal_parameters() -> None:
    stage = _stage()
    payload = copy.deepcopy(stage["template_payload"])
    payload["parameters"].update(APP="données_'quoted'_project", data_in="entrée/測試")
    changed = refresh_pipeline_stage_template(stage, payload=payload)
    stored = tomllib.loads(tomli_w.dumps({"demo": [changed]}))["demo"][0]
    assert stored == changed
    namespace = {}
    exec(rendered_pipeline_stage_code(stored), namespace)
    assert namespace["APP"] == "données_'quoted'_project"
    assert namespace["data_in"] == "entrée/測試"
    assert classify_pipeline_stage_template(stored).status is PipelineStageTemplateStatus.CURRENT


@pytest.mark.parametrize("change,reason", [
    ({"template_version": 0}, "older template version"),
    ({"template_version": 99}, "newer template version"),
    ({"template_fingerprint": "old-installed-renderer"}, "renderer fingerprint"),
    ({"payload_fingerprint": "polluted-session-payload"}, "payload fingerprint"),
    ({"C": "print('edited outside WORKFLOW')"}, "rendered Python differs"),
    ({"template_id": "missing"}, "unknown template"),
    ({"template_id": ""}, "missing template id"),
    ({"template_payload": {"schema": "future"}}, "payload schema"),
])
def test_drift_is_visible_and_cannot_run_without_mutating_source(change: dict, reason: str) -> None:
    stage = _stage() | change
    before = copy.deepcopy(stage)
    classification = classify_pipeline_stage_template(stage)
    assert classification.status is PipelineStageTemplateStatus.STALE
    assert reason in classification.reason
    with pytest.raises(ValueError, match="stale"):
        rendered_pipeline_stage_code(stage)
    assert stage == before


def test_same_version_changed_renderer_is_stale_and_refresh_is_explicit() -> None:
    old = PipelineStageTemplate("test.shape", "T", "Q", "x = 1\n", version=1)
    new = PipelineStageTemplate("test.shape", "T", "Q", "x = 1\nprint(x)\n", version=1)
    saved = old.saved_stage()
    registry = PipelineStageTemplateRegistry([new])
    assert classify_pipeline_stage_template(saved, registry=registry).reason == "template renderer fingerprint changed"
    refreshed = refresh_pipeline_stage_template(saved, registry=registry)
    assert saved["C"] == "x = 1\n"
    assert refreshed["C"] == "x = 1\nprint(x)\n"
    assert classify_pipeline_stage_template(refreshed, registry=registry).status is PipelineStageTemplateStatus.CURRENT


@pytest.mark.parametrize("parameters", [
    {"APP": "demo", "data_in": "in", "data_out": "out", "mode": "local", "injected": 1},
    {"APP": "demo"},
    {"APP": None, "data_in": "in", "data_out": "out", "mode": "local"},
    {"APP": float("nan"), "data_in": "in", "data_out": "out", "mode": "local"},
])
def test_malformed_or_polluted_parameters_are_rejected(parameters: dict) -> None:
    with pytest.raises(ValueError):
        REGISTRY.require("generic.configure").render({"schema": PIPELINE_STAGE_PAYLOAD_SCHEMA, "parameters": parameters})


def test_code_edit_detaches_without_rewriting_python_and_keeps_origin() -> None:
    previous = _stage()
    code = previous["C"] + "# manual custom code\nprint(APP)\n"
    result = normalize_pipeline_stage_for_save(previous | {"C": code}, previous=previous)
    assert result["kind"] == "raw_python"
    assert result["C"] == code
    assert result["template_origin"]["template_id"] == previous["template_id"]
    assert "template_id" not in result
    assert rendered_pipeline_stage_code(result) == code


def test_explicit_parameter_edit_is_still_a_template_and_stale_payload_is_not_hidden() -> None:
    previous = _stage()
    payload = copy.deepcopy(previous["template_payload"])
    payload["parameters"]["APP"] = "real_project"
    edited = refresh_pipeline_stage_template(previous, payload=payload)
    assert normalize_pipeline_stage_for_save(edited, previous=previous)["kind"] == "template"
    with pytest.raises(ValueError, match="payload fingerprint"):
        normalize_pipeline_stage_for_save(previous | {"template_payload": payload}, previous=previous)


def test_explicit_legacy_conversion_recognizes_only_exact_shapes_preserves_every_other_field() -> None:
    generated = {"Q": "Mine", "C": REGISTRY.require("generic.configure").code, "id": "configure",
                 "depends_on": ["before"], "outputs": ["out.csv"], "profiles": {"fast": {"retries": 3}}}
    custom_code = generated["C"] + "# custom annotation\nprint('custom')\n"
    custom = {"C": custom_code, "template_id": "generic.configure", "template_version": 0, "R": "runpy"}
    data = {"__meta__": {"project": "demo", "demo__sequence": [1, 0]}, "demo": [generated, custom]}
    before = copy.deepcopy(data)
    converted = convert_legacy_pipeline_stages(data)
    assert data == before
    assert converted["__meta__"] == data["__meta__"]
    assert converted["demo"][0]["kind"] == "template"
    for key in generated:
        assert converted["demo"][0][key] == generated[key]
    assert converted["demo"][1]["kind"] == "raw_python"
    assert converted["demo"][1]["C"] == custom_code
    assert convert_legacy_pipeline_stages(converted) == converted


def test_notebook_code_edits_detach_but_stale_metadata_stays_stale() -> None:
    stage = _stage()
    assert reconcile_imported_pipeline_template_stage(stage) == stage
    edited = stage | {"C": "print('notebook custom edit')\n"}
    result = reconcile_imported_pipeline_template_stage(edited)
    assert result["kind"] == "raw_python" and result["C"] == edited["C"]
    stale = edited | {"template_version": 99}
    assert reconcile_imported_pipeline_template_stage(stale) == stale


def test_app_action_template_uses_typed_run_request_and_preserves_args(monkeypatch: pytest.MonkeyPatch) -> None:
    stage = REGISTRY.saved_stage("pipeline.agi_run.single_action")
    payload = copy.deepcopy(stage["template_payload"])
    payload["parameters"].update(app="example_project", apps_path="/apps", action="allocate",
                                 args={"horizon": 16, "nested": {"label": "réseau"}})
    stage = refresh_pipeline_stage_template(stage, payload=payload)
    calls = []
    api = types.ModuleType("agi_cluster.agi_distributor")
    api.RunRequest = lambda **kwargs: SimpleNamespace(**kwargs)
    api.StageRequest = lambda **kwargs: SimpleNamespace(**kwargs)
    async def run(env, *, request):
        calls.append((env, request))
        return "computed"
    api.AGI = SimpleNamespace(run=run)
    env_module = types.ModuleType("agi_env")
    env_module.AgiEnv = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor", api)
    monkeypatch.setitem(sys.modules, "agi_env", env_module)
    namespace = {"__name__": "template_validation"}
    exec(rendered_pipeline_stage_code(stage), namespace)
    assert asyncio.run(namespace["main"]()) == "computed"
    env, request = calls[0]
    assert env.app == "example_project" and env.apps_path == "/apps"
    assert request.stages[0].name == "allocate"
    assert request.stages[0].args == payload["parameters"]["args"]


def test_conversion_preview_is_reviewable_guarded_and_retains_exact_source_backup(tmp_path: Path) -> None:
    from agilab.pipeline.pipeline_editor import apply_pipeline_stage_conversion, preview_pipeline_stage_conversion
    path = tmp_path / "lab_stages.toml"
    source = "# user notes survive in the backup\n" + tomli_w.dumps({"demo": [{"C": REGISTRY.require("generic.configure").code}]})
    path.write_text(source)
    preview = preview_pipeline_stage_conversion(path)
    assert path.read_text() == source
    assert preview["rows"][0]["kind"] == "template"
    path.write_text(source + "# another writer\n")
    with pytest.raises(ValueError, match="changed after conversion preview"):
        apply_pipeline_stage_conversion(path, preview)
    assert path.read_text().endswith("# another writer\n")
    fresh = preview_pipeline_stage_conversion(path)
    original = path.read_bytes()
    backup = apply_pipeline_stage_conversion(path, fresh)
    assert backup.read_bytes() == original
    assert tomllib.loads(path.read_text())["demo"][0]["kind"] == "template"


def test_workflow_save_and_force_persist_keep_template_or_custom_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agilab.pipeline import pipeline_editor as editor
    monkeypatch.setattr(editor, "toml_to_notebook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(editor, "st", SimpleNamespace(session_state={}, error=lambda text: pytest.fail(text)))
    path = tmp_path / "lab_stages.toml"
    stage = _stage()
    module = tmp_path / "demo_project"
    editor.save_stage(module, [stage["D"], stage["Q"], stage["M"], stage["C"]], 0, 0, path, extra_fields=stage)
    stored = next(value for key, value in tomllib.loads(path.read_text()).items() if key != "__meta__")[0]
    assert stored["kind"] == "template"
    custom_code = stored["C"] + "print('manual')\n"
    editor._force_persist_stage(module, path, 0, {"C": custom_code})
    stored = next(value for key, value in tomllib.loads(path.read_text()).items() if key != "__meta__")[0]
    assert stored["kind"] == "raw_python" and stored["C"] == custom_code
    assert "template_origin" in stored


def test_export_metadata_contains_template_contract_and_rejects_drift() -> None:
    from agilab.notebooks import notebook_export_support as export
    stage = _stage()
    record = export._stage_records({"demo": [stage]})[0]
    cell = export._stage_cell_metadata(record, kind="editable")
    metadata = cell["agilab"]["stage_cell"]
    assert metadata["template_payload"] == stage["template_payload"]
    assert metadata["template_fingerprint"] == stage["template_fingerprint"]
    changed = stage | {"template_fingerprint": "different-runtime"}
    with pytest.raises(ValueError, match="stale"):
        export._stage_records({"demo": [changed]})
    assert export.notebook_stage_fingerprint("demo", 0, changed) != export.notebook_stage_fingerprint("demo", 0, stage)


def test_plain_notebook_export_rejects_stale_cached_python() -> None:
    from agilab.notebooks import notebook_export_support as export
    stale = _stage() | {"template_version": 99}
    before = copy.deepcopy(stale)
    with pytest.raises(ValueError, match="newer template version"):
        export.build_notebook_document({"demo": [stale]}, Path("lab_stages.toml"))
    assert stale == before


def test_plain_notebook_export_renders_template_without_cached_python() -> None:
    from agilab.notebooks import notebook_export_support as export
    stage = _stage()
    expected_code = stage.pop("C")
    notebook = export.build_notebook_document({"demo": [stage]}, Path("lab_stages.toml"))
    assert len(notebook["cells"]) == 1
    exported_code = "".join(notebook["cells"][0]["source"])
    assert exported_code == expected_code
    namespace = {}
    exec(exported_code, namespace)
    assert namespace["APP"] == stage["template_payload"]["parameters"]["APP"]
    assert "C" not in stage


def test_actual_plain_notebook_writer_rejects_stale_export_before_replacing_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agilab.pipeline import pipeline_editor as editor
    errors = []
    monkeypatch.setattr(editor, "st", SimpleNamespace(session_state={}, error=errors.append))
    monkeypatch.setattr(editor, "resolve_pycharm_notebook_path", lambda *_args, **_kwargs: None)
    stages_file = tmp_path / "lab_stages.toml"
    notebook_path = stages_file.with_suffix(".ipynb")
    original = b'{"user_edits": "keep this exact notebook"}\n'
    notebook_path.write_bytes(original)
    stale = _stage() | {"template_version": 99}
    assert editor.toml_to_notebook({"demo": [stale]}, stages_file, force=True) is None
    assert notebook_path.read_bytes() == original
    assert len(errors) == 1 and "newer template version" in errors[0]
    current = _stage()
    expected_code = current.pop("C")
    assert editor.toml_to_notebook({"demo": [current]}, stages_file, force=True) == notebook_path
    notebook = json.loads(notebook_path.read_text())
    assert "".join(notebook["cells"][0]["source"]) == expected_code


def test_stage_without_cached_python_is_renderable_and_stale_stage_remains_visible() -> None:
    from agilab.pipeline.pipeline_stages import is_runnable_stage
    from agilab.workflow.lab_stages_contract import is_displayable_stage
    stage = _stage()
    stage.pop("C")
    assert is_displayable_stage(stage) and is_runnable_stage(stage)
    hydrated = stage | {"C": rendered_pipeline_stage_code(stage)}
    assert normalize_pipeline_stage_for_save(hydrated, previous=stage)["kind"] == "template"
    stage["template_version"] = 99
    assert is_displayable_stage(stage) and not is_runnable_stage(stage)


def test_static_workflow_validation_reports_template_drift_without_execution(tmp_path: Path) -> None:
    from agilab.workflow.workflow_validation import validate_lab_stages_file
    path = tmp_path / "lab_stages.toml"
    current = _stage()
    current.pop("C")
    path.write_text(tomli_w.dumps({"demo": [current]}))
    result = validate_lab_stages_file(path, module_key="demo")
    assert result["summary"]["error_count"] == 0
    current["template_version"] = 99
    path.write_text(tomli_w.dumps({"demo": [current]}))
    before = path.read_bytes()
    result = validate_lab_stages_file(path, module_key="demo")
    assert result["status"] == "fail"
    assert any(issue["check_id"] == "stage-template-drift" for issue in result["issues"])
    assert path.read_bytes() == before


def test_native_template_controls_accept_parameters_then_detach_custom_python() -> None:
    from agi_web.testing import AppTest
    def page():
        from agi_web import python_ui as ui
        from agilab.pipeline.pipeline_template_controls import render_new_pipeline_template, render_pipeline_template_controls
        result = render_new_pipeline_template(ui, key="new", app="demo_project")
        if result is not None:
            ui.session_state["stage"] = result
        if "stage" in ui.session_state:
            result = render_pipeline_template_controls(ui, ui.session_state["stage"], key="stage")
            if result is not None:
                ui.session_state["stage"] = result
    app = AppTest.from_function(page).run()
    assert not app.exception
    app.button(key="new_add_template").click().run()
    assert app.session_state["stage"]["kind"] == "template"
    app.button(key="stage_keep_python").click().run()
    assert app.session_state["stage"]["kind"] == "raw_python"
    assert not app.exception


def test_actual_workflow_runner_rejects_stale_template_before_lock_or_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agilab.pipeline import pipeline_run_controls as runner
    stage = _stage() | {"template_version": 99}
    messages = []
    state = {"page": [0, "", "", "", "", 1], "snippet_file": str(tmp_path / "snippet.py"),
             "page__run_sequence": [0]}
    monkeypatch.setattr(runner, "st", SimpleNamespace(session_state=state, error=messages.append))
    monkeypatch.setattr(runner, "_get_run_placeholder", lambda *_: None)
    monkeypatch.setattr(runner, "_push_run_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: pytest.fail("stale stage acquired a run lock"))
    runner.run_all_stages(
        tmp_path, "page", tmp_path / "lab_stages.toml", tmp_path / "demo_project", SimpleNamespace(),
        load_all_stages_fn=lambda *_: [stage],
        stream_run_command_fn=lambda *_args, **_kwargs: pytest.fail("stale stage executed"),
    )
    assert len(messages) == 1 and "newer template version" in messages[0]


def test_actual_locked_stage_runner_rejects_stale_template_before_environment_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    from agilab.pipeline.pipeline_runtime_execution_support import run_locked_stage
    from agi_web import python_ui as ui
    messages = []
    monkeypatch.setattr(ui, "error", messages.append)
    calls = []
    def unexpected(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("stale locked stage performed an execution action")
    run_locked_stage(
        SimpleNamespace(), "page", Path("unused.toml"), 0, _stage() | {"template_version": 99}, {}, {},
        normalize_runtime_path=unexpected, prepare_run_log_file=unexpected, push_run_log=unexpected,
        refresh_pipeline_run_lock=unexpected, acquire_pipeline_run_lock=unexpected, release_pipeline_run_lock=unexpected,
        get_run_placeholder=lambda *_: None, is_valid_runtime_root=unexpected, python_for_venv=unexpected,
        stream_run_command=unexpected, stage_summary=unexpected, label_for_stage_runtime_fn=unexpected,
        start_mlflow_run_fn=unexpected, build_mlflow_process_env_fn=unexpected, log_mlflow_artifacts_fn=unexpected,
        run_lab_fn=unexpected, python_for_stage_fn=unexpected, wrap_code_with_mlflow_resume_fn=unexpected,
    )
    assert not calls and len(messages) == 1 and "newer template version" in messages[0]


@pytest.mark.parametrize("relative_path", [
    "src/agilab/apps/builtin/mission_decision_project/lab_stages.toml",
    "src/agilab/apps/builtin/learning_assessment_project/lab_stages.toml",
    "src/agilab/apps/builtin/weather_forecast_project/lab_stages.toml",
    "src/agilab/apps/builtin/multi_app_dag_project/lab_stages.toml",
    "src/agilab/examples/notebook_to_dask/lab_stages.toml",
    "src/agilab/examples/notebook_migrations/skforecast_meteo_fr/migrated_project/lab_stages.toml",
])
def test_current_legacy_examples_keep_custom_code_dependencies_and_execution_metadata(relative_path: str) -> None:
    path = Path(__file__).resolve().parents[1] / relative_path
    source = path.read_bytes()
    data = tomllib.loads(source.decode("utf-8"))
    converted = convert_legacy_pipeline_stages(data)
    for module, entries in data.items():
        if module == "__meta__" or not isinstance(entries, list):
            assert converted[module] == entries
            continue
        for index, entry in enumerate(entries):
            result = converted[module][index]
            assert result["C"] == entry["C"]
            for key, value in entry.items():
                if key not in {"kind", "template_id", "template_version"}:
                    assert result[key] == value
    assert path.read_bytes() == source
