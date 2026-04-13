from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


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
