# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Notebook positions from exported CSV/Parquet/JSON datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import Markdown

from agi_pages.runtime import discover_files, relative_label


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
    files = sorted(
        set(
            discover_files(root, "**/*.csv")
            + discover_files(root, "**/*.parquet")
            + discover_files(root, "**/*.json")
        )
    )
    found = False
    for path in files:
        label = relative_label(path, root)
        try:
            if path.suffix == ".parquet":
                frame = pd.read_parquet(path)
            elif path.suffix == ".json":
                frame = pd.read_json(path, dtype={"plane_id": str, "node_id": str})
            else:
                frame = pd.read_csv(path, dtype={"plane_id": str, "node_id": str})
            columns = {str(column).strip().lower(): column for column in frame.columns}
            lat = next(
                (columns[key] for key in ("latitude", "lat") if key in columns), None
            )
            lon = next(
                (
                    columns[key]
                    for key in ("longitude", "lon", "long", "lng")
                    if key in columns
                ),
                None,
            )
            if lat is None or lon is None:
                continue
            found = True
            latitude = pd.to_numeric(frame[lat], errors="coerce")
            longitude = pd.to_numeric(frame[lon], errors="coerce")
            valid = latitude.between(-90, 90) & longitude.between(-180, 180)
            invalid = int((~valid).sum())
            outputs.append(Markdown(f"**{label}** — {int(valid.sum())} positions."))
            if invalid:
                outputs.append(
                    Markdown(
                        f"{invalid} invalid coordinate rows omitted (latitude/longitude ranges)."
                    )
                )
            points = frame.loc[valid].copy()
            points[lat], points[lon] = latitude[valid], longitude[valid]
            if points.empty:
                outputs.append(Markdown(f"No valid coordinates in `{label}`."))
                continue
            # Bound notebook output while preserving the full dataset on disk.
            outputs.append(points.head(1000))
            if len(points) > 1000:
                outputs.append(
                    Markdown(
                        f"Table shows the first 1000 of {len(points)} valid positions."
                    )
                )
            try:
                from agi_web import coordinate_map_component, render_notebook
                component = coordinate_map_component(
                    points, latitude=lat, longitude=lon,
                    label="plane_id" if "plane_id" in points else None,
                    group="plane_id" if "plane_id" in points else None,
                    title=f"Positions — {label}", component_id=f"{page}-{label}",
                )
                outputs.append(render_notebook(component))
                continue
            except (ImportError, OSError) as exc:
                outputs.append(Markdown(f"React widget unavailable: {exc}. Showing the standalone chart when possible."))
            try:
                import plotly.graph_objects as go
            except ImportError:
                outputs.append(
                    Markdown(
                        "Positions are shown in the table; install Plotly to display the chart."
                    )
                )
                continue
            plotted = points.iloc[:20000]
            if len(points) > len(plotted):
                outputs.append(
                    Markdown(
                        f"Chart shows the first {len(plotted)} of {len(points)} valid positions."
                    )
                )
            figure = go.Figure(
                go.Scatter(
                    x=plotted[lon],
                    y=plotted[lat],
                    mode="markers",
                    text=plotted["plane_id"] if "plane_id" in plotted else None,
                )
            )
            figure.update_layout(
                title=f"Positions — {label}",
                xaxis_title="Longitude (degrees)",
                yaxis_title="Latitude (degrees)",
                template="plotly_white",
            )
            outputs.append(figure)
        except (OSError, ValueError, TypeError, ImportError) as exc:
            outputs.append(Markdown(f"Unable to read `{label}`: {exc}"))
    if not found:
        outputs.append(
            Markdown("No exported datasets with latitude/longitude columns were found.")
        )
    return outputs
