# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Render paired forecast metrics and predictions inside the exported notebook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import Markdown

from agi_pages.runtime import discover_files, load_json_object, relative_label

import math


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
    metrics_files = discover_files(root, "**/forecast_metrics.json")
    if not metrics_files:
        return outputs + [
            Markdown("No forecast metrics were found in the exported artifacts.")
        ]
    for path in metrics_files:
        label = relative_label(path, root)
        metrics = load_json_object(path)
        if not metrics:
            outputs.append(Markdown(f"Unable to read a metrics object from `{label}`."))
            continue
        predictions_path = path.with_name("forecast_predictions.csv")
        if not predictions_path.is_file():
            outputs.append(
                Markdown(
                    f"Missing predictions paired with `{label}`: `forecast_predictions.csv`."
                )
            )
            continue
        try:
            frame = pd.read_csv(predictions_path, converters={"run_id": str})
            if "date" not in frame and "ds" in frame:
                frame = frame.rename(columns={"ds": "date"})
            required = {"date", "y_true", "y_pred"}
            if frame.empty or not required.issubset(frame.columns):
                raise ValueError(
                    "predictions require nonempty date/ds, y_true and y_pred columns"
                )
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            if frame["date"].isna().any():
                raise ValueError("predictions contain invalid dates")
            for column in ("y_true", "y_pred"):
                frame[column] = pd.to_numeric(frame[column], errors="raise")
                if not frame[column].map(math.isfinite).all():
                    raise ValueError(f"predictions contain non-finite {column} values")
            if metrics.get("run_id") is not None and "run_id" in frame:
                if not frame["run_id"].eq(str(metrics["run_id"])).all():
                    raise ValueError(
                        "prediction run_id does not match its metrics run_id"
                    )
            frame = frame.sort_values("date")
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            outputs.append(Markdown(f"Unable to render `{label}`: {exc}"))
            continue
        outputs.extend(
            [Markdown(f"**{label}**"), pd.json_normalize(metrics), frame.head(1000)]
        )
        if len(frame) > 1000:
            outputs.append(
                Markdown(f"Prediction table shows the first 1000 of {len(frame)} rows.")
            )
        try:
            import plotly.graph_objects as go
        except ImportError:
            outputs.append(
                Markdown(
                    "Predictions are shown in the table; install Plotly to display the chart."
                )
            )
            continue
        figure = go.Figure()
        figure.add_scatter(
            x=frame["date"], y=frame["y_true"], name="Observed", mode="lines"
        )
        figure.add_scatter(
            x=frame["date"], y=frame["y_pred"], name="Predicted", mode="lines"
        )
        figure.update_layout(
            title=f"Forecast — {label}",
            xaxis_title="Date",
            yaxis_title=str(metrics.get("target") or "Value"),
            template="plotly_white",
        )
        outputs.append(figure)
    return outputs
