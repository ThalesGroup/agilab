from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import agilab  # noqa: E402

SOURCE_PACKAGE = str(SRC_ROOT / "agilab")
if SOURCE_PACKAGE not in agilab.__path__:
    agilab.__path__.insert(0, SOURCE_PACKAGE)

notebook_import_sample = importlib.import_module("agilab.notebook_import_sample")


def test_notebook_import_sample_catalog_and_default_lookup() -> None:
    samples = notebook_import_sample.list_sample_notebooks()

    assert [sample.sample_id for sample in samples] == [
        "flight_telemetry",
        "minimal_app",
        "weather_forecast",
        "mission_decision",
    ]
    assert notebook_import_sample.get_sample_notebook() == samples[0]
    assert notebook_import_sample.get_sample_notebook("minimal_app").recommended_template == "minimal_app_project"
    assert notebook_import_sample.get_sample_notebook("weather_forecast").project_name_hint == (
        "weather-forecast-from-notebook-project"
    )


def test_notebook_import_sample_paths_and_payloads_are_packaged() -> None:
    for sample in notebook_import_sample.list_sample_notebooks():
        path = notebook_import_sample.sample_notebook_path(sample.sample_id)
        payload = notebook_import_sample.read_sample_notebook_bytes(sample.sample_id)
        notebook = json.loads(payload.decode("utf-8"))

        assert path.is_file()
        assert path.name == Path(sample.resource_name).name
        assert notebook["nbformat"] == 4
        assert isinstance(notebook["cells"], list)
        assert notebook["cells"]


def test_notebook_import_sample_rejects_unknown_id_with_available_samples() -> None:
    with pytest.raises(KeyError, match="available: flight_telemetry, minimal_app, weather_forecast, mission_decision"):
        notebook_import_sample.get_sample_notebook("unknown")
