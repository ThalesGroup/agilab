from __future__ import annotations

import importlib
import importlib.util
from importlib.machinery import ModuleSpec
import json
import os
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


class _LazyModuleProxy:
    def __init__(self, loader):
        object.__setattr__(self, "_loader", loader)
        object.__setattr__(self, "_module", None)

    def _load(self):
        module = object.__getattribute__(self, "_module")
        if module is None:
            module = object.__getattribute__(self, "_loader")()
            object.__setattr__(self, "_module", module)
        return module

    def __getattr__(self, name):
        return getattr(self._load(), name)

    def __setattr__(self, name, value):
        if name in {"_loader", "_module"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._load(), name, value)

    def __delattr__(self, name):
        if name in {"_loader", "_module"}:
            object.__delattr__(self, name)
            return
        delattr(self._load(), name)


pipeline_editor = _LazyModuleProxy(
    lambda: (
        _prime_current_agilab_package(),
        _load_module("agilab.pipeline_editor", "src/agilab/pipeline_editor.py"),
    )[1]
)
notebook_export_support = _LazyModuleProxy(
    lambda: (
        _prime_current_agilab_package(),
        _load_module("agilab.notebook_export_support", "src/agilab/notebook_export_support.py"),
    )[1]
)


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def test_save_stage_roundtrip_writes_toml_and_notebook(monkeypatch, tmp_path):
    fake_env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=tmp_path, envars={"OPENAI_MODEL": "gpt-x"})
    fake_st = SimpleNamespace(
        session_state={"_experiment_last_save_skipped": False, "env": fake_env},
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(pipeline_editor, "_ensure_primary_module_key", lambda *_args, **_kwargs: None)

    stages_file = tmp_path / "lab_stages.toml"
    nstages, entry = pipeline_editor.save_stage(
        tmp_path / "flight_telemetry_project",
        ["", "Describe stage", "", "print('ok')"],
        current_stage=0,
        nstages=0,
        stages_file=stages_file,
        venv_map={0: str(tmp_path / "flight_telemetry_project")},
        engine_map={0: "agi.run"},
    )

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    notebook = json.loads(stages_file.with_suffix(".ipynb").read_text(encoding="utf-8"))

    assert nstages == 1
    assert entry["Q"] == "Describe stage"
    assert entry["M"] == "gpt-x"
    assert stored["__meta__"] == {
        "schema": "agilab.lab_stages.v1",
        "version": 1,
    }
    assert stored["flight_telemetry_project"][0]["R"] == "agi.run"
    assert notebook["cells"][0]["source"] == ["print('ok')"]


def test_remove_stage_reindexes_state_and_sequence(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        """
[[flight_telemetry_project]]
Q = "First"
C = "print(1)"
[[flight_telemetry_project]]
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
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(pipeline_editor, "_ensure_primary_module_key", lambda *_args, **_kwargs: None)

    remaining = pipeline_editor.remove_stage(tmp_path / "flight_telemetry_project", "0", stages_file, "idx")

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert remaining == 1
    assert stored["flight_telemetry_project"][0]["Q"] == "Second"
    assert fake_st.session_state["idx__details"] == {0: "d1"}
    assert fake_st.session_state["idx__venv_map"] == {0: "/tmp/b"}
    assert fake_st.session_state["idx__engine_map"] == {0: "agi.run"}
    assert fake_st.session_state["idx__run_sequence"] == [0]


def test_remove_stage_out_of_range_preserves_state_and_reports_save_error(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        "[[flight_telemetry_project]]\nQ = 'First'\nC = 'print(1)'\n",
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
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom"))),
    )

    remaining = pipeline_editor.remove_stage(tmp_path / "flight_telemetry_project", "7", stages_file, "idx")

    assert remaining == 1
    assert fake_st.session_state["idx"][0] == 0
    assert fake_st.session_state["idx__venv_map"] == {0: "/tmp/a"}
    assert fake_st.session_state["idx__engine_map"] == {0: "runpy"}
    assert fake_st.session_state["idx__run_sequence"] == [0]
    assert errors == ["Failed to save stage contract: boom"]


def test_remove_stage_middle_keeps_lower_indexes_and_rebuilds_default_sequence(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        """
[[flight_telemetry_project]]
Q = "First"
C = "print(1)"
[[flight_telemetry_project]]
Q = "Second"
C = "print(2)"
[[flight_telemetry_project]]
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
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(pipeline_editor, "_ensure_primary_module_key", lambda *_args, **_kwargs: None)

    remaining = pipeline_editor.remove_stage(tmp_path / "flight_telemetry_project", "1", stages_file, "idx")

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

    count = pipeline_editor.notebook_to_toml(uploaded, "lab_stages.toml", tmp_path / "flight_telemetry_project")

    stored = tomllib.loads((tmp_path / "flight_telemetry_project" / "lab_stages.toml").read_text(encoding="utf-8"))
    assert count == 2
    assert stored["flight_telemetry_project"][0]["C"] == "print('a')\n"
    assert stored["flight_telemetry_project"][1]["C"] == "print('b')\n"
    assert stored["flight_telemetry_project"][0]["D"] == "ignore"
    assert stored["flight_telemetry_project"][0]["NB_CELL_ID"] == "cell-2"
    assert stored["flight_telemetry_project"][0]["NB_CONTEXT_IDS"] == ["markdown-1"]
    assert stored["flight_telemetry_project"][1]["NB_CELL_ID"] == "cell-3"


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

    stages = [
        {
            "D": "d0",
            "Q": "q0",
            "M": "m0",
            "C": "c0",
            "E": str(tmp_path / "venv0"),
            "R": "runpy",
            "template_id": "generic.execute",
            "template_version": 1,
            "custom_contract": {"schema_version": 1},
        },
        {"D": "d1", "Q": "q1", "M": "m1", "C": "c1", "E": str(tmp_path / "venv1"), "R": "agi.run"},
    ]
    snapshot = pipeline_editor._capture_pipeline_snapshot("idx", stages)
    assert snapshot["stages"][0]["template_id"] == "generic.execute"
    assert snapshot["stages"][0]["template_version"] == 1
    assert snapshot["stages"][0]["custom_contract"] == {"schema_version": 1}

    writes = {}
    def _write_stages(module, stages_file, module_stages):
        writes["stages"] = module_stages
        return len(module_stages)

    monkeypatch.setattr(
        pipeline_editor,
        "_write_stages_for_module",
        _write_stages,
    )
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *args, **kwargs: writes.setdefault("sequence", args[2]))
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: writes.setdefault("bumped", True))
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda path: path.endswith("venv0"))

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_telemetry_project",
        tmp_path / "lab_stages.toml",
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
    assert writes["stages"][0]["template_id"] == "generic.execute"
    assert writes["stages"][0]["template_version"] == 1
    assert writes["stages"][0]["custom_contract"] == {"schema_version": 1}


def test_write_stages_for_module_preserves_stage_contract_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(pipeline_editor, "get_stages_dict", lambda *_args, **_kwargs: {"flight_telemetry_project": []})
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "normalize_runtime_path", lambda value: str(value) if value else "")

    stages_file = tmp_path / "lab_stages.toml"
    count = pipeline_editor._write_stages_for_module(
        tmp_path / "flight_telemetry_project",
        stages_file,
        [
            {
                "Q": "Run template",
                "C": "print('run')",
                "R": "runpy",
                "template_id": "generic.execute",
                "template_version": 1,
                "custom_contract": {"schema_version": 1},
            }
        ],
    )

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert count == 1
    assert stored["flight_telemetry_project"][0]["template_id"] == "generic.execute"
    assert stored["flight_telemetry_project"][0]["template_version"] == 1
    assert stored["flight_telemetry_project"][0]["custom_contract"] == {"schema_version": 1}


def test_capture_pipeline_snapshot_falls_back_to_default_sequence_and_active_stage(monkeypatch, tmp_path):
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
    assert snapshot["active_stage"] == 0


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
        "_write_stages_for_module",
        lambda _module_path, _stages_file, module_stages: len(module_stages),
    )

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_telemetry_project",
        tmp_path / "lab_stages.toml",
        "idx",
        "idx_sequence_widget",
        {
            "stages": [{"Q": "q0", "C": "print(0)"}, {"Q": "q1", "C": "print(1)"}],
            "details": {"bad": "skip", "1": "detail1"},
            "venv_map": {"bad": "/tmp/skip", "1": "/tmp/runtime"},
            "engine_map": {"bad": "skip", "1": "agi.run"},
            "sequence": ["bad", 1, 1],
            "active_stage": "bad",
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
            "demo_q_stage_0": "q",
            "demo_code_stage_0": "c",
            "demo_venv_0": "v",
            "demo_keep": "ok",
            "demoa": "drop",
        }
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor._reset_pipeline_editor_state("demo")

    assert fake_st.session_state == {"demo_keep": "ok"}


def test_get_stages_list_and_dict_handle_invalid_files_and_alias_keys(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        "[[flight_telemetry_project]]\nQ = 'first'\n"
        "[[flight]]\nQ = 'alias'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project", "flight"])

    stages = pipeline_editor.get_stages_list(tmp_path / "flight_telemetry_project", stages_file)
    stored = pipeline_editor.get_stages_dict(tmp_path / "flight_telemetry_project", stages_file)

    assert stages[0]["Q"] == "first"
    assert "flight" not in stored

    invalid_file = tmp_path / "broken.toml"
    invalid_file.write_text("[[flight_telemetry_project]\n", encoding="utf-8")
    assert pipeline_editor.get_stages_list(tmp_path / "flight_telemetry_project", invalid_file) == []


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
    fallback = _load_pipeline_editor_with_missing("agilab.pipeline_runtime", "agilab.pipeline_stages")

    assert callable(fallback.get_stages_list)
    assert callable(fallback.save_stage)


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

    def _fake_stages_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_stages_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_stages_spec)
    with pytest.raises(ModuleNotFoundError, match="pipeline_stages"):
        _load_pipeline_editor_with_missing("agilab.pipeline_stages")


