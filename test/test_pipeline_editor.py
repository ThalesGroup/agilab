from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import ModuleSpec
import json
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest
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


def _prime_current_agilab_package() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = types.ModuleType("agilab")
    pkg.__path__ = [package_root_str]
    pkg.__file__ = str(package_root / "__init__.py")
    pkg.__package__ = "agilab"
    spec = ModuleSpec("agilab", loader=None, is_package=True)
    spec.submodule_search_locations = [package_root_str]
    pkg.__spec__ = spec
    sys.modules["agilab"] = pkg


def _load_pipeline_editor_with_missing(*missing_modules: str):
    _prime_current_agilab_package()
    module_name = f"agilab.pipeline_editor_fallback_{len(missing_modules)}_{abs(hash(missing_modules))}"
    for name in missing_modules:
        sys.modules.pop(name, None)
    original_import = __import__
    original_import_module = importlib.import_module

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            exc = ModuleNotFoundError(name)
            exc.name = name
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    def _patched_import_module(name, package=None):
        if name in missing_modules:
            exc = ModuleNotFoundError(name)
            exc.name = name
            raise exc
        return original_import_module(name, package)

    with (
        patch("builtins.__import__", _patched_import),
        patch("importlib.import_module", _patched_import_module),
    ):
        return _load_module(module_name, "src/agilab/pipeline_editor.py")


def _load_pipeline_editor_with_mixed_checkout(monkeypatch, stale_root: Path):
    module_name = "agilab.pipeline_editor_mixed_checkout"
    src_root = Path(__file__).resolve().parents[1] / "src"
    src_root_str = str(src_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = types.ModuleType("agilab")
    pkg.__path__ = [str(stale_root)]
    pkg.__file__ = str(stale_root / "__init__.py")
    pkg.__package__ = "agilab"
    spec = ModuleSpec("agilab", loader=None, is_package=True)
    spec.submodule_search_locations = [str(stale_root)]
    pkg.__spec__ = spec
    monkeypatch.setitem(sys.modules, "agilab", pkg)
    return _load_module(module_name, "src/agilab/pipeline_editor.py")


_prime_current_agilab_package()
pipeline_editor = _load_module("agilab.pipeline_editor", "src/agilab/pipeline_editor.py")
notebook_export_support = _load_module(
    "agilab.notebook_export_support",
    "src/agilab/notebook_export_support.py",
)


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


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


def test_remove_step_out_of_range_preserves_state_and_reports_save_error(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        "[[flight_project]]\nQ = 'First'\nC = 'print(1)'\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={
            "idx": [3, "", "", "", "", "", 1],
            "idx__details": {0: "d0"},
            "idx__venv_map": {0: "/tmp/a"},
            "idx__engine_map": {0: "runpy"},
            "idx__run_sequence": [0, 4],
        },
        error=lambda message, *args, **kwargs: errors.append(message),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project"])
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom"))),
    )

    remaining = pipeline_editor.remove_step(tmp_path / "flight_project", "7", steps_file, "idx")

    assert remaining == 1
    assert fake_st.session_state["idx"][0] == 0
    assert fake_st.session_state["idx__venv_map"] == {0: "/tmp/a"}
    assert fake_st.session_state["idx__engine_map"] == {0: "runpy"}
    assert fake_st.session_state["idx__run_sequence"] == [0]
    assert errors == ["Failed to save steps file: boom"]


