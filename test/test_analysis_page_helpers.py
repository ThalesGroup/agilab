from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("src/agilab/pages/4_▶️ ANALYSIS.py")


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location("agilab_analysis_page_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_config_loads_valid_toml(tmp_path: Path):
    module = _load_analysis_module()
    config_path = tmp_path / "view.toml"
    config_path.write_text('title = "demo"\n', encoding="utf-8")

    assert module._read_config(config_path) == {"title": "demo"}


def test_read_config_reports_invalid_toml(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    errors: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(error=lambda message: errors.append(str(message))))
    config_path = tmp_path / "view.toml"
    config_path.write_text("title = \n", encoding="utf-8")

    assert module._read_config(config_path) == {}
    assert any(message.startswith("Error loading configuration:") for message in errors)


def test_write_config_creates_parent_and_persists_toml(tmp_path: Path):
    module = _load_analysis_module()
    config_path = tmp_path / "nested" / "view.toml"

    module._write_config(config_path, {"title": "demo"})

    assert config_path.read_text(encoding="utf-8") == 'title = "demo"\n'


def test_write_config_reports_oserror(tmp_path: Path, monkeypatch):
    module = _load_analysis_module()
    errors: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(error=lambda message: errors.append(str(message))))

    def _raise_dump(_cfg, _stream):
        raise OSError("disk full")

    monkeypatch.setattr(module.tomli_w, "dump", _raise_dump)
    config_path = tmp_path / "nested" / "view.toml"

    module._write_config(config_path, {"title": "demo"})

    assert errors == ["Error updating configuration: disk full"]
