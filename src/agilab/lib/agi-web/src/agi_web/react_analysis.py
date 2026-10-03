"""Shared React coordinate maps and analysis curves for native Python views and Jupyter.

The component payload stays framework-neutral. React and both host adapters are
bundled in the wheel; Node is needed only to rebuild the frontend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
import math
import hashlib
import base64
from typing import Any, Callable, Sequence

from .component import (
    AgiWebAsset,
    AgiWebComponent,
    AgiWebRendererSpec,
    records_from_data,
)

REACT_ANALYSIS_RENDERERS = frozenset(
    ("agilab-coordinate-map-react-v1", "agilab-analysis-curves-react-v1")
)


def _asset(name: str) -> str:
    return (
        files("agi_web")
        .joinpath("react_analysis_assets", name)
        .read_text(encoding="utf-8")
    )


def _renderer(kind: str) -> AgiWebRendererSpec:
    names = (
        "agilab_react_analysis_streamlit.js",
        "agilab_react_analysis_notebook.js",
        "agilab_react_analysis.css",
    )
    assets = tuple(
        AgiWebAsset(
            asset_id=name,
            kind="css" if name.endswith(".css") else "javascript",
            href=name,
            integrity="sha256-"
            + base64.b64encode(hashlib.sha256(_asset(name).encode()).digest()).decode(),
        )
        for name in names
    )
    return AgiWebRendererSpec(
        renderer_id=f"agilab-{kind}-react-v1",
        technology="react",
        capabilities=(kind, "selection", "offline"),
        assets=assets,
    )


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def coordinate_map_component(
    data: Any,
    *,
    latitude: str = "latitude",
    longitude: str = "longitude",
    label: str | None = None,
    group: str | None = None,
    title: str = "Positions",
    component_id: str = "coordinate-map",
    max_rows: int = 20000,
) -> AgiWebComponent:
    """Build a coordinate plot without external tiles, preserving row identifiers."""
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    records = records_from_data(data)
    points = []
    invalid = 0
    for index, row in enumerate(records):
        lat, lon = _number(row.get(latitude)), _number(row.get(longitude))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            invalid += 1
            continue
        points.append(
            {
                "row": index,
                "latitude": lat,
                "longitude": lon,
                "label": str(row.get(label, index)) if label else str(index),
                "group": str(row.get(group, "Positions")) if group else "Positions",
            }
        )
    omitted = max(len(points) - max_rows, 0)
    return AgiWebComponent(
        component_id=component_id,
        title=title,
        renderer=_renderer("coordinate-map"),
        payload={
            "kind": "coordinate_map",
            "points": points[:max_rows],
            "invalid_rows": invalid,
            "omitted_rows": omitted,
        },
    )


def analysis_curves_component(
    data: Any,
    *,
    x: str,
    series: Sequence[str],
    title: str = "Analysis",
    labels: dict[str, str] | None = None,
    x_label: str = "Date",
    y_label: str = "Value",
    x_type: str = "datetime",
    component_id: str = "analysis-curves",
    max_rows: int = 20000,
) -> AgiWebComponent:
    """Build finite, ordered time/numeric series; missing values break the curve."""
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    if x_type not in ("datetime", "number"):
        raise ValueError("x_type must be datetime or number")
    if not series or len(set(series)) != len(series):
        raise ValueError("series must contain distinct column names")
    records = records_from_data(data)
    rows = []
    invalid = 0
    for index, row in enumerate(records):
        if x_type == "datetime":
            try:
                stamp = datetime.fromisoformat(
                    str(row.get(x, "")).replace("Z", "+00:00")
                )
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                xv = stamp.timestamp() * 1000
            except (ValueError, TypeError, OverflowError, OSError):
                xv = None
        else:
            xv = _number(row.get(x))
        if xv is None or not math.isfinite(xv):
            invalid += 1
            continue
        rows.append(
            {
                "row": index,
                "x": xv,
                "label": str(row.get(x, "")),
                "values": {name: _number(row.get(name)) for name in series},
            }
        )
    rows.sort(key=lambda row: row["x"])
    omitted = max(len(rows) - max_rows, 0)
    return AgiWebComponent(
        component_id=component_id,
        title=title,
        renderer=_renderer("analysis-curves"),
        payload={
            "kind": "analysis_curves",
            "rows": rows[:max_rows],
            "series": [
                {"id": name, "label": (labels or {}).get(name, name)} for name in series
            ],
            "x_type": x_type,
            "x_label": x_label,
            "y_label": y_label,
            "invalid_rows": invalid,
            "omitted_rows": omitted,
        },
    )


@lru_cache(maxsize=8)
def _streamlit_mount(factory: Callable[..., Any], manager_key: Any) -> Any:
    # Lazily register once per host factory, keeping notebook imports UI-free.
    return factory(
        "agilab_react_analysis",
        js=_asset("agilab_react_analysis_streamlit.js"),
        css=_asset("agilab_react_analysis.css"),
        isolate_styles=True,
    )


def render_react_streamlit(
    component: AgiWebComponent,
    streamlit: Any,
    *,
    height: int = 520,
    width: str = "100%",
    key: str | None = None,
) -> Any:
    """Mount through the Python view component protocol and synchronize selection."""
    runtime = getattr(streamlit, "runtime", None)
    factory = streamlit.components.v2.component
    manager_key = (
        runtime.get_instance().bidi_component_registry
        if runtime and runtime.exists()
        else factory
    )
    mount = _streamlit_mount(factory, manager_key)
    data = component.as_dict(include_evidence=True)
    if width != "100%":
        # Keep CSS sizing inside the mounted element.
        # Keep CSS sizing inside the mounted element, as in the static adapter.
        data["render_width"] = width
    return mount(
        data=data,
        height=height,
        width="stretch",
        key=key or component.component_id,
        on_selection_change=lambda: None,
    )


@lru_cache(maxsize=1)
def _notebook_widget_class():
    import anywidget
    import traitlets

    class ReactAnalysisWidget(anywidget.AnyWidget):
        _esm = _asset("agilab_react_analysis_notebook.js")
        _css = _asset("agilab_react_analysis.css")
        component = traitlets.Dict().tag(sync=True)
        selection = traitlets.Dict().tag(sync=True)

    return ReactAnalysisWidget


def render_react_notebook(
    component: AgiWebComponent, *, height: int = 520, width: str = "100%"
) -> Any:
    """Create a Jupyter widget with local assets and a Python-visible selection."""
    widget = _notebook_widget_class()(
        component=component.as_dict(include_evidence=True)
    )
    widget.layout.min_height = f"{max(int(height), 240)}px"
    widget.layout.width = width
    return widget
