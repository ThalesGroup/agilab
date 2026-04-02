from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys
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


pipeline_editor = _load_module("agilab.pipeline_editor", "src/agilab/pipeline_editor.py")


def test_save_step_roundtrip_writes_toml_and_notebook(monkeypatch, tmp_path):
    fake_env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=tmp_path, envars={"OPENAI_MODEL": "gpt-x"})
    fake_st = SimpleNamespace(
        session_state={"_experiment_last_save_skipped": False, "env": fake_env},
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project"])
    monkeypatch.setattr(pipeline_editor, "_ensure_primary_module_key", lambda *_args, **_kwargs: None)

    steps_file = tmp_path / "lab_steps.toml"
    nsteps, entry = pipeline_editor.save_step(
        tmp_path / "flight_project",
        ["", "Describe step", "", "print('ok')"],
        current_step=0,
        nsteps=0,
        steps_file=steps_file,
        venv_map={0: str(tmp_path / "flight_project")},
        engine_map={0: "agi.run"},
    )

    stored = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    notebook = json.loads(steps_file.with_suffix(".ipynb").read_text(encoding="utf-8"))

    assert nsteps == 1
    assert entry["Q"] == "Describe step"
    assert entry["M"] == "gpt-x"
    assert stored["flight_project"][0]["R"] == "agi.run"
    assert notebook["cells"][0]["source"] == ["print('ok')"]


def test_remove_step_reindexes_state_and_sequence(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        """
[[flight_project]]
Q = "First"
C = "print(1)"
[[flight_project]]
Q = "Second"
C = "print(2)"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    fake_env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=tmp_path, envars={})
    fake_st = SimpleNamespace(
        session_state={
            "env": fake_env,
            "idx": [1, "", "", "", "", "", 2],
            "idx__details": {0: "d0", 1: "d1"},
            "idx__venv_map": {0: "/tmp/a", 1: "/tmp/b"},
            "idx__engine_map": {0: "runpy", 1: "agi.run"},
            "idx__run_sequence": [1, 0],
        },
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project"])
    monkeypatch.setattr(pipeline_editor, "_ensure_primary_module_key", lambda *_args, **_kwargs: None)

    remaining = pipeline_editor.remove_step(tmp_path / "flight_project", "0", steps_file, "idx")

    stored = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert remaining == 1
    assert stored["flight_project"][0]["Q"] == "Second"
    assert fake_st.session_state["idx__details"] == {0: "d1"}
    assert fake_st.session_state["idx__venv_map"] == {0: "/tmp/b"}
    assert fake_st.session_state["idx__engine_map"] == {0: "agi.run"}
    assert fake_st.session_state["idx__run_sequence"] == [0]


def test_notebook_to_toml_imports_code_cells(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(error=lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    notebook = {
        "cells": [
            {"cell_type": "markdown", "source": ["ignore"]},
            {"cell_type": "code", "source": ["print('a')\n"]},
            {"cell_type": "code", "source": ["print('b')\n"]},
        ]
    }
    uploaded = SimpleNamespace(read=lambda: json.dumps(notebook).encode("utf-8"))

    count = pipeline_editor.notebook_to_toml(uploaded, "lab_steps.toml", tmp_path / "flight_project")

    stored = tomllib.loads((tmp_path / "flight_project" / "lab_steps.toml").read_text(encoding="utf-8"))
    assert count == 2
    assert stored["flight_project"][0]["C"] == "print('a')\n"
    assert stored["flight_project"][1]["C"] == "print('b')\n"


def test_capture_and_restore_pipeline_snapshot(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(
        session_state={
            "idx__details": {0: "detail0", 1: "detail1", "bad": "skip"},
            "idx__venv_map": {0: str(tmp_path / "venv0"), 1: "", 9: "/skip"},
            "idx__engine_map": {0: "runpy", 1: "agi.run"},
            "idx__run_sequence": [1, 0, 99, "bad"],
            "idx": [1, "", "", "", "", "", 2],
            "lab_selected_venv": str(tmp_path / "venv0"),
            "lab_selected_engine": "agi.run",
            "idx__clear_q": True,
            "idx__force_blank_q": True,
            "idx__q_rev": 2,
            "idx_confirm_delete_all": True,
            "idx_sequence_widget": [1, 0],
        }
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "normalize_runtime_path", lambda value: str(value) if value else "")

    steps = [
        {"D": "d0", "Q": "q0", "M": "m0", "C": "c0", "E": str(tmp_path / "venv0"), "R": "runpy"},
        {"D": "d1", "Q": "q1", "M": "m1", "C": "c1", "E": str(tmp_path / "venv1"), "R": "agi.run"},
    ]
    snapshot = pipeline_editor._capture_pipeline_snapshot("idx", steps)

    writes = {}
    def _write_steps(module, steps_file, module_steps):
        writes["steps"] = module_steps
        return len(module_steps)

    monkeypatch.setattr(
        pipeline_editor,
        "_write_steps_for_module",
        _write_steps,
    )
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *args, **kwargs: writes.setdefault("sequence", args[2]))
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: writes.setdefault("bumped", True))
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda path: path.endswith("venv0"))

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "idx_sequence_widget",
        snapshot,
    )

    assert error is None
    assert fake_st.session_state["idx__details"] == {0: "detail0", 1: "detail1"}
    assert fake_st.session_state["idx__run_sequence"] == [1, 0]
    assert fake_st.session_state["lab_selected_venv"].endswith("venv0")
    assert fake_st.session_state["lab_selected_engine"] == "agi.run"
    assert fake_st.session_state["idx"][0] == 1
    assert fake_st.session_state["idx"][-1] == 2
    assert "idx_sequence_widget" not in fake_st.session_state
    assert writes["bumped"] is True


def test_reset_pipeline_editor_state_clears_editor_widget_keys(monkeypatch):
    fake_st = SimpleNamespace(
        session_state={
            "demo_q_step_0": "q",
            "demo_code_step_0": "c",
            "demo_venv_0": "v",
            "demo_keep": "ok",
            "demoa": "drop",
        }
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor._reset_pipeline_editor_state("demo")

    assert fake_st.session_state == {"demo_keep": "ok"}


def test_get_steps_list_and_dict_handle_invalid_files_and_alias_keys(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        "[[flight_project]]\nQ = 'first'\n"
        "[[flight]]\nQ = 'alias'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project", "flight"])

    steps = pipeline_editor.get_steps_list(tmp_path / "flight_project", steps_file)
    stored = pipeline_editor.get_steps_dict(tmp_path / "flight_project", steps_file)

    assert steps[0]["Q"] == "first"
    assert "flight" not in stored

    invalid_file = tmp_path / "broken.toml"
    invalid_file.write_text("[[flight_project]\n", encoding="utf-8")
    assert pipeline_editor.get_steps_list(tmp_path / "flight_project", invalid_file) == []
