"""Packaged notebook sample used by the AGILAB import wizard."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SAMPLE_NOTEBOOK_RESOURCE_NAME = "notebook_pipeline_import_sample.ipynb"
SAMPLE_NOTEBOOK_DOWNLOAD_NAME = "flight_telemetry_from_notebook.ipynb"
SAMPLE_NOTEBOOK_MIME = "application/x-ipynb+json"
SAMPLE_NOTEBOOK_SESSION_KEY = "_agilab_use_packaged_notebook_import_sample"
SAMPLE_NOTEBOOK_DEFAULT_ID = "flight_telemetry"


@dataclass(frozen=True)
class NotebookImportSample:
    """Packaged notebook import sample metadata."""

    sample_id: str
    title: str
    resource_name: str
    download_name: str
    recommended_template: str
    project_name_hint: str


SAMPLE_NOTEBOOKS = (
    NotebookImportSample(
        sample_id="flight_telemetry",
        title="Flight telemetry from notebook",
        resource_name=SAMPLE_NOTEBOOK_RESOURCE_NAME,
        download_name=SAMPLE_NOTEBOOK_DOWNLOAD_NAME,
        recommended_template="flight_telemetry_project",
        project_name_hint="flight-telemetry-from-notebook-project",
    ),
    NotebookImportSample(
        sample_id="minimal_app",
        title="MinimalApp from notebook",
        resource_name="notebook_import_samples/minimal_app_from_notebook.ipynb",
        download_name="minimal_app_from_notebook.ipynb",
        recommended_template="minimal_app_project",
        project_name_hint="minimal_app-from-notebook-project",
    ),
    NotebookImportSample(
        sample_id="weather_forecast",
        title="Weather forecast from notebook",
        resource_name="notebook_import_samples/weather_forecast_from_notebook.ipynb",
        download_name="weather_forecast_from_notebook.ipynb",
        recommended_template="weather_forecast_project",
        project_name_hint="weather-forecast-from-notebook-project",
    ),
    NotebookImportSample(
        sample_id="mission_decision",
        title="Mission decision from notebook",
        resource_name="notebook_import_samples/mission_decision_from_notebook.ipynb",
        download_name="mission_decision_from_notebook.ipynb",
        recommended_template="mission_decision_project",
        project_name_hint="mission-decision-from-notebook-project",
    ),
)


def list_sample_notebooks() -> tuple[NotebookImportSample, ...]:
    """Return packaged notebook import samples."""
    return SAMPLE_NOTEBOOKS


def get_sample_notebook(sample_id: str = SAMPLE_NOTEBOOK_DEFAULT_ID) -> NotebookImportSample:
    """Return one packaged notebook import sample by id."""
    for sample in SAMPLE_NOTEBOOKS:
        if sample.sample_id == sample_id:
            return sample
    available = ", ".join(sample.sample_id for sample in SAMPLE_NOTEBOOKS)
    raise KeyError(f"Unknown notebook import sample {sample_id!r}; available: {available}")


def sample_notebook_path(sample_id: str = SAMPLE_NOTEBOOK_DEFAULT_ID) -> Path:
    """Return the packaged sample notebook path."""
    sample = get_sample_notebook(sample_id)
    return Path(__file__).resolve().parent / "resources" / sample.resource_name


def read_sample_notebook_bytes(sample_id: str = SAMPLE_NOTEBOOK_DEFAULT_ID) -> bytes:
    """Return the packaged sample notebook payload."""
    return sample_notebook_path(sample_id).read_bytes()
