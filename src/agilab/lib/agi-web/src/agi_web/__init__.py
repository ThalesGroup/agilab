"""Portable AGILAB web component contracts."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _package_version

from .component import (
    AGI_WEB_COMPONENT_SCHEMA,
    AGI_WEB_EVIDENCE_SCHEMA,
    SUPPORTED_RENDERER_TECHNOLOGIES,
    AgiWebAction,
    AgiWebAsset,
    AgiWebComponent,
    AgiWebRendererSpec,
    component_evidence,
    component_to_static_html,
    normalize_component_id,
    normalize_json_value,
    records_from_data,
    render_notebook,
    render_streamlit,
    stable_sha256,
    to_canonical_json,
)

try:
    __version__ = _package_version("agi-web")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = (
    "AGI_WEB_COMPONENT_SCHEMA",
    "AGI_WEB_EVIDENCE_SCHEMA",
    "SUPPORTED_RENDERER_TECHNOLOGIES",
    "AgiWebAction",
    "AgiWebAsset",
    "AgiWebComponent",
    "AgiWebRendererSpec",
    "__version__",
    "component_evidence",
    "component_to_static_html",
    "normalize_component_id",
    "normalize_json_value",
    "records_from_data",
    "render_notebook",
    "render_streamlit",
    "stable_sha256",
    "to_canonical_json",
)
