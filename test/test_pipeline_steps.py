from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import tomllib


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_steps = _load_module("agilab.pipeline_steps", "src/agilab/pipeline_steps.py")


def test_normalize_runtime_path_prefers_existing_app(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    app_dir = apps_root / "flight_project"
    app_dir.mkdir()

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)

    env = SimpleNamespace(apps_path=apps_root)
    normalized = pipeline_steps.normalize_runtime_path("flight_project", env=env)

    assert normalized == str(app_dir)


def test_module_key_normalization_and_sequence_roundtrip(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "flight_project"
    module_dir.mkdir(parents=True)
    steps_file = tmp_path / "lab_steps.toml"
    absolute_key = str(module_dir.resolve())
    steps_file.write_text(
        f'[[ "{absolute_key}" ]]\n'
        'Q = "First step"\n'
        'C = "print(1)"\n',
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    pipeline_steps.ensure_primary_module_key(module_dir, steps_file, env=env)
    pipeline_steps.persist_sequence_preferences(module_dir, steps_file, [2, 0, 1], env=env)

    data = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert "flight_project" in data
    assert absolute_key not in data
    assert pipeline_steps.load_sequence_preferences(module_dir, steps_file, env=env) == [2, 0, 1]


def test_get_available_virtualenvs_discovers_direct_and_nested_envs(monkeypatch, tmp_path):
    active_app = tmp_path / "apps" / "flight_project"
    apps_path = tmp_path / "apps"
    runenv = tmp_path / "runenv"
    direct = active_app / ".venv"
    nested = runenv / "worker_a"
    nested_venv = nested / ".venv"
    for path in (direct, nested_venv):
        path.mkdir(parents=True)
        (path / "pyvenv.cfg").write_text("home = /tmp/python\n", encoding="utf-8")

    env = SimpleNamespace(
        active_app=active_app,
        apps_path=apps_path,
        runenv=runenv,
        wenv_abs="",
        agi_env="",
    )

    pipeline_steps._cached_virtualenvs.clear()
    discovered = pipeline_steps.get_available_virtualenvs(env)

    assert direct.resolve() in discovered
    assert nested_venv.resolve() in discovered


def test_orchestrate_lock_helpers_cover_bool_and_question_forms():
    locked = {
        pipeline_steps.ORCHESTRATE_LOCKED_STEP_KEY: "yes",
        pipeline_steps.ORCHESTRATE_LOCKED_SOURCE_KEY: "AGI_run.py",
    }
    inferred = {"Q": "Imported snippet: generated_step.py"}

    assert pipeline_steps.is_orchestrate_locked_step(locked) is True
    assert pipeline_steps.orchestrate_snippet_source(locked) == "AGI_run.py"
    assert pipeline_steps.is_orchestrate_locked_step(inferred) is True
    assert pipeline_steps.orchestrate_snippet_source(inferred) == "generated_step.py"


def test_prune_invalid_entries_keeps_requested_index():
    entries = [
        {"Q": "Visible"},
        {"Q": "", "C": ""},
        {"C": "print('ok')"},
    ]

    pruned = pipeline_steps.prune_invalid_entries(entries, keep_index=1)

    assert pruned == entries
