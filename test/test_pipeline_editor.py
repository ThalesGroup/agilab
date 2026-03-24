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
