from __future__ import annotations

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest
from streamlit.errors import StreamlitAPIException


class _SessionState(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value):
        self[name] = value


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


def _load_pipeline_module():
    _prime_current_agilab_package()
    module_path = Path("src/agilab/pages/3_WORKFLOW.py")
    spec = importlib.util.spec_from_file_location("agilab_pipeline_page_helper_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_pipeline_module_with_mixed_checkout(monkeypatch, stale_root: Path):
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
    module_path = Path("src/agilab/pages/3_WORKFLOW.py")
    spec = importlib.util.spec_from_file_location("agilab_pipeline_page_mixed_checkout_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_pre_prompt_messages_returns_list(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    warnings: list[str] = []
    fake_st = SimpleNamespace(warning=lambda message: warnings.append(str(message)))
    monkeypatch.setattr(module, "st", fake_st)

    app_src = tmp_path / "demo_app"
    app_src.mkdir()
    (app_src / "pre_prompt.json").write_text('[{"role": "system", "content": "hi"}]\n', encoding="utf-8")
    env = SimpleNamespace(app_src=app_src)

    result = module._load_pre_prompt_messages(env)

    assert result == [{"role": "system", "content": "hi"}]
    assert warnings == []


def test_load_pre_prompt_messages_treats_missing_file_as_optional(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    warnings: list[str] = []
    fake_st = SimpleNamespace(warning=lambda message: warnings.append(str(message)))
    monkeypatch.setattr(module, "st", fake_st)

    app_src = tmp_path / "demo_app"
    app_src.mkdir()
    env = SimpleNamespace(app_src=app_src)

    result = module._load_pre_prompt_messages(env)

    assert result == []
    assert not (app_src / "pre_prompt.json").exists()
    assert warnings == []


def test_load_pre_prompt_messages_rejects_invalid_json(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    warnings: list[str] = []
    fake_st = SimpleNamespace(warning=lambda message: warnings.append(str(message)))
    monkeypatch.setattr(module, "st", fake_st)

    app_src = tmp_path / "demo_app"
    app_src.mkdir()
    (app_src / "pre_prompt.json").write_text("{broken", encoding="utf-8")
    env = SimpleNamespace(app_src=app_src)

    result = module._load_pre_prompt_messages(env)

    assert result == []
    assert any("Failed to load pre_prompt.json" in message for message in warnings)


def test_caption_once_suppresses_repeated_low_priority_guidance(monkeypatch):
    module = _load_pipeline_module()
    captions: list[str] = []
    fake_st = SimpleNamespace(
        caption=lambda message: captions.append(str(message)),
        session_state={},
    )
    monkeypatch.setattr(module, "st", fake_st)

    module._caption_once("demo", "Only once.")
    module._caption_once("demo", "Only once.")
    module._caption_once("other", "Second notice.")

    assert captions == ["Only once.", "Second notice."]


def test_ensure_notebook_export_creates_missing_notebook(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    warnings: list[str] = []
    generated: list[tuple[dict, Path]] = []
    monkeypatch.setattr(module, "logger", SimpleNamespace(warning=lambda message: warnings.append(str(message))))
    monkeypatch.setattr(module, "toml_to_notebook", lambda payload, path: generated.append((payload, path)))

    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text('[[demo]]\nQ = "q"\n', encoding="utf-8")

    module._ensure_notebook_export(stages_file)

    assert generated == [({"demo": [{"Q": "q"}]}, stages_file)]
    assert warnings == []


def test_ensure_notebook_export_logs_invalid_toml(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    warnings: list[str] = []
    monkeypatch.setattr(
        module,
        "logger",
        SimpleNamespace(warning=lambda message, *args: warnings.append(message % args if args else str(message))),
    )
    monkeypatch.setattr(module, "toml_to_notebook", lambda *_args, **_kwargs: None)

    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("[demo\n", encoding="utf-8")

    module._ensure_notebook_export(stages_file)

    assert any("Skipping notebook generation:" in message for message in warnings)


def test_render_notebook_download_button_renders_bytes(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    download_calls: list[dict[str, object]] = []
    errors: list[str] = []
    captions: list[str] = []
    fake_container = SimpleNamespace(
        download_button=lambda label, **kwargs: download_calls.append({"label": label, **kwargs}),
        error=lambda message: errors.append(str(message)),
        caption=lambda message: captions.append(str(message)),
    )

    notebook_path = tmp_path / "lab_stages.ipynb"
    notebook_path.write_bytes(b'{"cells": []}')
    pycharm_path = tmp_path / "exported_notebooks" / "demo" / "lab_stages.ipynb"

    module._render_notebook_download_button(
        notebook_path,
        "pipeline-export",
        pycharm_path=pycharm_path,
        container=fake_container,
    )

    assert download_calls == [
        {
            "label": "Download pipeline notebook",
            "data": b'{"cells": []}',
            "file_name": "lab_stages.ipynb",
            "mime": "application/x-ipynb+json",
            "key": "pipeline-export",
        }
    ]
    assert errors == []
    assert captions == [f"PyCharm notebook: `{pycharm_path}`"]


def test_render_notebook_download_button_reports_streamlit_failure(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    errors: list[str] = []

    def _raise_download_error(_label, **_kwargs):
        raise StreamlitAPIException("download failed")

    fake_container = SimpleNamespace(
        download_button=_raise_download_error,
        error=lambda message: errors.append(str(message)),
        caption=lambda _message: None,
    )

    notebook_path = tmp_path / "lab_stages.ipynb"
    notebook_path.write_bytes(b'{"cells": []}')

    module._render_notebook_download_button(notebook_path, "pipeline-export", container=fake_container)

    assert errors == ["Failed to prepare notebook export: download failed"]


def test_pipeline_on_df_change_uses_page_local_load_last_stage(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    export_root = tmp_path / "export"
    selected_rel = Path("demo/new.csv")
    stages_file = tmp_path / "stages" / "lab_stages.toml"
    session_state = _SessionState(
        {
            "env": SimpleNamespace(AGILAB_EXPORT_ABS=export_root),
            "demo": [0, "old"],
            "demodf": selected_rel,
        }
    )
    loaded: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(
        module,
        "load_last_stage",
        lambda module_dir, stages_path, page_key: loaded.append((module_dir, stages_path, page_key)),
    )

    module.on_df_change(Path("demo_module"), "demo", None, stages_file)

    assert session_state["df_file"] == export_root / selected_rel
    assert session_state["demodf_file"] == export_root / selected_rel
    assert "demo" not in session_state
    assert session_state["page_broken"] is True
    assert loaded == [(Path("demo_module"), stages_file, "demo")]
    assert stages_file.parent.exists()


def test_filter_pipeline_dataframe_files_keeps_supported_sorted():
    module = _load_pipeline_module()

    files = [
        Path("demo/notes.txt"),
        Path("demo/b.JSONL"),
        Path("demo/lab_steps.toml"),
        Path("demo/a.csv"),
        Path("demo/c.parquet"),
    ]

    assert module._filter_pipeline_dataframe_files(files) == [
        Path("demo/a.csv"),
        Path("demo/b.JSONL"),
        Path("demo/c.parquet"),
    ]
    assert "*.csv" in module._PIPELINE_DATA_SOURCE_PATTERNS
    assert "*" not in module._PIPELINE_DATA_SOURCE_PATTERNS


def test_clear_dataframe_picker_selection_resets_page_and_picker_state(monkeypatch):
    module = _load_pipeline_module()
    session_state = {
        "demodf": Path("demo/old.csv"),
        "demodf_file": "/tmp/demo/old.csv",
        "df_file": "/tmp/demo/old.csv",
        "demo:dataframe_picker:selected_paths": ["/tmp/demo/old.csv"],
    }
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))

    module._clear_dataframe_picker_selection("demodf", picker_key="demo:dataframe_picker")

    assert "demodf" not in session_state
    assert "demodf_file" not in session_state
    assert "demo:dataframe_picker:selected_paths" not in session_state
    assert session_state["df_file"] is None


def test_dataframe_picker_apply_hydrates_initial_picker_selection(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    session_state = {}
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))

    export_root = tmp_path / "export"
    df_files_rel = [Path("demo/old.csv"), Path("demo/new.csv")]
    dataframe_key = "demodf"

    applied = module._apply_dataframe_picker_selection(
        export_root / df_files_rel[1],
        dataframe_key=dataframe_key,
        df_files_rel=df_files_rel,
        export_root=export_root,
    )

    assert applied is False
    assert session_state[dataframe_key] == df_files_rel[1]
    assert session_state["demodf_file"] == str((export_root / df_files_rel[1]).resolve(strict=False))
    assert session_state["df_file"] == str((export_root / df_files_rel[1]).resolve(strict=False))


def test_dataframe_picker_apply_updates_dataframe_state_when_picker_changed(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    session_state = {}
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))

    export_root = tmp_path / "export"
    df_files_rel = [Path("demo/old.csv"), Path("demo/new.csv")]
    dataframe_key = "demodf"
    new_abs = str((export_root / df_files_rel[1]).resolve(strict=False))
    session_state[dataframe_key] = df_files_rel[0]

    applied = module._apply_dataframe_picker_selection(
        export_root / df_files_rel[1],
        dataframe_key=dataframe_key,
        df_files_rel=df_files_rel,
        export_root=export_root,
    )

    assert applied is True
    assert session_state[dataframe_key] == df_files_rel[1]
    assert session_state["demodf_file"] == new_abs
    assert session_state["df_file"] == new_abs


def test_load_about_page_module_uses_imported_module(monkeypatch):
    module = _load_pipeline_module()
    imported = SimpleNamespace(main=lambda: None)
    monkeypatch.setattr(module, "load_local_module", lambda *_args, **_kwargs: imported)

    result = module._load_about_page_module()

    assert result is imported


def test_load_about_page_module_falls_back_to_file_loader(monkeypatch):
    module = _load_pipeline_module()
    fallback_module = SimpleNamespace(main=lambda: None)

    monkeypatch.setattr(module, "load_local_module", lambda *_args, **_kwargs: fallback_module)

    result = module._load_about_page_module()

    assert hasattr(result, "main")


def test_load_about_page_module_raises_last_import_error_when_no_fallback(monkeypatch):
    module = _load_pipeline_module()

    def _raise_missing(*_args, **_kwargs):
        raise ModuleNotFoundError("missing about page")

    monkeypatch.setattr(module, "load_local_module", _raise_missing)

    try:
        module._load_about_page_module()
    except ModuleNotFoundError as exc:
        assert "missing about page" in str(exc)
    else:
        raise AssertionError("Expected ModuleNotFoundError")


def test_pipeline_page_raises_mixed_checkout_error(monkeypatch, tmp_path):
    stale_root = tmp_path / "stale" / "agilab"
    stale_root.mkdir(parents=True)

    with pytest.raises(ImportError, match="Mixed AGILAB checkout detected"):
        _load_pipeline_module_with_mixed_checkout(monkeypatch, stale_root)