def test_save_query_invalid_still_exports_dataframe(monkeypatch, tmp_path):
    calls = {"exported": 0, "saved": 0}
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "export_df", lambda: calls.__setitem__("exported", calls["exported"] + 1))
    monkeypatch.setattr(
        pipeline_editor,
        "save_stage",
        lambda *_args, **_kwargs: calls.__setitem__("saved", calls["saved"] + 1),
    )

    pipeline_editor.save_query(tmp_path / "flight_telemetry_project", [0, "desc", ""], tmp_path / "lab_stages.toml", "idx")

    assert calls == {"exported": 1, "saved": 0}


def test_force_persist_stage_merges_existing_content(tmp_path):
    module_dir = tmp_path / "flight_telemetry_project"
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        "[[flight_telemetry_project]]\nQ = 'first'\nC = 'print(1)'\n",
        encoding="utf-8",
    )

    with patch.object(pipeline_editor, "_module_keys", return_value=["flight_telemetry_project"]):
        pipeline_editor._force_persist_stage(
        module_dir,
        stages_file,
        0,
        {"D": "detail", "E": Path("/tmp/runtime")},
        )

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert stored["flight_telemetry_project"][0]["Q"] == "first"
    assert stored["flight_telemetry_project"][0]["D"] == "detail"
    assert stored["flight_telemetry_project"][0]["E"] == "/tmp/runtime"


def test_force_persist_stage_swallows_invalid_toml(monkeypatch, tmp_path):
    module_dir = tmp_path / "flight_telemetry_project"
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("[[flight_telemetry_project]\n", encoding="utf-8")
    logged: list[str] = []

    monkeypatch.setattr(
        pipeline_editor.logger,
        "error",
        lambda message, *args: logged.append(message % args if args else message),
    )
    with patch.object(pipeline_editor, "_module_keys", return_value=["flight_telemetry_project"]):
        pipeline_editor._force_persist_stage(
            module_dir,
            stages_file,
            0,
            {"D": "detail"},
        )

    assert logged


def test_write_stages_for_module_normalizes_runtime_and_exports_notebook(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    notebook_calls: list[dict[str, object]] = []

    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(
        pipeline_editor,
        "normalize_runtime_path",
        lambda value: f"normalized::{value}" if value else "",
    )
    monkeypatch.setattr(
        pipeline_editor,
        "toml_to_notebook",
        lambda stages, path: notebook_calls.append({"stages": stages, "path": path}),
    )

    count = pipeline_editor._write_stages_for_module(
        tmp_path / "flight_telemetry_project",
        stages_file,
        [
            {"D": "demo", "Q": "q1", "M": "m1", "C": "print(1)", "E": tmp_path / "venv", "R": "agi.run"},
            {"D": "", "Q": "", "M": "", "C": ""},
        ],
    )

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert count == 1
    assert stored["flight_telemetry_project"] == [
        {
            "D": "demo",
            "Q": "q1",
            "M": "m1",
            "C": "print(1)",
            "E": f"normalized::{tmp_path / 'venv'}",
            "R": "agi.run",
        }
    ]
    assert notebook_calls == [{"stages": stored, "path": stages_file}]


def test_save_stage_preserves_existing_runtime_and_extra_fields(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        """
[[flight_telemetry_project]]
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
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)

    nstages, entry = pipeline_editor.save_stage(
        tmp_path / "flight_telemetry_project",
        ["detail", "updated question", "updated-model", "print(2)"],
        current_stage=0,
        nstages=1,
        stages_file=stages_file,
        extra_fields={"LOCKED": None, "SOURCE": "copied"},
    )

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert nstages == 1
    assert entry["E"] == "/tmp/runtime"
    assert entry["R"] == "agi.run"
    assert "LOCKED" not in entry
    assert entry["SOURCE"] == "copied"
    assert stored["flight_telemetry_project"][0]["SOURCE"] == "copied"
    assert stored["flight_telemetry_project"][0]["E"] == "/tmp/runtime"
    assert stored["flight_telemetry_project"][0]["R"] == "agi.run"


def test_save_stage_merges_alias_entries_and_reports_dump_failure(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        """
[[flight]]
Q = "alias only"
C = "print('alias')"
[[flight]]
Q = "alias second"
C = "print('second')"
[[flight_telemetry_project]]
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
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project", "flight"])
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("save boom"))),
    )

    nstages, entry = pipeline_editor.save_stage(
        tmp_path / "flight_telemetry_project",
        ["detail", "question", "model", "print(3)"],
        current_stage=1,
        nstages=2,
        stages_file=stages_file,
    )

    assert nstages == 2
    assert entry["Q"] == "question"
    assert fake_st.session_state["_experiment_last_save_skipped"] is True
    assert errors == ["Failed to save stage contract: save boom"]


def test_save_stage_refuses_future_lab_stages_schema(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        "[__meta__]\nversion = 999\n[[flight_telemetry_project]]\nQ = 'First'\nC = 'print(1)'\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"_experiment_last_save_skipped": False},
        error=lambda message, *args, **kwargs: errors.append(str(message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)

    nstages, entry = pipeline_editor.save_stage(
        tmp_path / "flight_telemetry_project",
        ["detail", "updated question", "model", "print(2)"],
        current_stage=0,
        nstages=1,
        stages_file=stages_file,
    )

    assert nstages == 1
    assert entry["Q"] == "updated question"
    assert fake_st.session_state["_experiment_last_save_skipped"] is True
    assert errors == [
        "Failed to save stage contract: Unsupported lab_stages.toml schema version 999; "
        "upgrade AGILAB before editing this pipeline."
    ]


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
        "save_stage",
        lambda module, query, current_stage, nstages, stages_file, venv_map=None, engine_map=None: (
            calls.setdefault("query", query),
            calls.setdefault("venv_map", venv_map),
            calls.setdefault("engine_map", engine_map),
            (4, {"Q": query[1]}),
        )[-1],
    )
    monkeypatch.setattr(pipeline_editor, "export_df", lambda: calls.setdefault("exported", True))
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: calls.setdefault("bumped", True))

    pipeline_editor.save_query(
        tmp_path / "flight_telemetry_project",
        [0, "detail", "question", "model", "print(1)", 2],
        tmp_path / "lab_stages.toml",
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
        "_write_stages_for_module",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("write boom")),
    )

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_telemetry_project",
        tmp_path / "lab_stages.toml",
        "idx",
        "sequence_widget",
        {"stages": []},
    )

    assert error == "write boom"


def test_restore_pipeline_snapshot_reports_invalid_snapshot_payload(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_telemetry_project",
        tmp_path / "lab_stages.toml",
        "idx",
        "sequence_widget",
        None,
    )

    assert error == "'NoneType' object has no attribute 'get'"


def test_restore_pipeline_snapshot_resets_empty_state(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [4, "stale", "stale", "stale", "stale", "stale", 9]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_write_stages_for_module", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_telemetry_project",
        tmp_path / "lab_stages.toml",
        "idx",
        "sequence_widget",
        {"stages": [], "sequence": []},
    )

    assert error is None
    assert fake_st.session_state["idx"] == [0, "", "", "", "", "", 0]
    assert fake_st.session_state["lab_selected_venv"] == ""
    assert fake_st.session_state["lab_selected_engine"] == "runpy"


def test_on_import_notebook_ignores_non_ipynb(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"upload": SimpleNamespace(type="text/plain")})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_stages.toml", "idx")

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

    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_stages.toml", "idx")

    assert calls["args"][0] is uploaded
    assert fake_st.session_state["idx"][-1] == 3
    assert fake_st.session_state["page_broken"] is True


