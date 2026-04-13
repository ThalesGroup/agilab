from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from streamlit.errors import StreamlitAPIException


def _load_pipeline_module():
    module_path = Path("src/agilab/pages/3_▶️ PIPELINE.py")
    spec = importlib.util.spec_from_file_location("agilab_pipeline_page_helper_tests", module_path)
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


def test_load_pre_prompt_messages_recovers_missing_file(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    warnings: list[str] = []
    fake_st = SimpleNamespace(warning=lambda message: warnings.append(str(message)))
    monkeypatch.setattr(module, "st", fake_st)

    app_src = tmp_path / "demo_app"
    app_src.mkdir()
    env = SimpleNamespace(app_src=app_src)

    result = module._load_pre_prompt_messages(env)

    assert result == []
    assert (app_src / "pre_prompt.json").read_text(encoding="utf-8") == "[]\n"
    assert any("Missing pre_prompt.json" in message for message in warnings)


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
    monkeypatch.setattr(module, "logger", SimpleNamespace(warning=lambda message: warnings.append(str(message))))
    monkeypatch.setattr(module, "toml_to_notebook", lambda *_args, **_kwargs: None)

    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("[demo\n", encoding="utf-8")

    module._ensure_notebook_export(steps_file)

    assert any("Skipping notebook generation:" in message for message in warnings)


def test_render_notebook_download_button_renders_bytes(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    download_calls: list[dict[str, object]] = []
    errors: list[str] = []
    fake_sidebar = SimpleNamespace(
        download_button=lambda label, **kwargs: download_calls.append({"label": label, **kwargs}),
        error=lambda message: errors.append(str(message)),
    )
    monkeypatch.setattr(module.st, "sidebar", fake_sidebar)

    notebook_path = tmp_path / "lab_steps.ipynb"
    notebook_path.write_bytes(b'{"cells": []}')

    module._render_notebook_download_button(notebook_path, "pipeline-export")

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


def test_render_notebook_download_button_reports_streamlit_failure(tmp_path, monkeypatch):
    module = _load_pipeline_module()
    errors: list[str] = []

    def _raise_download_error(_label, **_kwargs):
        raise StreamlitAPIException("download failed")

    fake_sidebar = SimpleNamespace(
        download_button=_raise_download_error,
        error=lambda message: errors.append(str(message)),
    )
    monkeypatch.setattr(module.st, "sidebar", fake_sidebar)

    notebook_path = tmp_path / "lab_steps.ipynb"
    notebook_path.write_bytes(b'{"cells": []}')

    module._render_notebook_download_button(notebook_path, "pipeline-export")

    assert errors == ["Failed to prepare notebook export: download failed"]


def test_load_about_page_module_uses_imported_module(monkeypatch):
    module = _load_pipeline_module()
    imported = SimpleNamespace(main=lambda: None)
    monkeypatch.setattr(module.importlib, "import_module", lambda name: imported if name == "agilab.About_agilab" else None)

    result = module._load_about_page_module()

    assert result is imported


def test_load_about_page_module_falls_back_to_file_loader(monkeypatch):
    module = _load_pipeline_module()
    imported_errors = []
    fallback_module = SimpleNamespace(main=lambda: None)

    def _raise_missing(_name):
        raise ModuleNotFoundError("missing")

    class _Loader:
        def exec_module(self, target):
            target.main = fallback_module.main

    monkeypatch.setattr(module.importlib, "import_module", _raise_missing)
    monkeypatch.setattr(
        module.importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: SimpleNamespace(loader=_Loader()),
    )
    monkeypatch.setattr(
        module.importlib.util,
        "module_from_spec",
        lambda _spec: SimpleNamespace(),
    )

    result = module._load_about_page_module()

    assert hasattr(result, "main")


def test_load_about_page_module_raises_last_import_error_when_no_fallback(monkeypatch):
    module = _load_pipeline_module()

    def _raise_missing(_name):
        raise ModuleNotFoundError("missing about page")

    monkeypatch.setattr(module.importlib, "import_module", _raise_missing)
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    try:
        module._load_about_page_module()
    except ModuleNotFoundError as exc:
        assert "missing about page" in str(exc)
    else:
        raise AssertionError("Expected ModuleNotFoundError")
