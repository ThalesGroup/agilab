from pathlib import Path

import tomllib
import pytest
from pydantic import BaseModel

from agi_env.app_args import (
    dump_model_to_toml,
    load_model_from_toml,
    merge_model_data,
    model_to_payload,
)


class ExampleModel(BaseModel):
    foo: int = 1
    bar: str = "baz"


def test_model_to_payload_round_trip():
    model = ExampleModel(foo=3, bar="qux")
    payload = model_to_payload(model)
    assert payload == {"foo": 3, "bar": "qux"}


def test_merge_model_data_applies_overrides_without_mutating_original():
    original = ExampleModel(foo=1, bar="orig")
    updated = merge_model_data(original, {"bar": "changed"})

    assert updated.bar == "changed"
    assert updated.foo == 1
    assert original.bar == "orig"


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
