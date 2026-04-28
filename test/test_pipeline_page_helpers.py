from __future__ import annotations

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest
from streamlit.errors import StreamlitAPIException


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
    module_path = Path("src/agilab/pages/3_▶️ PIPELINE.py")
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
    module_path = Path("src/agilab/pages/3_▶️ PIPELINE.py")
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

    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text('[[demo]]\nQ = "q"\n', encoding="utf-8")

    module._ensure_notebook_export(steps_file)

    assert generated == [({"demo": [{"Q": "q"}]}, steps_file)]
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

    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("[demo\n", encoding="utf-8")

    module._ensure_notebook_export(steps_file)

    assert any("Skipping notebook generation:" in message for message in warnings)


def test_render_notebook_download_button_renders_bytes(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    download_calls: list[dict[str, object]] = []
    errors: list[str] = []
    captions: list[str] = []
    fake_sidebar = SimpleNamespace(
        download_button=lambda label, **kwargs: download_calls.append({"label": label, **kwargs}),
        error=lambda message: errors.append(str(message)),
        caption=lambda message: captions.append(str(message)),
    )
    monkeypatch.setattr(module.st, "sidebar", fake_sidebar)

    notebook_path = tmp_path / "lab_steps.ipynb"
    notebook_path.write_bytes(b'{"cells": []}')
    pycharm_path = tmp_path / "exported_notebooks" / "demo" / "lab_steps.ipynb"

    module._render_notebook_download_button(notebook_path, "pipeline-export", pycharm_path=pycharm_path)

    assert download_calls == [
        {
            "label": "Export notebook",
            "data": b'{"cells": []}',
            "file_name": "lab_steps.ipynb",
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

    fake_sidebar = SimpleNamespace(
        download_button=_raise_download_error,
        error=lambda message: errors.append(str(message)),
        caption=lambda _message: None,
    )
    monkeypatch.setattr(module.st, "sidebar", fake_sidebar)

    notebook_path = tmp_path / "lab_steps.ipynb"
    notebook_path.write_bytes(b'{"cells": []}')

    module._render_notebook_download_button(notebook_path, "pipeline-export")

    assert errors == ["Failed to prepare notebook export: download failed"]


def test_dataframe_picker_syncs_from_selectbox_when_selectbox_changed(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    session_state = {}
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))

    export_root = tmp_path / "export"
    df_files_rel = [Path("demo/old.csv"), Path("demo/new.csv")]
    picker_key = "demo/dataframe_picker"
    selectbox_key = "demodf"
    old_abs = str((export_root / df_files_rel[0]).resolve(strict=False))
    new_abs = str((export_root / df_files_rel[1]).resolve(strict=False))
    session_state[selectbox_key] = df_files_rel[1]
    session_state[f"{picker_key}:selected_paths"] = [old_abs]
    session_state[f"{picker_key}:last_applied"] = old_abs

    module._sync_dataframe_picker_from_selectbox(
        picker_key=picker_key,
        selectbox_key=selectbox_key,
        df_files_rel=df_files_rel,
        export_root=export_root,
    )

    assert session_state[selectbox_key] == df_files_rel[1]
    assert session_state[f"{picker_key}:selected_paths"] == [new_abs]
    assert session_state[f"{picker_key}:last_applied"] == new_abs


def test_dataframe_picker_apply_ignores_stale_picker_after_selectbox_sync(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    session_state = {}
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))

    export_root = tmp_path / "export"
    df_files_rel = [Path("demo/old.csv"), Path("demo/new.csv")]
    picker_key = "demo/dataframe_picker"
    selectbox_key = "demodf"
    new_abs = str((export_root / df_files_rel[1]).resolve(strict=False))
    session_state[selectbox_key] = df_files_rel[1]
    session_state[f"{picker_key}:last_applied"] = new_abs

    applied = module._apply_dataframe_picker_selection(
        export_root / df_files_rel[1],
        picker_key=picker_key,
        selectbox_key=selectbox_key,
        df_files_rel=df_files_rel,
        export_root=export_root,
    )

    assert applied is False
    assert session_state[selectbox_key] == df_files_rel[1]


def test_dataframe_picker_apply_updates_selectbox_when_picker_changed(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    session_state = {}
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))

    export_root = tmp_path / "export"
    df_files_rel = [Path("demo/old.csv"), Path("demo/new.csv")]
    picker_key = "demo/dataframe_picker"
    selectbox_key = "demodf"
    old_abs = str((export_root / df_files_rel[0]).resolve(strict=False))
    new_abs = str((export_root / df_files_rel[1]).resolve(strict=False))
    session_state[selectbox_key] = df_files_rel[0]
    session_state[f"{picker_key}:last_applied"] = old_abs

    applied = module._apply_dataframe_picker_selection(
        export_root / df_files_rel[1],
        picker_key=picker_key,
        selectbox_key=selectbox_key,
        df_files_rel=df_files_rel,
        export_root=export_root,
    )

    assert applied is True
    assert session_state[selectbox_key] == df_files_rel[1]
    assert session_state[f"{picker_key}:selected_paths"] == [new_abs]
    assert session_state[f"{picker_key}:last_applied"] == new_abs


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