def test_remove_step_middle_keeps_lower_indexes_and_rebuilds_default_sequence(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        """
[[flight_project]]
Q = "First"
C = "print(1)"
[[flight_project]]
Q = "Second"
C = "print(2)"
[[flight_project]]
Q = "Third"
C = "print(3)"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    fake_env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=tmp_path, envars={})
    fake_st = SimpleNamespace(
        session_state={
            "env": fake_env,
            "idx": [1, "", "", "", "", "", 3],
            "idx__details": {0: "d0", 1: "d1", 2: "d2"},
            "idx__venv_map": {0: "/tmp/a", 1: "/tmp/b", 2: "/tmp/c"},
            "idx__engine_map": {0: "runpy", 1: "agi.run", 2: "agi.custom"},
            "idx__run_sequence": [1],
        },
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project"])
    monkeypatch.setattr(pipeline_editor, "_ensure_primary_module_key", lambda *_args, **_kwargs: None)

    remaining = pipeline_editor.remove_step(tmp_path / "flight_project", "1", steps_file, "idx")

    assert remaining == 2
    assert fake_st.session_state["idx__details"] == {0: "d0", 1: "d2"}
    assert fake_st.session_state["idx__venv_map"] == {0: "/tmp/a", 1: "/tmp/c"}
    assert fake_st.session_state["idx__engine_map"] == {0: "runpy", 1: "agi.custom"}
    assert fake_st.session_state["idx__run_sequence"] == [0, 1]


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


def test_capture_pipeline_snapshot_falls_back_to_default_sequence_and_active_step(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(
        session_state={
            "idx__details": {"bad": "skip"},
            "idx__venv_map": {"bad": str(tmp_path / "venv")},
            "idx__engine_map": {"bad": "agi.run"},
            "idx__run_sequence": ["bad", 99],
            "idx": ["oops"],
            "lab_selected_venv": "",
            "lab_selected_engine": "",
        }
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "normalize_runtime_path", lambda value: str(value) if value else "")

    snapshot = pipeline_editor._capture_pipeline_snapshot(
        "idx",
        [{"D": "", "Q": "", "M": "", "C": "print(1)"}],
    )

    assert snapshot["details"] == {}
    assert snapshot["venv_map"] == {}
    assert snapshot["engine_map"] == {}
    assert snapshot["sequence"] == [0]
    assert snapshot["active_step"] == 0


def test_restore_pipeline_snapshot_skips_invalid_indices_and_rebuilds_default_page_state(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(
        session_state={
            "idx__details": {},
            "idx": "bad-state",
        }
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "normalize_runtime_path", lambda value: str(value) if value else "")
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_reset_pipeline_editor_state", lambda _index_page: None)
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda _path: False)
    monkeypatch.setattr(
        pipeline_editor,
        "_write_steps_for_module",
        lambda _module_path, _steps_file, module_steps: len(module_steps),
    )

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "idx_sequence_widget",
        {
            "steps": [{"Q": "q0", "C": "print(0)"}, {"Q": "q1", "C": "print(1)"}],
            "details": {"bad": "skip", "1": "detail1"},
            "venv_map": {"bad": "/tmp/skip", "1": "/tmp/runtime"},
            "engine_map": {"bad": "skip", "1": "agi.run"},
            "sequence": ["bad", 1, 1],
            "active_step": "bad",
        },
    )

    assert error is None
    assert fake_st.session_state["idx__details"] == {1: "detail1"}
    assert fake_st.session_state["idx__venv_map"] == {1: "/tmp/runtime"}
    assert fake_st.session_state["idx__engine_map"] == {1: "agi.run"}
    assert fake_st.session_state["idx__run_sequence"] == [1]
    assert fake_st.session_state["idx"][:6] == [0, "", "q0", "", "print(0)", ""]


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


def test_convert_paths_to_strings_and_query_validation():
    converted = pipeline_editor.convert_paths_to_strings({"paths": [Path("/tmp/demo"), {"nested": Path("rel")}]})
    assert converted == {"paths": ["/tmp/demo", {"nested": "rel"}]}
    assert pipeline_editor.is_query_valid([0, "desc", "question"]) is True
    assert pipeline_editor.is_query_valid([0, "desc", ""]) is False
    assert pipeline_editor.is_query_valid("not-a-query") is False


def test_pipeline_editor_top_level_helpers_cover_small_fallbacks(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pipeline_editor,
        "st",
        SimpleNamespace(success=lambda message: calls.append(("success", message))),
    )

    pipeline_editor._emit_streamlit_message("success", "saved")
    pipeline_editor._emit_streamlit_message("missing", "ignored")

    assert calls == [("success", "saved")]
    assert pipeline_editor._coerce_source_lines(None) == []
    assert pipeline_editor._coerce_source_lines("print(1)\nprint(2)") == ["print(1)\n", "print(2)"]
    assert pipeline_editor._coerce_source_lines((1, "two")) == ["1", "two"]
    assert pipeline_editor._coerce_source_lines(3) == ["3"]

    assert pipeline_editor._is_uploaded_notebook(None) is False
    assert pipeline_editor._is_uploaded_notebook(SimpleNamespace(name="demo.ipynb", type="")) is True
    assert pipeline_editor._is_uploaded_notebook(SimpleNamespace(name="demo.txt", type="text/plain")) is False
    assert pipeline_editor._is_uploaded_notebook(SimpleNamespace(name="", type="application/x-ipynb+json")) is True
    assert pipeline_editor._is_uploaded_notebook(SimpleNamespace(name="", type="")) is True

    assert pipeline_editor._read_uploaded_text(SimpleNamespace(read=lambda: "plain text")) == "plain text"
    assert pipeline_editor._read_uploaded_text(SimpleNamespace(read=lambda: b"bytes")) == "bytes"
    assert pipeline_editor._read_uploaded_text(SimpleNamespace(read=lambda: 42)) == "42"


def test_pipeline_editor_import_falls_back_when_pipeline_modules_are_unavailable():
    fallback = _load_pipeline_editor_with_missing("agilab.pipeline_runtime", "agilab.pipeline_steps")

    assert callable(fallback.get_steps_list)
    assert callable(fallback.save_step)


def test_pipeline_editor_import_falls_back_when_code_editor_support_is_unavailable():
    fallback = _load_pipeline_editor_with_missing("agilab.code_editor_support")

    assert callable(fallback.normalize_custom_buttons)
    with pytest.raises(TypeError, match="custom_buttons payload"):
        fallback.normalize_custom_buttons({"buttons": "invalid"})


def test_pipeline_editor_raises_mixed_checkout_error(monkeypatch, tmp_path):
    stale_root = tmp_path / "stale" / "agilab"
    stale_root.mkdir(parents=True)

    with pytest.raises(ImportError, match="Mixed AGILAB checkout detected"):
        _load_pipeline_editor_with_mixed_checkout(monkeypatch, stale_root)


def test_pipeline_editor_import_fallback_raises_when_local_specs_are_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_code_editor_spec(name, location, *args, **kwargs):
        if name == "agilab_code_editor_support_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_code_editor_spec)
    with pytest.raises(ModuleNotFoundError, match="code_editor_support"):
        _load_pipeline_editor_with_missing("agilab.code_editor_support")

    monkeypatch.setattr(importlib.util, "spec_from_file_location", original_spec)

    def _fake_runtime_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_runtime_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_runtime_spec)
    with pytest.raises(ModuleNotFoundError, match="pipeline_runtime"):
        _load_pipeline_editor_with_missing("agilab.pipeline_runtime")

    monkeypatch.setattr(importlib.util, "spec_from_file_location", original_spec)

    def _fake_steps_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_steps_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_steps_spec)
    with pytest.raises(ModuleNotFoundError, match="pipeline_steps"):
        _load_pipeline_editor_with_missing("agilab.pipeline_steps")


def test_save_query_invalid_still_exports_dataframe(monkeypatch, tmp_path):
    calls = {"exported": 0, "saved": 0}
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "export_df", lambda: calls.__setitem__("exported", calls["exported"] + 1))
    monkeypatch.setattr(
        pipeline_editor,
        "save_step",
        lambda *_args, **_kwargs: calls.__setitem__("saved", calls["saved"] + 1),
    )

    pipeline_editor.save_query(tmp_path / "flight_project", [0, "desc", ""], tmp_path / "lab_steps.toml", "idx")

    assert calls == {"exported": 1, "saved": 0}


def test_force_persist_step_merges_existing_content(tmp_path):
    module_dir = tmp_path / "flight_project"
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        "[[flight_project]]\nQ = 'first'\nC = 'print(1)'\n",
        encoding="utf-8",
    )

    with patch.object(pipeline_editor, "_module_keys", return_value=["flight_project"]):
        pipeline_editor._force_persist_step(
        module_dir,
        steps_file,
        0,
        {"D": "detail", "E": Path("/tmp/runtime")},
        )

    stored = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert stored["flight_project"][0]["Q"] == "first"
    assert stored["flight_project"][0]["D"] == "detail"
    assert stored["flight_project"][0]["E"] == "/tmp/runtime"


def test_force_persist_step_swallows_invalid_toml(monkeypatch, tmp_path):
    module_dir = tmp_path / "flight_project"
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("[[flight_project]\n", encoding="utf-8")
    logged: list[str] = []

    monkeypatch.setattr(pipeline_editor.logger, "error", logged.append)
    with patch.object(pipeline_editor, "_module_keys", return_value=["flight_project"]):
        pipeline_editor._force_persist_step(
            module_dir,
            steps_file,
            0,
            {"D": "detail"},
        )

    assert logged


def test_write_steps_for_module_normalizes_runtime_and_exports_notebook(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    notebook_calls: list[dict[str, object]] = []

    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project"])
    monkeypatch.setattr(
        pipeline_editor,
        "normalize_runtime_path",
        lambda value: f"normalized::{value}" if value else "",
    )
    monkeypatch.setattr(
        pipeline_editor,
        "toml_to_notebook",
        lambda steps, path: notebook_calls.append({"steps": steps, "path": path}),
    )

    count = pipeline_editor._write_steps_for_module(
        tmp_path / "flight_project",
        steps_file,
        [
            {"D": "demo", "Q": "q1", "M": "m1", "C": "print(1)", "E": tmp_path / "venv", "R": "agi.run"},
            {"D": "", "Q": "", "M": "", "C": ""},
        ],
    )

    stored = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert count == 1
    assert stored["flight_project"] == [
        {
            "D": "demo",
            "Q": "q1",
            "M": "m1",
            "C": "print(1)",
            "E": f"normalized::{tmp_path / 'venv'}",
            "R": "agi.run",
        }
    ]
    assert notebook_calls == [{"steps": stored, "path": steps_file}]


def test_save_step_preserves_existing_runtime_and_extra_fields(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        """
[[flight_project]]
Q = "first"
M = "model-a"
C = "print(1)"
E = "/tmp/runtime"
R = "agi.run"
LOCKED = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={"_experiment_last_save_skipped": False}, error=lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project"])
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)

    nsteps, entry = pipeline_editor.save_step(
        tmp_path / "flight_project",
        ["detail", "updated question", "updated-model", "print(2)"],
        current_step=0,
        nsteps=1,
        steps_file=steps_file,
        extra_fields={"LOCKED": None, "SOURCE": "copied"},
    )

    stored = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert nsteps == 1
    assert entry["E"] == "/tmp/runtime"
    assert entry["R"] == "agi.run"
    assert "LOCKED" not in entry
    assert entry["SOURCE"] == "copied"
    assert stored["flight_project"][0]["SOURCE"] == "copied"
    assert stored["flight_project"][0]["E"] == "/tmp/runtime"
    assert stored["flight_project"][0]["R"] == "agi.run"


