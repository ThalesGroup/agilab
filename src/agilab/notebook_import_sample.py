"""Packaged notebook sample used by the AGILAB import wizard."""

from __future__ import annotations

from pathlib import Path


SAMPLE_NOTEBOOK_RESOURCE_NAME = "notebook_pipeline_import_sample.ipynb"
SAMPLE_NOTEBOOK_DOWNLOAD_NAME = "flight_telemetry_from_notebook.ipynb"
SAMPLE_NOTEBOOK_MIME = "application/x-ipynb+json"


def sample_notebook_path() -> Path:
    """Return the packaged sample notebook path."""
    return Path(__file__).resolve().parent / "resources" / SAMPLE_NOTEBOOK_RESOURCE_NAME


def read_sample_notebook_bytes() -> bytes:
    """Return the packaged sample notebook payload."""
    return sample_notebook_path().read_bytes()