def test_on_preview_notebook_import_stores_preview_without_writing(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    uploaded = SimpleNamespace(
        name="demo.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["# Import context\n"]},
                    {"cell_type": "code", "source": ["print(1)\n"]},
                ]
            }
        ).encode("utf-8"),
    )
    fake_st = SimpleNamespace(
        session_state=_State({"upload": uploaded, "idx": [0, "", "", "", "", "", 0]}),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        info=lambda message, *args, **kwargs: messages.append(("info", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor.on_preview_notebook_import("upload", tmp_path / "demo_project", "idx")

    preview = fake_st.session_state["idx__notebook_import_preview"]
    assert preview["cell_count"] == 1
    assert preview["module"] == "demo_project"
    assert (tmp_path / "demo_project" / "lab_stages.toml").exists() is False
    assert messages == [
        ("info", "Notebook import preview ready: 1 stage(s), 0 input(s), 0 output(s).")
    ]


def test_confirm_notebook_import_preview_writes_stages_contract_and_marks_page_broken(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    uploaded = SimpleNamespace(
        name="demo.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["# Import context\n"]},
                    {
                        "cell_type": "code",
                        "source": [
                            "import pandas as pd\n",
                            "df = pd.read_csv('data/orders.csv')\n",
                            "df.to_parquet('artifacts/orders.parquet')\n",
                        ],
                    },
                ]
            }
        ).encode("utf-8"),
    )
    fake_st = SimpleNamespace(
        session_state=_State({"idx": [0, "", "", "", "", "", 0]}),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        info=lambda message, *args, **kwargs: messages.append(("info", message)),
        warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
        success=lambda message, *args, **kwargs: messages.append(("success", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: messages.append(("revision", "bump")))

    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    (module_dir / "notebook_import_views.toml").write_text(
        """
schema = "agilab.notebook_import_views.v1"
app = "demo_project"

[[views]]
id = "orders_dataframe"
module = "view_dataframe"
required_artifacts_any = ["artifacts/*.parquet"]
optional_artifacts = ["data/*.csv"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    preview = pipeline_editor.build_notebook_import_preview(uploaded, module_dir)
    fake_st.session_state["idx__notebook_import_preview"] = preview

    count = pipeline_editor.confirm_notebook_import_preview(
        module_dir,
        module_dir / "lab_stages.toml",
        "idx",
    )

    stored = tomllib.loads((module_dir / "lab_stages.toml").read_text(encoding="utf-8"))
    contract = json.loads((module_dir / "notebook_import_contract.json").read_text(encoding="utf-8"))
    pipeline_view = json.loads((module_dir / "notebook_import_pipeline_view.json").read_text(encoding="utf-8"))
    view_plan = json.loads((module_dir / "notebook_import_view_plan.json").read_text(encoding="utf-8"))
    assert count == 1
    assert stored["demo_project"][0]["D"] == "Import context"
    assert contract["artifact_contract"]["inputs"] == ["data/orders.csv"]
    assert contract["artifact_contract"]["outputs"] == ["artifacts/orders.parquet"]
    assert pipeline_view["schema"] == "agilab.notebook_import_pipeline_view.v1"
    assert any(node["kind"] == "analysis_consumer" for node in pipeline_view["nodes"])
    assert any(edge["kind"] == "analysis_consumes" for edge in pipeline_view["edges"])
    assert view_plan["schema"] == "agilab.notebook_import_view_plan.v1"
    assert view_plan["status"] == "matched"
    assert view_plan["matched_views"][0]["module"] == "view_dataframe"
    assert "idx__notebook_import_preview" not in fake_st.session_state
    assert fake_st.session_state["idx"][-1] == 1
    assert fake_st.session_state["page_broken"] is True
    assert ("success", "Imported 1 notebook code cell(s).") in messages
    assert ("revision", "bump") in messages


def test_confirm_notebook_import_preview_uses_app_manifest_without_writing_to_app(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    uploaded = SimpleNamespace(
        name="flight.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["# Flight analysis\n"]},
                    {
                        "cell_type": "code",
                        "source": [
                            "import pandas as pd\n",
                            "df = pd.read_csv('flight/raw/input.csv')\n",
                            "df.to_parquet('flight/dataframe/output.parquet')\n",
                        ],
                    },
                ]
            }
        ).encode("utf-8"),
    )
    fake_st = SimpleNamespace(
        session_state=_State({"idx": [0, "", "", "", "", "", 0]}),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        info=lambda message, *args, **kwargs: messages.append(("info", message)),
        warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
        success=lambda message, *args, **kwargs: messages.append(("success", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: messages.append(("revision", "bump")))

    export_dir = tmp_path / "exported_notebooks" / "flight_telemetry_project"
    app_dir = tmp_path / "apps" / "builtin" / "flight_telemetry_project"
    app_dir.mkdir(parents=True)
    (app_dir / "notebook_import_views.toml").write_text(
        """
schema = "agilab.notebook_import_views.v1"
app = "flight_telemetry_project"

[[views]]
id = "flight_maps"
module = "view_maps"
required_artifacts_any = ["flight/dataframe/*.parquet"]
optional_artifacts = ["flight/raw/*.csv"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    preview = pipeline_editor.build_notebook_import_preview(uploaded, export_dir)
    fake_st.session_state["idx__notebook_import_preview"] = preview

    count = pipeline_editor.confirm_notebook_import_preview(
        export_dir,
        export_dir / "lab_stages.toml",
        "idx",
        view_manifest_dir=app_dir,
    )

    view_plan = json.loads((export_dir / "notebook_import_view_plan.json").read_text(encoding="utf-8"))
    assert count == 1
    assert (export_dir / "lab_stages.toml").is_file()
    assert (export_dir / "notebook_import_contract.json").is_file()
    assert not (app_dir / "notebook_import_contract.json").exists()
    assert view_plan["status"] == "matched"
    assert view_plan["matched_views"][0]["module"] == "view_maps"
    assert set(view_plan["matched_views"][0]["matched_artifacts"]) == {
        "flight/dataframe/output.parquet",
        "flight/raw/input.csv",
    }
    assert ("revision", "bump") in messages


def test_confirm_notebook_import_preview_blocks_unsafe_preflight(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    uploaded = SimpleNamespace(
        name="empty.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(
            {"cells": [{"cell_type": "markdown", "source": ["# Notes only\n"]}]}
        ).encode("utf-8"),
    )
    fake_st = SimpleNamespace(
        session_state=_State({"idx": [0, "", "", "", "", "", 0]}),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        success=lambda message, *args, **kwargs: messages.append(("success", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: messages.append(("revision", "bump")))

    module_dir = tmp_path / "demo_project"
    preview = pipeline_editor.build_notebook_import_preview(uploaded, module_dir)
    fake_st.session_state["idx__notebook_import_preview"] = preview

    count = pipeline_editor.confirm_notebook_import_preview(
        module_dir,
        module_dir / "lab_stages.toml",
        "idx",
    )

    assert count == 0
    assert not (module_dir / "lab_stages.toml").exists()
    assert not (module_dir / "notebook_import_contract.json").exists()
    assert "idx__notebook_import_preview" in fake_st.session_state
    assert "page_broken" not in fake_st.session_state
    assert messages == [
        ("error", "Notebook import is blocked: Notebook import produced no runnable code cells.")
    ]


def test_render_notebook_import_preview_hides_import_button_for_blocked_preflight(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    button_labels: list[str] = []

    def _button(label, *args, **kwargs):
        button_labels.append(label)
        return True

    sidebar = SimpleNamespace(
        caption=lambda message, *args, **kwargs: messages.append(("caption", message)),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        button=_button,
    )
    fake_st = SimpleNamespace(
        session_state=_State(
            {
                "idx__notebook_import_preview": {
                    "cell_count": 0,
                    "preflight": {
                        "safe_to_import": False,
                        "summary": {"pipeline_stage_count": 0, "input_count": 0, "output_count": 0},
                        "risk_counts": {"error": 1},
                        "risks": [
                            {
                                "level": "error",
                                "message": "Notebook import produced no runnable code cells.",
                            }
                        ],
                    },
                }
            }
        ),
        sidebar=sidebar,
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor.render_notebook_import_preview(
        tmp_path / "demo_project",
        tmp_path / "demo_project" / "lab_stages.toml",
        "idx",
    )

    assert button_labels == ["Cancel import"]
    assert "idx__notebook_import_preview" not in fake_st.session_state
    assert ("error", "Notebook import blocked: Notebook import produced no runnable code cells.") in messages


def test_display_history_tab_filters_and_saves_editor_content(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
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

    pipeline_editor.display_history_tab(stages_file, tmp_path / "demo_project")

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
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
    pipeline_editor.toml_to_notebook({"demo_project": [{"C": "print(1)"}]}, tmp_path / "lab_stages.toml")

    uploaded = SimpleNamespace(
        read=lambda: json.dumps({"cells": [{"cell_type": "code", "source": ["print(2)"]}]}).encode("utf-8")
    )
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("toml boom"))),
    )
    count = pipeline_editor.notebook_to_toml(uploaded, "lab_stages.toml", tmp_path / "demo_project")

    assert count is None
    assert errors == [
        "Failed to save notebook: nb boom",
        "Failed to save TOML file: toml boom",
    ]


def test_save_stage_handles_invalid_indices_and_runtime_map_failures(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
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
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["flight_telemetry_project"])
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)

    nstages, entry = pipeline_editor.save_stage(
        tmp_path / "flight_telemetry_project",
        ["detail", "question", "model", 42],
        current_stage="bad",
        nstages="bad",
        stages_file=stages_file,
        venv_map=_BrokenMap(),
        engine_map=_BrokenMap(),
    )

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert nstages == 1
    assert entry["E"] == ""
    assert entry["R"] == ""
    assert entry["C"] == "42"
    assert stored["flight_telemetry_project"][0]["C"] == "42"
    assert errors == []


def test_force_persist_stage_swallows_dump_failures(monkeypatch, tmp_path):
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
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

    pipeline_editor._force_persist_stage(tmp_path / "flight_telemetry_project", stages_file, 2, {"Q": "late"})

    expected_path = pipeline_editor.bound_log_value(stages_file, pipeline_editor.LOG_PATH_LIMIT)
    assert failures == [f"Force persist failed for stage 2 -> {expected_path}: dump boom"]


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

    assert pipeline_editor.notebook_to_toml(None, "lab_stages.toml", tmp_path / "demo_project") is None
    assert (
        pipeline_editor.notebook_to_toml(
            SimpleNamespace(name="demo.txt", type="text/plain", read=lambda: b"{}"),
            "lab_stages.toml",
            tmp_path / "demo_project",
        )
        is None
    )
    assert (
        pipeline_editor.notebook_to_toml(
            SimpleNamespace(name="demo.ipynb", type="application/x-ipynb+json", read=lambda: b"{"),
            "lab_stages.toml",
            tmp_path / "demo_project",
        )
        is None
    )
    assert (
        pipeline_editor.notebook_to_toml(
            SimpleNamespace(name="demo.ipynb", type="application/x-ipynb+json", read=lambda: b"[]"),
            "lab_stages.toml",
            tmp_path / "demo_project",
        )
        is None
    )
    assert (
        pipeline_editor.notebook_to_toml(
            SimpleNamespace(
                name="demo.ipynb",
                type="application/x-ipynb+json",
                read=lambda: b'{"cells": {}}',
            ),
            "lab_stages.toml",
            tmp_path / "demo_project",
        )
        is None
    )

    broken_stages = tmp_path / "broken.toml"
    broken_stages.write_text("[[demo_project]\n", encoding="utf-8")
    assert pipeline_editor.refresh_notebook_export(tmp_path / "missing.toml") is None
    assert pipeline_editor.refresh_notebook_export(broken_stages) is None

    assert messages == [
        ("error", "No uploaded notebook provided."),
        ("error", "Please upload a .ipynb file."),
        ("error", "Unable to parse notebook: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"),
        ("error", "Invalid notebook format: expected a JSON object."),
        ("error", "Invalid notebook format: notebook format is invalid: cells must be a list"),
        ("error", f"Unable to export notebook: failed to load {broken_stages}: Expected ']]' at the end of an array declaration (at line 1, column 15)"),
    ]


def test_on_import_notebook_does_not_mark_page_broken_when_import_fails(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    fake_st = SimpleNamespace(
        session_state=_State({"idx": [0, "", "", "", "", "", 0]}),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
        success=lambda message, *args, **kwargs: messages.append(("success", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_stages.toml", "idx")

    fake_st.session_state["upload"] = SimpleNamespace(type="application/x-ipynb+json")
    monkeypatch.setattr(pipeline_editor, "notebook_to_toml", lambda *_args, **_kwargs: None)
    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_stages.toml", "idx")

    assert messages == [
        ("error", "No notebook file was uploaded."),
    ]
    assert "page_broken" not in fake_st.session_state
    assert fake_st.session_state["idx"][-1] == 0


def test_on_import_notebook_warns_when_successful_import_has_no_code_cells(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    fake_st = SimpleNamespace(
        session_state=_State(
            {
                "upload": SimpleNamespace(
                    name="demo.ipynb",
                    type="application/x-ipynb+json",
                ),
                "idx": [0, "", "", "", "", "", 9],
            }
        ),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
        success=lambda message, *args, **kwargs: messages.append(("success", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "notebook_to_toml", lambda *_args, **_kwargs: 0)

    pipeline_editor.on_import_notebook("upload", tmp_path, tmp_path / "lab_stages.toml", "idx")

    assert messages == [("warning", "Notebook imported, but no code cells were found.")]
    assert fake_st.session_state["page_broken"] is True
    assert fake_st.session_state["idx"][-1] == 0


def test_on_import_notebook_does_not_report_success_after_write_failure(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    fake_st = SimpleNamespace(
        session_state=_State(
            {
                "upload": SimpleNamespace(
                    name="demo.ipynb",
                    type="application/x-ipynb+json",
                    read=lambda: json.dumps(
                        {"cells": [{"cell_type": "code", "source": ["print(1)\n"]}]}
                    ).encode("utf-8"),
                ),
                "idx": [0, "", "", "", "", "", 0],
            }
        ),
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
        success=lambda message, *args, **kwargs: messages.append(("success", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(
        pipeline_editor,
        "tomli_w",
        SimpleNamespace(dump=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("toml boom"))),
    )

    pipeline_editor.on_import_notebook(
        "upload",
        tmp_path / "demo_project",
        tmp_path / "demo_project" / "lab_stages.toml",
        "idx",
    )

    assert messages == [("error", "Failed to save TOML file: toml boom")]
    assert "page_broken" not in fake_st.session_state
    assert fake_st.session_state["idx"][-1] == 0
    assert not (tmp_path / "demo_project" / "lab_stages.toml").exists()


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
    assert errors == ["Failed to save stage contract from editor: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"]


def test_pipeline_editor_additional_branch_coverage(monkeypatch, tmp_path):
    empty_stages = tmp_path / "empty.toml"
    empty_stages.write_text("demo = { value = 1 }\n", encoding="utf-8")
    assert pipeline_editor.get_stages_list(tmp_path / "demo_project", empty_stages) == []

    monkeypatch.setattr(pipeline_editor, "_prune_invalid_entries", lambda stages, keep_index=None: stages)
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)
    count = pipeline_editor._write_stages_for_module(
        tmp_path / "demo_project",
        tmp_path / "lab_stages.toml",
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
    assert snapshot["stages"] == [{"D": "", "Q": "keep", "M": "", "C": "", "E": "", "R": ""}]
    assert snapshot["active_stage"] == 0

    monkeypatch.setattr(pipeline_editor, "_write_stages_for_module", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_reset_pipeline_editor_state", lambda _index_page: None)
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda _path: False)
    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "demo_project",
        tmp_path / "lab_stages.toml",
        "idx",
        "idx_sequence_widget",
        {"stages": "not-a-list", "sequence": []},
    )
    assert error is None
    assert fake_st.session_state["idx__run_sequence"] == [0]

    fake_st = SimpleNamespace(
        session_state={"env": SimpleNamespace(envars={}), "_experiment_last_save_skipped": False},
        error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_module_keys", lambda _module: ["demo_project"])
    monkeypatch.setattr(pipeline_editor, "_looks_like_stage", lambda value: str(value) == "1")
    monkeypatch.setattr(pipeline_editor, "_prune_invalid_entries", lambda stages, keep_index=None: stages)
    monkeypatch.setattr(pipeline_editor, "toml_to_notebook", lambda *_args, **_kwargs: None)
    nstages, entry = pipeline_editor.save_stage(
        tmp_path / "demo_project",
        ["1", "desc", "question", "model", "print(1)"],
        current_stage=0,
        nstages=0,
        stages_file=tmp_path / "save_stages.toml",
        venv_map={},
        engine_map={},
    )
    assert nstages == 1
    assert entry["D"] == "desc"
    assert entry["Q"] == "question"
    assert entry["M"] == "model"
    assert entry["C"] == "print(1)"



def test_toml_to_notebook_handles_meta_string_stages_and_blank_entries(tmp_path):
    toml_path = tmp_path / "lab_stages.toml"

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
    assert notebook["metadata"]["agilab"]["schema"] == "agilab.notebook_export.v1"
    assert notebook["metadata"]["agilab"]["version"] == 1
    assert notebook["metadata"]["agilab"]["export_mode"] == "plain"


def test_stage_source_cell_preserves_escape_sensitive_code() -> None:
    code_text = (
        'path = r"C:\\tmp"\n'
        'pattern = "\\\\d+"\n'
        'continued = "abc" '
        + "\\"
        + "\n"
        '    "def"\n'
        'print("""triple quoted text""")\n'
    )

    source = notebook_export_support._stage_source_cell({"index": 7, "code": code_text})

    namespace: dict[str, object] = {}
    exec(source, namespace)
    assert namespace["STAGE_007_CODE"] == code_text


def test_pycharm_notebook_mirror_path_targets_source_checkout_for_external_exports(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True, exist_ok=True)
    (repo_root / ".idea").mkdir(parents=True, exist_ok=True)
    export_dir = tmp_path / "export" / "uav_graph_routing"
    export_dir.mkdir(parents=True, exist_ok=True)
    stages_file = export_dir / "lab_stages.toml"

    context = notebook_export_support.NotebookExportContext(
        project_name="uav_queue_project",
        module_path="uav_queue_project",
        artifact_dir=str(export_dir),
        repo_root=str(repo_root),
    )

    mirror_path = notebook_export_support.pycharm_notebook_mirror_path(
        stages_file,
        export_context=context,
    )

    assert mirror_path == str(repo_root / "exported_notebooks" / "uav_graph_routing" / "lab_stages.ipynb")


def test_pycharm_notebook_mirror_path_prefers_project_notebooks_for_active_app(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True, exist_ok=True)
    (repo_root / ".idea").mkdir(parents=True, exist_ok=True)
    app_root = repo_root / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='flight_telemetry_project'\n", encoding="utf-8")

    paths = []
    for project_name, artifact_name in (("flight_telemetry_project", "flight"), ("flight", "flight_telemetry_project")):
        export_dir = tmp_path / "export" / artifact_name
        export_dir.mkdir(parents=True, exist_ok=True)
        context = notebook_export_support.NotebookExportContext(
            project_name=project_name,
            module_path=artifact_name,
            artifact_dir=str(export_dir),
            active_app=str(app_root),
            repo_root=str(repo_root),
        )
        paths.append(
            notebook_export_support.pycharm_notebook_mirror_path(
                export_dir / "lab_stages.toml",
                export_context=context,
            )
        )

    assert paths == [str(app_root / "notebooks" / "lab_stages.ipynb")] * 2


def test_build_notebook_export_context_reads_related_pages_from_app_settings(tmp_path):
    pages_root = tmp_path / "apps-pages"
    page_script = pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True, exist_ok=True)
    page_script.write_text("print('page')\n", encoding="utf-8")
    (page_script.parent / "notebook_inline.py").write_text(
        "def render_inline(*, page, record, export_payload):\n    return f'inline:{page}'\n",
        encoding="utf-8",
    )

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
        tmp_path / "export" / "demo_project" / "lab_stages.toml",
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
    assert context.related_pages[0].inline_renderer.endswith("notebook_inline.py:render_inline")


@pytest.mark.parametrize(
    ("app_name", "expected_modules", "expected_label"),
    [
        (
            "uav_queue_project",
            ("view_queue_resilience", "view_maps_network"),
            "UAV Queue Analysis",
        ),
        (
            "uav_relay_queue_project",
            ("view_relay_resilience", "view_maps_network"),
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
        tmp_path / "export" / app_name / "lab_stages.toml",
        project_name=app_name,
    )

    assert tuple(page.module for page in context.related_pages) == expected_modules
    assert context.related_pages[0].label == expected_label
    assert context.related_pages[0].description
    assert context.related_pages[0].artifacts
    assert context.related_pages[0].launch_note
    assert context.related_pages[0].script_path.endswith(f"{expected_modules[0]}.py")
    assert not context.related_pages[0].inline_renderer
    assert context.related_pages[1].label == "Maps Network"
    assert "pipeline/topology.gml" in context.related_pages[1].artifacts
    assert context.related_pages[1].script_path.endswith("view_maps_network.py")
    assert context.related_pages[1].inline_renderer.endswith("notebook_inline.py:render_inline")


def test_build_notebook_export_context_prefers_valid_apps_repository_root_when_active_app_is_stale(tmp_path):
    pages_root = tmp_path / "apps-pages"
    page_script = pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True, exist_ok=True)
    page_script.write_text("print('page')\n", encoding="utf-8")

    stale_app = tmp_path / "src" / "agilab" / "apps" / "demo_project"
    (stale_app / "src").mkdir(parents=True, exist_ok=True)

    repo_apps = tmp_path / "repo-apps"
    source_app = repo_apps / "demo_project"
    (source_app / "src").mkdir(parents=True, exist_ok=True)
    (source_app / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    (source_app / "src" / "app_settings.toml").write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    workspace_settings = tmp_path / ".agilab" / "apps" / "demo_project" / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    env = SimpleNamespace(
        AGILAB_PAGES_ABS=pages_root,
        active_app=stale_app,
        app_settings_file=workspace_settings,
        apps_repository_root=repo_apps,
        resolve_user_app_settings_file=lambda app_name, ensure_exists=False: workspace_settings,
        find_source_app_settings_file=lambda app_name: None,
        read_agilab_path=lambda: tmp_path / "repo",
    )

    context = pipeline_editor.build_notebook_export_context(
        env,
        Path("demo_project"),
        tmp_path / "export" / "demo_project" / "lab_stages.toml",
        project_name="demo_project",
    )

    assert context.active_app == str(source_app)
    assert tuple(page.module for page in context.related_pages) == ("view_demo",)


def test_build_notebook_export_context_ignores_valid_active_app_for_other_project(tmp_path):
    pages_root = tmp_path / "apps-pages"
    page_script = pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True, exist_ok=True)
    page_script.write_text("print('page')\n", encoding="utf-8")

    wrong_app = tmp_path / "apps" / "flight_telemetry_project"
    (wrong_app / "src").mkdir(parents=True, exist_ok=True)
    (wrong_app / "pyproject.toml").write_text("[project]\nname='flight_telemetry_project'\n", encoding="utf-8")

    repo_apps = tmp_path / "repo-apps"
    source_app = repo_apps / "uav_graph_routing_project"
    (source_app / "src").mkdir(parents=True, exist_ok=True)
    (source_app / "pyproject.toml").write_text(
        "[project]\nname='uav_graph_routing_project'\n",
        encoding="utf-8",
    )
    (source_app / "src" / "app_settings.toml").write_text(
        "[pages]\nview_module=['view_demo']\n",
        encoding="utf-8",
    )

    workspace_settings = (
        tmp_path
        / ".agilab"
        / "apps"
        / "uav_graph_routing_project"
        / "app_settings.toml"
    )
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    env = SimpleNamespace(
        AGILAB_PAGES_ABS=pages_root,
        active_app=wrong_app,
        app_settings_file=workspace_settings,
        apps_repository_root=repo_apps,
        resolve_user_app_settings_file=lambda app_name, ensure_exists=False: workspace_settings,
        find_source_app_settings_file=lambda app_name: None,
        read_agilab_path=lambda: tmp_path / "repo",
    )

    context = pipeline_editor.build_notebook_export_context(
        env,
        Path("uav_graph_routing"),
        tmp_path / "export" / "uav_graph_routing" / "lab_stages.toml",
        project_name="uav_graph_routing_project",
    )

    assert context.active_app == str(source_app)
    assert tuple(page.module for page in context.related_pages) == ("view_demo",)


def test_build_notebook_export_context_normalizes_repo_root_hint_without_sibling_workspace_scan(
    tmp_path,
):
    workspace_root = tmp_path / "workspace"
    public_repo = workspace_root / "agilab"
    (public_repo / "src" / "agilab").mkdir(parents=True, exist_ok=True)
    (public_repo / ".idea").mkdir(parents=True, exist_ok=True)

    pages_root = public_repo / "src" / "agilab" / "apps-pages"
    page_script = pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True, exist_ok=True)
    page_script.write_text("print('page')\n", encoding="utf-8")

    private_repo = workspace_root / "thales_agilab"
    source_app = private_repo / "apps" / "demo_project"
    (source_app / "src").mkdir(parents=True, exist_ok=True)
    (source_app / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    (source_app / "src" / "app_settings.toml").write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    workspace_settings = tmp_path / ".agilab" / "apps" / "demo_project" / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    env = SimpleNamespace(
        AGILAB_PAGES_ABS=pages_root,
        active_app="",
        app_settings_file=workspace_settings,
        apps_repository_root="",
        resolve_user_app_settings_file=lambda app_name, ensure_exists=False: workspace_settings,
        find_source_app_settings_file=lambda app_name: None,
        read_agilab_path=lambda: public_repo / "src" / "agilab",
    )

    context = pipeline_editor.build_notebook_export_context(
        env,
        Path("demo_project"),
        tmp_path / "export" / "demo_project" / "lab_stages.toml",
        project_name="demo_project",
    )

    assert context.repo_root == str(public_repo)
    assert context.active_app == ""
    assert tuple(page.module for page in context.related_pages) == ("view_demo",)


def test_build_notebook_export_context_can_scan_sibling_workspace_when_enabled(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGILAB_NOTEBOOK_EXPORT_ALLOW_WORKSPACE_SIBLINGS", "1")
    workspace_root = tmp_path / "workspace"
    public_repo = workspace_root / "agilab"
    (public_repo / "src" / "agilab").mkdir(parents=True, exist_ok=True)
    (public_repo / ".idea").mkdir(parents=True, exist_ok=True)

    pages_root = public_repo / "src" / "agilab" / "apps-pages"
    page_script = pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True, exist_ok=True)
    page_script.write_text("print('page')\n", encoding="utf-8")

    private_repo = workspace_root / "thales_agilab"
    source_app = private_repo / "apps" / "demo_project"
    (source_app / "src").mkdir(parents=True, exist_ok=True)
    (source_app / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    (source_app / "src" / "app_settings.toml").write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    workspace_settings = tmp_path / ".agilab" / "apps" / "demo_project" / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    env = SimpleNamespace(
        AGILAB_PAGES_ABS=pages_root,
        active_app="",
        app_settings_file=workspace_settings,
        apps_repository_root="",
        resolve_user_app_settings_file=lambda app_name, ensure_exists=False: workspace_settings,
        find_source_app_settings_file=lambda app_name: None,
        read_agilab_path=lambda: public_repo / "src" / "agilab",
    )

    context = pipeline_editor.build_notebook_export_context(
        env,
        Path("demo_project"),
        tmp_path / "export" / "demo_project" / "lab_stages.toml",
        project_name="demo_project",
    )

    assert context.repo_root == str(public_repo)
    assert context.active_app == str(source_app)
    assert context.allow_workspace_sibling_apps is True
    assert tuple(page.module for page in context.related_pages) == ("view_demo",)


def test_build_notebook_export_context_accepts_project_suffix_alias(tmp_path):
    pages_root = tmp_path / "apps-pages"
    page_script = pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True, exist_ok=True)
    page_script.write_text("print('page')\n", encoding="utf-8")

    source_app = tmp_path / "apps" / "uav_graph_routing_project"
    (source_app / "src").mkdir(parents=True, exist_ok=True)
    (source_app / "pyproject.toml").write_text(
        "[project]\nname='uav_graph_routing_project'\n",
        encoding="utf-8",
    )
    (source_app / "src" / "app_settings.toml").write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    workspace_settings = tmp_path / ".agilab" / "apps" / "uav_graph_routing" / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[pages]\nview_module=['view_demo']\n", encoding="utf-8")

    env = SimpleNamespace(
        AGILAB_PAGES_ABS=pages_root,
        active_app=source_app,
        app_settings_file=workspace_settings,
        apps_path=tmp_path / "apps",
        builtin_apps_path=tmp_path / "apps" / "builtin",
        apps_repository_root="",
        resolve_user_app_settings_file=lambda app_name, ensure_exists=False: workspace_settings,
        find_source_app_settings_file=lambda app_name: source_app / "src" / "app_settings.toml",
        read_agilab_path=lambda: tmp_path / "repo",
    )

    context = pipeline_editor.build_notebook_export_context(
        env,
        Path("uav_graph_routing"),
        tmp_path / "export" / "uav_graph_routing" / "lab_stages.toml",
        project_name="uav_graph_routing",
    )

    assert context.project_name == "uav_graph_routing"
    assert context.active_app == str(source_app)
    assert tuple(page.module for page in context.related_pages) == ("view_demo",)


def test_toml_to_notebook_with_export_context_embeds_supervisor_metadata_and_analysis_helpers(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True, exist_ok=True)
    (repo_root / ".idea").mkdir(parents=True, exist_ok=True)
    export_dir = tmp_path / "export" / "demo_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    app_root = tmp_path / "apps" / "demo_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    stage_code = (
        "print('stage-0')\n"
        'path = r"C:\\tmp"\n'
        'pattern = "\\\\d+"\n'
        'continued = "abc" '
        + "\\"
        + "\n"
        '    "def"\n'
        'print("""triple quoted text""")\n'
    )
    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(export_dir),
        active_app=str(app_root),
        app_settings_file=str(tmp_path / ".agilab" / "apps" / "demo_project" / "app_settings.toml"),
        pages_root=str(tmp_path / "apps-pages"),
        repo_root=str(repo_root),
        related_pages=(
            notebook_export_support.RelatedPageExport(
                module="view_demo",
                label="Demo Analysis",
                description="Inspect demo artifacts.",
                artifacts=("demo.json", "demo.csv"),
                launch_note="Open this after the run.",
                script_path=str(tmp_path / "apps-pages" / "view_demo" / "src" / "view_demo" / "view_demo.py"),
                inline_renderer=str(tmp_path / "apps-pages" / "view_demo" / "src" / "view_demo" / "notebook_inline.py:render_inline"),
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
                    "C": stage_code,
                    "E": str(tmp_path / "venv-demo"),
                    "R": "agi.run",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    pycharm_mirror = app_root / "notebooks" / "lab_stages.ipynb"
    pycharm_sitecustomize = pycharm_mirror.parent / "sitecustomize.py"
    mirror_notebook = json.loads(pycharm_mirror.read_text(encoding="utf-8"))
    metadata = notebook["metadata"]["agilab"]
    helper_source = "".join(notebook["cells"][1]["source"])
    stage_source_cell = "".join(notebook["cells"][3]["source"])
    stage_runner_cell = "".join(notebook["cells"][4]["source"])
    page_markdown = "".join(notebook["cells"][-2]["source"])
    analysis_source = "".join(notebook["cells"][-1]["source"])

    assert metadata["schema"] == "agilab.notebook_export.v1"
    assert metadata["version"] == 1
    assert metadata["export_mode"] == "supervisor"
    assert metadata["project_name"] == "demo_project"
    assert metadata["controller_python"] == sys.executable
    assert metadata["pycharm_mirror_path"] == str(pycharm_mirror)
    assert metadata["stages"][0]["runtime"] == "agi.run"
    assert metadata["stages"][0]["env"] == str(tmp_path / "venv-demo")
    assert metadata["related_pages"][0]["module"] == "view_demo"
    assert metadata["related_pages"][0]["label"] == "Demo Analysis"
    assert metadata["related_pages"][0]["artifacts"] == ["demo.json", "demo.csv"]
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"
    assert notebook["metadata"]["language_info"]["name"] == "python"
    assert "run_agilab_stage" in helper_source
    assert "run_agilab_pipeline" in helper_source
    assert "analysis_launch_command" in helper_source
    assert "analysis_launch_argv" in helper_source
    assert "render_analysis_page" in helper_source
    assert "shell=True" not in helper_source
    assert "_build_shorthand_agi_script" in helper_source
    assert "_find_free_streamlit_port" in helper_source
    assert "controller_python = AGILAB_NOTEBOOK_EXPORT.get(\"controller_python\")" in helper_source
    stage_namespace: dict[str, object] = {}
    exec(stage_source_cell, stage_namespace)
    assert stage_namespace["STAGE_000_CODE"] == stage_code
    assert "\nprint(STAGE_000_CODE)\n" in stage_source_cell
    assert "run_agilab_stage(0, code_override=STAGE_000_CODE)" in stage_runner_cell
    assert "Demo Analysis" in page_markdown
    assert "`demo.json`" in page_markdown
    assert "Open this after the run." in page_markdown
    assert "Inline renderer:" in page_markdown
    assert "view_demo" in analysis_source
    assert "render_analysis_page(page)" in analysis_source
    assert "launch_analysis_page(page)" not in analysis_source
    assert "print(analysis_launch_command(page))" not in analysis_source
    assert mirror_notebook == notebook
    assert pycharm_sitecustomize.exists()
    assert "ValuesPolicy" in pycharm_sitecustomize.read_text(encoding="utf-8")


def test_notebook_helper_re_resolves_stale_analysis_page_paths_with_agi_env_and_agi_pages(
    tmp_path,
    monkeypatch,
):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True, exist_ok=True)
    (repo_root / ".idea").mkdir(parents=True, exist_ok=True)
    export_dir = tmp_path / "export" / "demo_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    app_root = tmp_path / "apps" / "demo_project"
    app_root.mkdir(parents=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")

    installed_pages_root = tmp_path / "site-packages" / "agi_pages"
    page_script = installed_pages_root / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_script.parent.mkdir(parents=True)
    page_script.write_text("print('page')\n", encoding="utf-8")
    page_script.with_name("notebook_inline.py").write_text(
        "def render_inline(*, page, record, export_payload):\n    return 'inline:' + page\n",
        encoding="utf-8",
    )

    stale_pages_root = tmp_path / "missing-pages"
    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(export_dir),
        active_app=str(app_root),
        pages_root=str(stale_pages_root),
        repo_root=str(repo_root),
        related_pages=(
            notebook_export_support.RelatedPageExport(
                module="view_demo",
                label="Demo Analysis",
                script_path=str(stale_pages_root / "view_demo.py"),
                inline_renderer=str(stale_pages_root / "notebook_inline.py:render_inline"),
            ),
        ),
    )

    pipeline_editor.toml_to_notebook({"demo_project": ["print('stage')\n"]}, toml_path, export_context=context)
    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    helper_source = "".join(notebook["cells"][1]["source"])
    assert "_resolve_pages_root" in helper_source
    assert "_resolve_agi_pages_bundle" in helper_source

    fake_agi_env = types.ModuleType("agi_env")

    class _FakeAgiEnv:
        def __init__(self, *args, **kwargs):
            self.AGILAB_PAGES_ABS = installed_pages_root

    fake_agi_env.AgiEnv = _FakeAgiEnv
    monkeypatch.setitem(sys.modules, "agi_env", fake_agi_env)

    provider_path = Path(__file__).resolve().parents[1] / "src/agilab/lib/agi-pages/src/agi_pages/__init__.py"
    spec = importlib.util.spec_from_file_location("agi_pages", provider_path)
    assert spec and spec.loader
    agi_pages = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "agi_pages", agi_pages)
    spec.loader.exec_module(agi_pages)

    namespace: dict[str, object] = {}
    exec(helper_source, namespace)

    argv = namespace["analysis_launch_argv"]("view_demo", port=9876)
    assert isinstance(argv, list)
    assert str(page_script.resolve()) in argv
    assert argv[-2:] == ["--active-app", str(app_root)]
    assert namespace["render_analysis_page"]("view_demo", fallback_launch=False) == "inline:view_demo"
    assert namespace["AGILAB_NOTEBOOK_EXPORT"]["pages_root"] == str(installed_pages_root)


def test_notebook_helper_replays_app_shorthand_stages_as_agi_run_scripts(tmp_path):
    export_dir = tmp_path / "export" / "demo_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    app_root = tmp_path / "apps" / "demo_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(export_dir),
        active_app=str(app_root),
        app_settings_file="",
        pages_root="",
        repo_root=str(tmp_path / "repo"),
        related_pages=(),
    )

    pipeline_editor.toml_to_notebook(
        {
            "demo_project": [
                {
                    "D": "Run demo app",
                    "Q": "Generate demo artifacts.",
                    "M": "",
                    "C": "APP = 'demo_project'\ntrainer = 'ppo'\ndata_in = 'demo/in'\ndata_out = 'demo/out'\n",
                    "R": "runpy",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, object] = {}
    exec(helper_source, namespace)

    captured: dict[str, str] = {}

    class _Result:
        stdout = ""
        stderr = ""

        @staticmethod
        def check_returncode() -> None:
            return None

    def _fake_run(cmd, **kwargs):
        captured["script"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _Result()

    original_run = namespace["subprocess"].run
    try:
        namespace["subprocess"].run = _fake_run
        namespace["run_agilab_stage"](0, capture_output=False)
    finally:
        namespace["subprocess"].run = original_run

    assert "from agi_cluster.agi_distributor import AGI" in captured["script"]
    assert "ACTIVE_APP = " + repr(str(app_root)) in captured["script"]
    assert "RUN_MODE = json.loads('0')" in captured["script"]
    assert "await AGI.run(app_env, request=request)" in captured["script"]
    assert "AgiEnv(active_app=ACTIVE_APP, verbose=1)" in captured["script"]
    assert (
        "RUN_ARGS = json.loads('{\"data_in\": \"demo/in\", \"data_out\": \"demo/out\", "
        "\"trainer\": \"ppo\"}')"
    ) in captured["script"]


def test_notebook_helper_replays_app_shorthand_stages_from_apps_repository_when_active_app_is_stale(
    tmp_path,
    monkeypatch,
):
    export_dir = tmp_path / "export" / "demo_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    stale_app = tmp_path / "src" / "agilab" / "apps" / "demo_project"
    (stale_app / "src").mkdir(parents=True, exist_ok=True)
    repo_apps = tmp_path / "repo-apps"
    app_root = repo_apps / "demo_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(export_dir),
        active_app=str(stale_app),
        app_settings_file="",
        pages_root="",
        repo_root=str(tmp_path / "repo"),
        related_pages=(),
    )

    pipeline_editor.toml_to_notebook(
        {
            "demo_project": [
                {
                    "D": "Run demo app",
                    "Q": "Generate demo artifacts.",
                    "M": "",
                    "C": "APP = 'demo_project'\ntrainer = 'ppo'\n",
                    "R": "runpy",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, object] = {}
    exec(helper_source, namespace)
    namespace["AGILAB_NOTEBOOK_EXPORT"]["repo_root"] = ""
    namespace["AGILAB_NOTEBOOK_EXPORT"]["pycharm_mirror_path"] = ""
    namespace["AGILAB_NOTEBOOK_EXPORT"]["pages_root"] = ""

    captured: dict[str, str] = {}

    class _Result:
        stdout = ""
        stderr = ""

        @staticmethod
        def check_returncode() -> None:
            return None

    def _fake_run(cmd, **kwargs):
        captured["script"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _Result()

    original_run = namespace["subprocess"].run
    monkeypatch.setenv("APPS_REPOSITORY", str(repo_apps))
    try:
        namespace["subprocess"].run = _fake_run
        namespace["run_agilab_stage"](0, capture_output=False)
    finally:
        namespace["subprocess"].run = original_run

    assert "ACTIVE_APP = " + repr(str(app_root)) in captured["script"]


def test_notebook_helper_replays_app_shorthand_stages_when_active_app_is_other_project(
    tmp_path,
    monkeypatch,
):
    export_dir = tmp_path / "export" / "uav_graph_routing"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"

    wrong_app = tmp_path / "apps" / "flight_telemetry_project"
    (wrong_app / "src").mkdir(parents=True, exist_ok=True)
    (wrong_app / "pyproject.toml").write_text(
        "[project]\nname='flight_telemetry_project'\n",
        encoding="utf-8",
    )

    repo_apps = tmp_path / "repo-apps"
    app_root = repo_apps / "uav_graph_routing_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text(
        "[project]\nname='uav_graph_routing_project'\n",
        encoding="utf-8",
    )
    context = notebook_export_support.NotebookExportContext(
        project_name="uav_graph_routing_project",
        module_path="uav_graph_routing",
        artifact_dir=str(export_dir),
        active_app=str(wrong_app),
        app_settings_file="",
        pages_root="",
        repo_root=str(tmp_path / "repo"),
        related_pages=(),
    )

    pipeline_editor.toml_to_notebook(
        {
            "uav_graph_routing": [
                {
                    "D": "Train routing policy",
                    "Q": "Run routing training.",
                    "M": "",
                    "C": (
                        "APP = 'uav_graph_routing_project'\n"
                        "trainer = 'uav_graph_routing_ppo'\n"
                    ),
                    "R": "runpy",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, object] = {}
    exec(helper_source, namespace)
    namespace["AGILAB_NOTEBOOK_EXPORT"]["repo_root"] = ""
    namespace["AGILAB_NOTEBOOK_EXPORT"]["pycharm_mirror_path"] = ""
    namespace["AGILAB_NOTEBOOK_EXPORT"]["pages_root"] = ""

    captured: dict[str, str] = {}

    class _Result:
        stdout = ""
        stderr = ""

        @staticmethod
        def check_returncode() -> None:
            return None

    def _fake_run(cmd, **kwargs):
        captured["script"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _Result()

    original_run = namespace["subprocess"].run
    monkeypatch.setenv("APPS_REPOSITORY", str(repo_apps))
    try:
        namespace["subprocess"].run = _fake_run
        namespace["run_agilab_stage"](0, capture_output=False)
    finally:
        namespace["subprocess"].run = original_run

    assert "ACTIVE_APP = " + repr(str(app_root)) in captured["script"]
    assert "flight_telemetry_project" not in captured["script"]


@pytest.mark.parametrize(
    ("allow_siblings", "expect_private_resolution"),
    [(False, False), (True, True)],
)
def test_notebook_helper_replays_app_shorthand_stages_from_sibling_workspace_when_active_app_is_missing(
    tmp_path,
    monkeypatch,
    allow_siblings,
    expect_private_resolution,
):
    if allow_siblings:
        monkeypatch.setenv("AGILAB_NOTEBOOK_EXPORT_ALLOW_WORKSPACE_SIBLINGS", "1")
    workspace_root = tmp_path / "workspace"
    public_repo = workspace_root / "agilab"
    (public_repo / "src" / "agilab").mkdir(parents=True, exist_ok=True)
    (public_repo / ".idea").mkdir(parents=True, exist_ok=True)
    private_repo = workspace_root / "thales_agilab"
    app_root = private_repo / "apps" / "demo_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")

    export_dir = tmp_path / "export" / "demo_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(export_dir),
        active_app="",
        app_settings_file="",
        pages_root=str(public_repo / "src" / "agilab" / "apps-pages"),
        repo_root=str(public_repo),
        related_pages=(),
    )

    pipeline_editor.toml_to_notebook(
        {
            "demo_project": [
                {
                    "D": "Run demo app",
                    "Q": "Generate demo artifacts.",
                    "M": "",
                    "C": "APP = 'demo_project'\ntrainer = 'ppo'\n",
                    "R": "runpy",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, object] = {}
    exec(helper_source, namespace)
    namespace["AGILAB_NOTEBOOK_EXPORT"]["active_app"] = ""
    namespace["AGILAB_NOTEBOOK_EXPORT"]["repo_root"] = str(public_repo / "src" / "agilab")
    namespace["AGILAB_NOTEBOOK_EXPORT"]["pycharm_mirror_path"] = str(
        public_repo / "exported_notebooks" / "demo_project" / "lab_stages.ipynb"
    )

    captured: dict[str, str] = {}

    class _Result:
        stdout = ""
        stderr = ""

        @staticmethod
        def check_returncode() -> None:
            return None

    def _fake_run(cmd, **kwargs):
        captured["script"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _Result()

    original_run = namespace["subprocess"].run
    try:
        namespace["subprocess"].run = _fake_run
        if not expect_private_resolution:
            with pytest.raises(ValueError, match="Unable to resolve a valid AGILAB app root"):
                namespace["run_agilab_stage"](0, capture_output=False)
            assert captured == {}
            return
        namespace["run_agilab_stage"](0, capture_output=False)
    finally:
        namespace["subprocess"].run = original_run

    assert "ACTIVE_APP = " + repr(str(app_root)) in captured["script"]


def test_notebook_helper_replays_trainer_stack_shorthand_from_app_settings(tmp_path):
    export_dir = tmp_path / "export" / "demo_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    app_root = tmp_path / "apps" / "demo_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    (app_root / "src" / "app_settings.toml").write_text(
        """
[args]
data_in = "seed/in"
data_out = "seed/out"
reset_target = false

[[args.stages]]
name = "ppo"

[args.stages.args]
seed = 0
total_timesteps = 5000

[[args.stages]]
name = "ilp"

[args.stages.args]
beam_width = 3
""".strip()
        + "\n",
        encoding="utf-8",
    )

    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(export_dir),
        active_app=str(app_root),
        app_settings_file=str(app_root / "src" / "app_settings.toml"),
        pages_root="",
        repo_root=str(tmp_path / "repo"),
        related_pages=(),
    )

    pipeline_editor.toml_to_notebook(
        {
            "demo_project": [
                {
                    "D": "Run trainer stack",
                    "Q": "Select a single trainer.",
                    "M": "",
                    "C": (
                        "APP = 'demo_project'\n"
                        "trainer = 'ppo'\n"
                        "data_in = 'demo/in'\n"
                        "data_out = 'demo/out'\n"
                        "total_timesteps = 10000\n"
                    ),
                    "R": "runpy",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, object] = {}
    exec(helper_source, namespace)

    captured: dict[str, str] = {}

    class _Result:
        stdout = ""
        stderr = ""

        @staticmethod
        def check_returncode() -> None:
            return None

    def _fake_run(cmd, **kwargs):
        captured["script"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _Result()

    original_run = namespace["subprocess"].run
    try:
        namespace["subprocess"].run = _fake_run
        namespace["run_agilab_stage"](0, capture_output=False)
    finally:
        namespace["subprocess"].run = original_run

    assert '"trainer"' not in captured["script"]
    assert (
        'RUN_ARGS = json.loads(\'{"data_in": "demo/in", "data_out": "demo/out", "reset_target": false, '
        '"stages": [{"args": {"seed": 0, "total_timesteps": 10000}, '
        '"name": "ppo"}]}\')'
    ) in captured["script"]
    assert "RUN_MODE = json.loads('0')" in captured["script"]


def test_notebook_helper_respects_explicit_mode_in_shorthand(tmp_path):
    export_dir = tmp_path / "export" / "demo_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    app_root = tmp_path / "apps" / "demo_project"
    (app_root / "src").mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")

    context = notebook_export_support.NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(export_dir),
        active_app=str(app_root),
        app_settings_file=str(app_root / "src" / "app_settings.toml"),
        pages_root="",
        repo_root=str(tmp_path / "repo"),
        related_pages=(),
    )

    pipeline_editor.toml_to_notebook(
        {
            "demo_project": [
                {
                    "D": "Run trainer stack",
                    "Q": "Select a single trainer.",
                    "M": "",
                    "C": (
                        "APP = 'demo_project'\n"
                        "trainer = 'ppo'\n"
                        "data_in = 'demo/in'\n"
                        "data_out = 'demo/out'\n"
                        "mode = 3\n"
                    ),
                    "R": "runpy",
                }
            ]
        },
        toml_path,
        export_context=context,
    )

    notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, object] = {}
    exec(helper_source, namespace)

    captured: dict[str, str] = {}

    class _Result:
        stdout = ""
        stderr = ""

        @staticmethod
        def check_returncode() -> None:
            return None

    def _fake_run(cmd, **kwargs):
        captured["script"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _Result()

    original_run = namespace["subprocess"].run
    try:
        namespace["subprocess"].run = _fake_run
        namespace["run_agilab_stage"](0, capture_output=False)
    finally:
        namespace["subprocess"].run = original_run

    assert "RUN_MODE = json.loads('3')" in captured["script"]


def test_toml_to_notebook_plain_export_uses_local_source_checkout_mirror(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    export_dir = tmp_path / "export" / "uav_graph_routing"
    export_dir.mkdir(parents=True, exist_ok=True)
    toml_path = export_dir / "lab_stages.toml"
    mirror_path = repo_root / "exported_notebooks" / "uav_graph_routing" / "lab_stages.ipynb"
    sitecustomize_path = mirror_path.parent / "sitecustomize.py"

    try:
        if mirror_path.exists():
            mirror_path.unlink()
        if sitecustomize_path.exists():
            sitecustomize_path.unlink()
        pipeline_editor.toml_to_notebook({"demo_project": [{"C": "print('ok')\n"}]}, toml_path)
        notebook = json.loads(toml_path.with_suffix(".ipynb").read_text(encoding="utf-8"))
        mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
        assert mirror == notebook
        assert sitecustomize_path.exists()
        assert "debugpy._vendored" in sitecustomize_path.read_text(encoding="utf-8")
    finally:
        if mirror_path.exists():
            mirror_path.unlink()
        if sitecustomize_path.exists():
            sitecustomize_path.unlink()
        mirror_parent = mirror_path.parent
        while mirror_parent != repo_root and mirror_parent.exists():
            try:
                mirror_parent.rmdir()
            except OSError:
                break
            mirror_parent = mirror_parent.parent


def test_pycharm_notebook_sitecustomize_patches_debugpy_values_policy(tmp_path):
    debugpy = pytest.importorskip("debugpy")

    shim_dir = tmp_path / "notebook_dir"
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        notebook_export_support.pycharm_notebook_sitecustomize_text(),
        encoding="utf-8",
    )

    import subprocess

    env = os.environ.copy()
    pythonpath_entries = [str(shim_dir), str(Path(debugpy.__file__).resolve().parents[1])]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from debugpy._vendored import vendored\n"
                "with vendored('pydevd'):\n"
                "    import _pydevd_bundle.pydevd_constants as c\n"
                "    print(hasattr(c, 'ValuesPolicy'))\n"
                "    print(getattr(getattr(c, 'ValuesPolicy', None), 'ASYNC', 'missing'))\n"
            ),
        ],
        cwd=shim_dir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    stdout_lines = result.stdout.strip().splitlines()
    assert stdout_lines == ["True", "1"]


def test_pycharm_notebook_sitecustomize_blocks_python_ipynb_execution(tmp_path):
    shim_dir = tmp_path / "notebook_dir"
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        notebook_export_support.pycharm_notebook_sitecustomize_text(),
        encoding="utf-8",
    )
    notebook_path = shim_dir / "lab_stages.ipynb"
    notebook_path.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n', encoding="utf-8")

    import subprocess

    env = os.environ.copy()
    env["PYTHONPATH"] = str(shim_dir)

    result = subprocess.run(
        [sys.executable, str(notebook_path)],
        cwd=shim_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "AGILAB exported notebooks are Jupyter notebooks, not Python scripts." in result.stderr
    assert "uv run --with jupyterlab jupyter lab" in result.stderr
    assert "uv run --with nbconvert python -m jupyter nbconvert" in result.stderr
    assert "NameError: name 'null' is not defined" not in result.stderr


def test_pycharm_notebook_sitecustomize_uses_repo_project_prefix_for_mirror(tmp_path):
    repo_root = tmp_path / "repo"
    shim_dir = repo_root / "exported_notebooks" / "demo_project"
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        notebook_export_support.pycharm_notebook_sitecustomize_text(),
        encoding="utf-8",
    )
    notebook_path = shim_dir / "lab_stages.ipynb"
    notebook_path.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n', encoding="utf-8")

    import subprocess

    env = os.environ.copy()
    env["PYTHONPATH"] = str(shim_dir)

    result = subprocess.run(
        [sys.executable, str(notebook_path)],
        cwd=shim_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"uv --project {repo_root} run --with jupyterlab jupyter lab" in result.stderr
    assert f"uv --project {repo_root} run --with nbconvert python -m jupyter nbconvert" in result.stderr


def test_pycharm_notebook_sitecustomize_uses_app_project_prefix_for_project_notebooks(tmp_path):
    app_root = tmp_path / "apps" / "demo_project"
    shim_dir = app_root / "notebooks"
    shim_dir.mkdir(parents=True, exist_ok=True)
    (app_root / "pyproject.toml").write_text("[project]\nname='demo_project'\n", encoding="utf-8")
    (shim_dir / "sitecustomize.py").write_text(
        notebook_export_support.pycharm_notebook_sitecustomize_text(),
        encoding="utf-8",
    )
    notebook_path = shim_dir / "lab_stages.ipynb"
    notebook_path.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n', encoding="utf-8")

    import subprocess

    env = os.environ.copy()
    env["PYTHONPATH"] = str(shim_dir)

    result = subprocess.run(
        [sys.executable, str(notebook_path)],
        cwd=shim_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"uv --project {app_root} run --with jupyterlab jupyter lab" in result.stderr
    assert f"uv --project {app_root} run --with nbconvert python -m jupyter nbconvert" in result.stderr


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

    count = pipeline_editor.notebook_to_toml(uploaded, "lab_stages.toml", tmp_path / "demo_project")

    stored = tomllib.loads((tmp_path / "demo_project" / "lab_stages.toml").read_text(encoding="utf-8"))
    assert count == 1
    assert stored["demo_project"][0]["D"] == "ignore"
    assert stored["demo_project"][0]["Q"] == "Imported notebook cell cell-3"
    assert stored["demo_project"][0]["C"] == "print(3)\n"
    assert stored["demo_project"][0]["M"] == ""
    assert stored["demo_project"][0]["NB_CELL_ID"] == "cell-3"
    assert stored["demo_project"][0]["NB_CONTEXT_IDS"] == ["markdown-1"]
    assert stored["demo_project"][0]["NB_EXECUTION_MODE"] == "not_executed_import"


def test_notebook_to_toml_writes_preflight_contract_and_reports_warnings(monkeypatch, tmp_path):
    messages: list[tuple[str, str]] = []
    fake_st = SimpleNamespace(
        error=lambda message, *args, **kwargs: messages.append(("error", message)),
        warning=lambda message, *args, **kwargs: messages.append(("warning", message)),
        info=lambda message, *args, **kwargs: messages.append(("info", message)),
    )
    monkeypatch.setattr(pipeline_editor, "st", fake_st)

    uploaded = SimpleNamespace(
        name="demo.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["# Import context\n"]},
                    {
                        "cell_type": "code",
                        "source": [
                            "!pip install requests\n",
                            "import pandas as pd\n",
                            "df = pd.read_csv('data/orders.csv')\n",
                            "df.to_parquet('artifacts/orders.parquet')\n",
                        ],
                    },
                ]
            }
        ).encode("utf-8"),
    )

    count = pipeline_editor.notebook_to_toml(uploaded, "lab_stages.toml", tmp_path / "demo_project")

    contract = json.loads((tmp_path / "demo_project" / "notebook_import_contract.json").read_text(encoding="utf-8"))
    view_plan = json.loads((tmp_path / "demo_project" / "notebook_import_view_plan.json").read_text(encoding="utf-8"))
    assert count == 1
    assert contract["schema"] == "agilab.notebook_import_contract.v1"
    assert view_plan["schema"] == "agilab.notebook_import_view_plan.v1"
    assert view_plan["status"] == "unmatched"
    assert contract["preflight"]["status"] == "review"
    assert contract["artifact_contract"]["inputs"] == ["data/orders.csv"]
    assert contract["artifact_contract"]["outputs"] == ["artifacts/orders.parquet"]
    assert {warning["rule"] for warning in contract["warnings"]} >= {
        "dependency_install",
        "shell_execution",
    }
    assert messages == [
        (
            "warning",
            "Notebook import preflight: review; 1 stage(s), 1 input(s), 1 output(s). "
            "Contract: notebook_import_contract.json; View plan: notebook_import_view_plan.json",
        )
    ]


def test_notebook_to_toml_uses_lab_stages_key_when_module_dir_has_no_name(monkeypatch, tmp_path):
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

    count = pipeline_editor.notebook_to_toml(uploaded, "lab_stages.toml", Path(""))

    stored = tomllib.loads((tmp_path / "lab_stages.toml").read_text(encoding="utf-8"))
    assert count == 1
    assert stored["lab_stages"][0]["C"] == "print(9)\n"
    assert stored["lab_stages"][0]["NB_CELL_ID"] == "cell-1"
    assert stored["lab_stages"][0]["NB_EXECUTION_MODE"] == "not_executed_import"


def test_restore_pipeline_snapshot_rebuilds_engine_from_map_when_selection_missing(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"idx": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(pipeline_editor, "_write_stages_for_module", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda _path: False)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_telemetry_project",
        tmp_path / "lab_stages.toml",
        "idx",
        "sequence_widget",
        {
            "stages": [{}],
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
    monkeypatch.setattr(pipeline_editor, "_write_stages_for_module", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(pipeline_editor, "_persist_sequence_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_editor, "_bump_history_revision", lambda: None)
    monkeypatch.setattr(pipeline_editor, "_is_valid_runtime_root", lambda _path: False)

    error = pipeline_editor._restore_pipeline_snapshot(
        tmp_path / "flight_telemetry_project",
        tmp_path / "lab_stages.toml",
        "idx",
        "sequence_widget",
        {
            "stages": ["not-a-dict"],
            "active_stage": 0,
            "sequence": [0],
        },
    )

    assert error is None
    assert fake_st.session_state["idx"][:6] == [0, "", "", "", "", ""]