def test_save_step_merges_alias_entries_and_reports_dump_failure(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        """
[[flight]]
Q = "alias only"
C = "print('alias')"
[[flight]]
Q = "alias second"
C = "print('second')"
[[flight_project]]
Q = "short"
C = "print('short')"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"_experiment_last_save_skipped": False},
        error=lambda message, *args, **kwargs: errors.append(message),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project", "flight"])
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("save boom"))),
    )

    nsteps, entry = pipeline_editor.save_step(
        tmp_path / "flight_project",
        ["detail", "question", "model", "print(3)"],
        current_step=1,
        nsteps=2,
        steps_file=steps_file,
    )

    assert nsteps == 2
    assert entry["Q"] == "question"
    assert fake_st.session_state["_experiment_last_save_skipped"] is True
    assert errors == ["Failed to save steps file: save boom"]


def test_save_query_valid_uses_runtime_and_engine_maps(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(
        session_state={
            "idx__venv_map": {0: "/tmp/runtime"},
            "idx__engine_map": {0: "agi.run"},
        }
    )
    calls: dict[str, object] = {}
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(
        pipeline_editor,
        "save_step",
        lambda module, query, current_step, nsteps, steps_file, venv_map=None, engine_map=None: (
            calls.setdefault("query", query),
            calls.setdefault("venv_map", venv_map),
            calls.setdefault("engine_map", engine_map),
            (4, {"Q": query[1]}),
        )[-1],
    )
    monkeypatch.setattr(pipeline_editor, "export_df", lambda: calls.setdefault("exported", True))
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: calls.setdefault("bumped", True))

    pipeline_editor.save_query(
        tmp_path / "flight_project",
        [0, "detail", "question", "model", "print(1)", 2],
        tmp_path / "lab_steps.toml",
        "idx",
    )

    assert calls["query"] == ["detail", "question", "model", "print(1)"]
    assert calls["venv_map"] == {0: "/tmp/runtime"}
    assert calls["engine_map"] == {0: "agi.run"}
    assert calls["bumped"] is True
    assert calls["exported"] is True


def test_restore_pipeline_snapshot_reports_write_failure(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(
        pipeline_editor,
        "_write_steps_for_module",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("write boom")),
    )

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "sequence_widget",
        {"steps": []},
    )

    assert error == "write boom"


def test_restore_pipeline_snapshot_reports_invalid_snapshot_payload(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "sequence_widget",
        None,
    )

    assert error == "'NoneType' object has no attribute 'get'"


def test_restore_pipeline_snapshot_resets_empty_state(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [4, "stale", "stale", "stale", "stale", "stale", 9]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_write_steps_for_module", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "sequence_widget",
        {"steps": [], "sequence": []},
    )

    assert error is None
    assert fake_st.session_state["idx"] == [0, "", "", "", "", "", 0]
    assert fake_st.session_state["lab_selected_venv"] == ""
    assert fake_st.session_state["lab_selected_engine"] == "runpy"


def test_on_import_notebook_ignores_non_ipynb(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"upload": SimpleNamespace(type="text/plain")})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_steps.toml", "idx")

    assert "page_broken" not in fake_st.session_state


def test_on_import_notebook_imports_ipynb_and_marks_page_broken(monkeypatch, tmp_path):
    uploaded = SimpleNamespace(type="application/x-ipynb+json")
    fake_st = SimpleNamespace(session_state=_State({"upload": uploaded, "idx": [0, "", "", "", "", "", 0]}))
    calls: dict[str, object] = {}
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    def _fake_notebook_to_toml(uploaded_file, toml_name, module_dir):
        calls["args"] = (uploaded_file, toml_name, module_dir)
        return 3

    monkeypatch.setattr(pipeline_editor, "notebook_to_toml", _fake_notebook_to_toml)

    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_steps.toml", "idx")

    assert calls["args"][0] is uploaded
    assert fake_st.session_state["idx"][-1] == 3
    assert fake_st.session_state["page_broken"] is True


def test_display_history_tab_filters_and_saves_editor_content(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        "[[demo_project]]\nQ = 'kept'\nC = 'print(1)'\n",
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={}, error=lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_editor, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_editor, "get_css_text", lambda: "")
    monkeypatch.setattr(
        pipeline_editor,
        "code_editor",
        lambda *_args, **_kwargs: {
            "type": "save",
            "text": json.dumps(
                {
                    "demo_project": [
                        {"Q": "visible", "C": "print(2)"},
                        {"Q": "", "C": ""},
                    ]
                }
            ),
        },
    )
    revisions: list[bool] = []
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: revisions.append(True))

    pipeline_editor.display_history_tab(steps_file, tmp_path / "demo_project")

    stored = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert stored["demo_project"] == [{"Q": "visible", "C": "print(2)"}]
    assert revisions == [True]


def test_toml_and_notebook_exports_report_errors(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message, *args, **kwargs: errors.append(message))
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    monkeypatch.setattr(
        pipeline_editor.json,
        "dump",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("nb boom")),
    )
    pipeline_editor.toml_to_notebook({"demo_project": [{"C": "print(1)"}]}, tmp_path / "lab_steps.toml")

    uploaded = SimpleNamespace(
        read=lambda: json.dumps({"cells": [{"cell_type": "code", "source": ["print(2)"]}]}).encode("utf-8")
    )
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("toml boom"))),
    )
    count = pipeline_editor.notebook_to_toml(uploaded, "lab_steps.toml", tmp_path / "demo_project")

    assert count == 1
    assert errors == [
        "Failed to save notebook: nb boom",
        "Failed to save TOML file: toml boom",
    ]


def test_save_step_handles_invalid_indices_and_runtime_map_failures(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    errors: list[str] = []

    class _BrokenEnv:
        @property
        def envars(self):
            raise RuntimeError("env boom")

    class _BrokenMap(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("map boom")

    fake_st = SimpleNamespace(
        session_state={"_experiment_last_save_skipped": False, "env": _BrokenEnv()},
        error=lambda message, *args, **kwargs: errors.append(message),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_project"])
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)

    nsteps, entry = pipeline_editor.save_step(
        tmp_path / "flight_project",
        ["detail", "question", "model", 42],
        current_step="bad",
        nsteps="bad",
        steps_file=steps_file,
        venv_map=_BrokenMap(),
        engine_map=_BrokenMap(),
    )

    stored = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert nsteps == 1
    assert entry["E"] == ""
    assert entry["R"] == ""
    assert entry["C"] == "42"
    assert stored["flight_project"][0]["C"] == "42"
    assert errors == []


def test_force_persist_step_swallows_dump_failures(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    failures: list[str] = []
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("dump boom"))),
    )
    monkeypatch.setattr(
        pipeline_editor.logger,
        "error",
        lambda message, *args: failures.append(message % args if args else message),
    )

    pipeline_editor._force_persist_step(tmp_path / "flight_project", steps_file, 2, {"Q": "late"})

    assert failures == [f"Force persist failed for step 2 -> {steps_file}: dump boom"]


def test_notebook_to_toml_and_refresh_cover_import_failures(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pipeline_editor,
        "st",
        SimpleNamespace(
            error=lambda message, *args, **kwargs: messages.append(("error", message)),
            warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
            success=lambda message, *args, **kwargs: messages.append(("success", message)),
        ),
    )

    assert pipeline_editor.notebook_to_toml(None, "lab_steps.toml", tmp_path / "demo_project") == 0
    assert (
        pipeline_editor.notebook_to_toml(
            SimpleNamespace(name="demo.txt", type="text/plain", read=lambda: b"{}"),
            "lab_steps.toml",
            tmp_path / "demo_project",
        )
        == 0
    )
    assert (
        pipeline_editor.notebook_to_toml(
            SimpleNamespace(name="demo.ipynb", type="application/x-ipynb+json", read=lambda: b"{"),
            "lab_steps.toml",
            tmp_path / "demo_project",
        )
        == 0
    )
    assert (
        pipeline_editor.notebook_to_toml(
            SimpleNamespace(name="demo.ipynb", type="application/x-ipynb+json", read=lambda: b"[]"),
            "lab_steps.toml",
            tmp_path / "demo_project",
        )
        == 0
    )

    broken_steps = tmp_path / "broken.toml"
    broken_steps.write_text("[[demo_project]\n", encoding="utf-8")
    assert pipeline_editor.refresh_notebook_export(tmp_path / "missing.toml") is None
    assert pipeline_editor.refresh_notebook_export(broken_steps) is None

    assert messages == [
        ("error", "No uploaded notebook provided."),
        ("error", "Please upload a .ipynb file."),
        ("error", "Unable to parse notebook: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"),
        ("error", "Invalid notebook format: expected a JSON object."),
        ("error", f"Unable to export notebook: failed to load {broken_steps}: Expected ']]' at the end of an array declaration (at line 1, column 15)"),
    ]


def test_on_import_notebook_reports_missing_upload_and_empty_code_cells(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    fake_st = SimpleNamespace(
        session_state=_State({"idx": [0, "", "", "", "", "", 0]}),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
        success=lambda message, *args, **kwargs: messages.append(("success", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_steps.toml", "idx")

    fake_st.session_state["upload"] = SimpleNamespace(type="application/x-ipynb+json")
    monkeypatch.setattr(pipeline_editor, "notebook_to_toml", lambda *_args, **_kwargs: 0)
    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_steps.toml", "idx")

    assert messages == [
        ("error", "No notebook file was uploaded."),
        ("warning", "Notebook imported, but no code cells were found."),
    ]
    assert fake_st.session_state["page_broken"] is True


def test_display_history_tab_covers_missing_file_and_save_error(monkeypatch, tmp_path):
    errors: list[str] = []
    fake_st = SimpleNamespace(session_state={}, error=lambda message, *args, **kwargs: errors.append(message))
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_editor, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_editor, "get_css_text", lambda: "")

    editor_payloads: list[str] = []

    def _code_editor(code, **_kwargs):
        editor_payloads.append(code)
        return {"type": "save", "text": "{bad json"}

    monkeypatch.setattr(pipeline_editor, "code_editor", _code_editor)

    pipeline_editor.display_history_tab(tmp_path / "missing.toml", tmp_path / "demo_project")

    assert editor_payloads == ["{}"]
    assert errors == ["Failed to save steps file from editor: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"]


def test_pipeline_editor_additional_branch_coverage(monkeypatch, tmp_path):
    empty_steps = tmp_path / "empty.toml"
    empty_steps.write_text("demo = { value = 1 }\n", encoding="utf-8")
    assert pipeline_editor.get_steps_list(tmp_path / "demo_project", empty_steps) == []

    monkeypatch.setattr(pipeline_editor, "_prune_invalid_entries", lambda steps, keep_index=None: steps)
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)
    count = pipeline_editor._write_steps_for_module(
        tmp_path / "demo_project",
        tmp_path / "lab_steps.toml",
        [{"Q": "keep"}, "skip-me"],
    )
    assert count == 1

    fake_st = SimpleNamespace(
        session_state={
            "idx": ["bad", "", "", "", "", "", 0],
            "idx__details": {0: "detail"},
            "idx__venv_map": {},
            "idx__engine_map": {},
            "idx__run_sequence": [],
        }
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "normalize_runtime_path", lambda value: str(value) if value else "")
    snapshot = pipeline_editor._capture_pipeline_snapshot("idx", [{"Q": "keep"}, "skip"])
    assert snapshot["steps"] == [{"D": "", "Q": "keep", "M": "", "C": "", "E": "", "R": ""}]
    assert snapshot["active_step"] == 0

    monkeypatch.setattr(pipeline_editor, "_write_steps_for_module", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_reset_pipeline_editor_state", lambda _index_page: None)
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda _path: False)
    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "demo_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "idx_sequence_widget",
        {"steps": "not-a-list", "sequence": []},
    )
    assert error is None
    assert fake_st.session_state["idx__run_sequence"] == [0]

    fake_st = SimpleNamespace(
        session_state={"env": SimpleNamespace(envars={}), "_experiment_last_save_skipped": False},
        error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["demo_project"])
    monkeypatch.setattr(pipeline_editor, "_looks_like_step", lambda value: str(value) == "1")
    monkeypatch.setattr(pipeline_editor, "_prune_invalid_entries", lambda steps, keep_index=None: steps)
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)
    nsteps, entry = pipeline_editor.save_step(
        tmp_path / "demo_project",
        ["1", "desc", "question", "model", "print(1)"],
        current_step=0,
        nsteps=0,
        steps_file=tmp_path / "save_steps.toml",
        venv_map={},
        engine_map={},
    )
    assert nsteps == 1
    assert entry["D"] == "desc"
    assert entry["Q"] == "question"
    assert entry["M"] == "model"
    assert entry["C"] == "print(1)"



def test_toml_to_notebook_handles_meta_string_steps_and_blank_entries(tmp_path):
    toml_path = tmp_path / "lab_steps.toml"

    pipeline_editor.toml_to_notebook(
        {
            "__meta__": {"ignored": True},
            "demo_project": [
                "print('raw')\n",
                {"C": ""},
                {"C": "print('dict')\n"},
            ],
        },
        toml_path,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    assert [cell["source"] for cell in notebook["cells"]] == [["print('raw')\n"], ["print('dict')\n"]]
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"
    assert notebook["metadata"]["language_info"]["name"] == "python"
    assert "pycharm" in notebook["metadata"]


def test_build_notebook_export_context_reads_related_pages_from_app_settings(tmp_path):
    pages_root = tmp_path / "apps-pages"
    page_script = pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True, exist_ok=True)
    page_script.write_text("print('page')\n", encoding="utf-8")

    source_app = tmp_path / "apps" / "demo_project"
    source_settings = source_app / "src" / "app_settings.toml"
    source_settings.parent.mkdir(parents=True, exist_ok=True)
    source_settings.write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")
    (source_app / "notebook_export.toml").write_text(
        """
[notebook_export]

[[notebook_export.related_pages]]
module = "view_demo"
label = "Demo Analysis"
description = "Inspect demo artifacts."
artifacts = ["demo.json", "demo.csv"]
launch_note = "Open this after the run."
""".strip()
        + "\n",
        encoding="utf-8",
    )

    workspace_settings = tmp_path / ".agilab" / "apps" / "demo_project" / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    env = SimpleNamespace(
        AGILAB_PAGES_ABS=pages_root,
        active_app=source_app,
        app_settings_file=workspace_settings,
        resolve_user_app_settings_file=lambda app_name, ensure_exists=False: workspace_settings,
        find_source_app_settings_file=lambda app_name: source_settings,
        read_agilab_path=lambda: tmp_path,
    )

    context = pipeline_editor.build_notebook_export_context(
        env,
        Path("demo_project"),
        tmp_path / "export" / "demo_project" / "lab_steps.toml",
        project_name="demo_project",
    )

    assert context.project_name == "demo_project"
    assert context.active_app == str(source_app)
    assert context.app_settings_file == str(workspace_settings)
    assert tuple(page.module for page in context.related_pages) == ("view_demo",)
    assert context.related_pages[0].label == "Demo Analysis"
    assert context.related_pages[0].description == "Inspect demo artifacts."
    assert context.related_pages[0].artifacts == ("demo.json", "demo.csv")
    assert context.related_pages[0].launch_note == "Open this after the run."
    assert context.related_pages[0].script_path == str(page_script.resolve())


@pytest.mark.parametrize(
    ("app_name", "expected_modules", "expected_label"),
    [
        (
            "uav_queue_project",
            ("view_uav_queue_analysis", "view_maps_network"),
            "UAV Queue Analysis",
        ),
        (
            "uav_relay_queue_project",
            ("view_uav_relay_queue_analysis", "view_maps_network"),
            "UAV Relay Queue Analysis",
        ),
    ],
)
def test_build_notebook_export_context_enriches_builtin_uav_pages_from_manifest(
    tmp_path,
    app_name,
    expected_modules,
    expected_label,
):
    repo_root = Path(__file__).resolve().parents[1]
    source_app = repo_root / "src" / "agilab" / "apps" / "builtin" / app_name
    source_settings = source_app / "src" / "app_settings.toml"
    workspace_settings = tmp_path / ".agilab" / "apps" / app_name / "app_settings.toml"
    pages_root = repo_root / "src" / "agilab" / "apps-pages"

    env = SimpleNamespace(
        AGILAB_PAGES_ABS=pages_root,
        active_app=source_app,
        app_settings_file=workspace_settings,
        resolve_user_app_settings_file=lambda app_name, ensure_exists=False: workspace_settings,
        find_source_app_settings_file=lambda app_name: source_settings,
        read_agilab_path=lambda: repo_root,
    )

    context = pipeline_editor.build_notebook_export_context(
        env,
        Path(app_name),
        tmp_path / "export" / app_name / "lab_steps.toml",
        project_name=app_name,
    )

    assert tuple(page.module for page in context.related_pages) == expected_modules
    assert context.related_pages[0].label == expected_label
    assert context.related_pages[0].description
    assert context.related_pages[0].artifacts
    assert context.related_pages[0].launch_note
    assert context.related_pages[0].script_path.endswith(f"{expected_modules[0]}.py")
    assert context.related_pages[1].label == "Maps Network"
    assert "pipeline/topology.gml" in context.related_pages[1].artifacts
    assert context.related_pages[1].script_path.endswith("view_maps_network.py")


def test_toml_to_notebook_with_export_context_embeds_supervisor_metadata_and_analysis_helpers(tmp_path):
    toml_path = tmp_path / "lab_steps.toml"
    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(tmp_path),
        active_app=str(tmp_path / "apps" / "demo_project"),
        app_settings_file=str(tmp_path / ".agilab" / "apps" / "demo_project" / "app_settings.toml"),
        pages_root=str(tmp_path / "apps-pages"),
        repo_root=str(tmp_path),
        related_pages=(
            notebook_export_support.RelatedPageExport(
                module="view_demo",
                label="Demo Analysis",
                description="Inspect demo artifacts.",
                artifacts=("demo.json", "demo.csv"),
                launch_note="Open this after the run.",
                script_path=str(tmp_path / "apps-pages" / "view_demo" / "src" / "view_demo" / "view_demo.py"),
            ),
        ),
    )

    pipeline_editor.toml_to_notebook(
        {
            "demo_project": [
                {
                    "D": "Prepare data",
                    "Q": "load and clean",
                    "M": "gpt-demo",
                    "C": "print('step-0')\n",
                    "E": str(tmp_path / "venv-demo"),
                    "R": "agi.run",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    metadata = notebook["metadata"]["agilab"]
    helper_source = "".join(notebook["cells"][1]["source"])
    page_markdown = "".join(notebook["cells"][-2]["source"])
    analysis_source = "".join(notebook["cells"][-1]["source"])

    assert metadata["export_mode"] == "supervisor"
    assert metadata["project_name"] == "demo_project"
    assert metadata["controller_python"] == sys.executable
    assert metadata["steps"][0]["runtime"] == "agi.run"
    assert metadata["steps"][0]["env"] == str(tmp_path / "venv-demo")
    assert metadata["related_pages"][0]["module"] == "view_demo"
    assert metadata["related_pages"][0]["label"] == "Demo Analysis"
    assert metadata["related_pages"][0]["artifacts"] == ["demo.json", "demo.csv"]
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"
    assert notebook["metadata"]["language_info"]["name"] == "python"
    assert "run_agilab_step" in helper_source
    assert "run_agilab_pipeline" in helper_source
    assert "analysis_launch_command" in helper_source
    assert "controller_python = AGILAB_NOTEBOOK_EXPORT.get(\"controller_python\")" in helper_source
    assert "Demo Analysis" in page_markdown
    assert "`demo.json`" in page_markdown
    assert "Open this after the run." in page_markdown
    assert "view_demo" in analysis_source
    assert notebook["cells"][3]["source"] == ["print('step-0')\n"]


def test_notebook_to_toml_skips_non_code_and_empty_code_cells(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(error=lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    uploaded = SimpleNamespace(
        name="demo.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["ignore"]},
                    {"cell_type": "code", "source": []},
                    {"cell_type": "code", "source": ["print(3)\n"]},
                ]
            }
        ).encode("utf-8"),
    )

    count = pipeline_editor.notebook_to_toml(uploaded, "lab_steps.toml", tmp_path / "demo_project")

    stored = tomllib.loads((tmp_path / "demo_project" / "lab_steps.toml").read_text(encoding="utf-8"))
    assert count == 1
    assert stored["demo_project"] == [{"D": "", "Q": "", "C": "print(3)\n", "M": ""}]


def test_notebook_to_toml_uses_lab_steps_key_when_module_dir_has_no_name(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(error=lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.chdir(tmp_path)

    uploaded = SimpleNamespace(
        name="demo.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(
            {"cells": [{"cell_type": "code", "source": ["print(9)\n"]}]}
        ).encode("utf-8"),
    )

    count = pipeline_editor.notebook_to_toml(uploaded, "lab_steps.toml", Path(""))

    stored = tomllib.loads((tmp_path / "lab_steps.toml").read_text(encoding="utf-8"))
    assert count == 1
    assert stored["lab_steps"] == [{"D": "", "Q": "", "C": "print(9)\n", "M": ""}]


def test_restore_pipeline_snapshot_rebuilds_engine_from_map_when_selection_missing(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_write_steps_for_module", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda _path: False)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "sequence_widget",
        {
            "steps": [{}],
            "engine_map": {0: "agi.run"},
            "selected_engine": "",
            "selected_venv": "/invalid/runtime",
            "sequence": [0],
        },
    )

    assert error is None
    assert fake_st.session_state["lab_selected_venv"] == ""
    assert fake_st.session_state["lab_selected_engine"] == "agi.run"


def test_restore_pipeline_snapshot_handles_non_dict_active_entry(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [0, "stale", "stale", "stale", "stale", "stale", 0]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_write_steps_for_module", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda _path: False)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_project",
        tmp_path / "lab_steps.toml",
        "idx",
        "sequence_widget",
        {
            "steps": ["not-a-dict"],
            "active_step": 0,
            "sequence": [0],
        },
    )

    assert error is None
    assert fake_st.session_state["idx"][:6] == [0, "", "", "", "", ""]
