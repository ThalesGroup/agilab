# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Recorded scenario comparisons using the cockpit's existing evidence helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import Markdown

from agi_pages.runtime import discover_files, load_json_object, relative_label

import importlib.util


def _evidence_helpers():
    # The notebook loader executes this file directly, outside its package.
    path = Path(__file__).with_name("evidence.py")
    spec = importlib.util.spec_from_file_location(
        "agilab_notebook_scenario_evidence", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load scenario evidence helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_inline(
    *, page: str, record: dict[str, Any], export_payload: dict[str, Any]
) -> list[Any]:
    outputs: list[Any] = [Markdown(f"### {record.get('label') or page}")]
    value = export_payload.get("artifact_dir")
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return outputs + [
            Markdown("No export artifact directory is recorded in this notebook.")
        ]
    root = Path(value)
    if not root.is_dir():
        return outputs + [Markdown(f"Missing artifact directory: `{root}`.")]
    paths = discover_files(root, "**/*_summary_metrics.json")
    if not paths:
        return outputs + [
            Markdown("No scenario summaries were found in the exported artifacts.")
        ]
    try:
        evidence = _evidence_helpers()
    except (ImportError, OSError) as exc:
        return outputs + [Markdown(f"Unable to load scenario evidence helpers: {exc}")]
    frames = []
    for path in paths:
        label = relative_label(path, root)
        if not load_json_object(path):
            outputs.append(
                Markdown(f"Unable to read a scenario summary from `{label}`.")
            )
            continue
        try:
            # No automatic baseline or candidate: comparison is recorded evidence.
            frames.append(
                evidence.build_comparison_frame({label: path}, root, baseline_label="")
            )
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            outputs.append(Markdown(f"Unable to compare `{label}`: {exc}"))
    if not frames:
        return outputs
    comparison = pd.concat(frames, ignore_index=True)
    outputs.extend([Markdown("Recorded scenario metrics"), comparison])
    try:
        import plotly.graph_objects as go
    except ImportError:
        return outputs + [
            Markdown(
                "Metrics are shown in the table; install Plotly to display the chart."
            )
        ]
    figure = go.Figure(
        go.Bar(x=comparison["run_label"], y=comparison["pdr"], name="PDR")
    )
    figure.update_layout(
        title="Packet delivery by scenario",
        xaxis_title="Run",
        yaxis_title="Packet delivery ratio",
        template="plotly_white",
    )
    outputs.append(figure)
    return outputs
