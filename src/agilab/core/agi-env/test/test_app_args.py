import builtins
from pathlib import Path
from types import SimpleNamespace

import tomllib
import pytest
from pydantic import BaseModel

from agi_env.app_args import (
    dump_model_to_toml,
    load_model_from_toml,
    merge_model_data,
    model_to_payload,
    prefer_persisted_value,
)


class ExampleModel(BaseModel):
    foo: int = 1
    bar: str = "baz"


def test_model_to_payload_round_trip():
    model = ExampleModel(foo=3, bar="qux")
    payload = model_to_payload(model)
    assert payload == {"foo": 3, "bar": "qux"}


def test_prefer_persisted_value_preserves_explicit_values():
    assert prefer_persisted_value("saved", "fallback") == "saved"
    assert prefer_persisted_value(Path("saved"), Path("fallback")) == Path("saved")
    assert prefer_persisted_value(0, 1) == 0
    assert prefer_persisted_value(None, "fallback") == "fallback"
    assert prefer_persisted_value("", "fallback") == "fallback"
    assert prefer_persisted_value(False, "fallback") == "fallback"


def test_merge_model_data_applies_overrides_without_mutating_original():
    original = ExampleModel(foo=1, bar="orig")
    updated = merge_model_data(original, {"bar": "changed"})

    assert updated.bar == "changed"
    assert updated.foo == 1
    assert original.bar == "orig"


def test_merge_model_data_without_overrides_returns_copy():
    original = ExampleModel(foo=4, bar="same")

    updated = merge_model_data(original, {})

    assert updated == original
    assert updated is not original


def test_load_model_from_toml_reads_existing_section(tmp_path: Path):
    settings = tmp_path / "config.toml"
    settings.write_text(
        """
[args]
foo = 10
bar = "from_toml"
""".strip()
    )

    model = load_model_from_toml(ExampleModel, settings)
    assert model.foo == 10
    assert model.bar == "from_toml"


def test_load_model_from_toml_returns_defaults_when_missing(tmp_path: Path):
    settings = tmp_path / "missing.toml"
    model = load_model_from_toml(ExampleModel, settings)
    assert model == ExampleModel()


def test_load_model_from_toml_returns_defaults_when_section_is_absent(tmp_path: Path):
    settings = tmp_path / "config.toml"
    settings.write_text(
        """
[other]
foo = 10
""".strip()
    )

    model = load_model_from_toml(ExampleModel, settings)

    assert model == ExampleModel()


def test_load_model_from_toml_raises_on_invalid_payload(tmp_path: Path):
    settings = tmp_path / "invalid.toml"
    settings.write_text(
        """
[args]
foo = "bad"
""".strip()
    )

    with pytest.raises(ValueError):
        load_model_from_toml(ExampleModel, settings)


def test_dump_model_to_toml_creates_file_and_section(tmp_path: Path):
    settings = tmp_path / "config.toml"
    model = ExampleModel(foo=7, bar="written")

    dump_model_to_toml(model, settings)

    data = tomllib.loads(settings.read_text())
    assert data["args"] == {"foo": 7, "bar": "written"}


def test_dump_model_to_toml_respects_create_missing_flag(tmp_path: Path):
    settings = tmp_path / "config.toml"
    model = ExampleModel()

    with pytest.raises(FileNotFoundError):
        dump_model_to_toml(model, settings, create_missing=False)

    dump_model_to_toml(model, settings)
    dump_model_to_toml(model, settings, create_missing=False)


def test_dump_model_to_toml_falls_back_to_tomlkit_when_tomli_w_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = tmp_path / "config.toml"
    model = ExampleModel(foo=9, bar="tomlkit")
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tomli_w":
            raise ModuleNotFoundError("missing tomli_w")
        if name == "tomlkit":
            return SimpleNamespace(dumps=lambda data: '[args]\nfoo = 9\nbar = "tomlkit"\n')
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    dump_model_to_toml(model, settings)

    data = tomllib.loads(settings.read_text())
    assert data["args"] == {"foo": 9, "bar": "tomlkit"}
