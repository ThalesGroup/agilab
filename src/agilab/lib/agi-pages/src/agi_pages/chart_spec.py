"""Small, deterministic chart-spec contract for AGILAB page bundles.

The module intentionally does not depend on pandas, Streamlit, IPython, or
ECharts at import time. Page bundles can pass a pandas-like dataframe, records,
or a mapping of columns, then render the same specification in Streamlit,
notebooks, or static proof artifacts.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as _dt
import decimal
import enum
import hashlib
import html
import json
import math
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

CHART_SPEC_SCHEMA = "agilab.agi_pages.chart_spec.v1"
CHART_EVIDENCE_SCHEMA = "agilab.agi_pages.chart_evidence.v1"
DEFAULT_ECHARTS_SCRIPT_URL = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"
SUPPORTED_DATASET_CHART_TYPES = ("line", "bar", "scatter", "heatmap")
_SCRIPT_END_REPLACEMENT = "<\\/script"

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclasses.dataclass(frozen=True, slots=True)
class ChartData:
    """Normalized table payload used by one chart spec."""

    columns: tuple[str, ...]
    records: tuple[dict[str, JsonValue], ...]

    @property
    def row_count(self) -> int:
        return len(self.records)

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "columns": list(self.columns),
            "records": [dict(record) for record in self.records],
        }


@dataclasses.dataclass(frozen=True, slots=True)
class ChartSpec:
    """Portable ECharts-compatible chart specification."""

    chart_id: str
    option: dict[str, JsonValue]
    data: ChartData
    title: str = ""
    source: str = ""
    metadata: dict[str, JsonValue] = dataclasses.field(default_factory=dict)
    renderer: str = "echarts"
    schema: str = CHART_SPEC_SCHEMA

    def data_hash(self) -> str:
        return stable_sha256(self.data.as_dict())

    def option_hash(self) -> str:
        return stable_sha256(self.option)

    def evidence(self) -> dict[str, JsonValue]:
        payload = {
            "schema": CHART_EVIDENCE_SCHEMA,
            "chart_id": self.chart_id,
            "title": self.title,
            "source": self.source,
            "renderer": self.renderer,
            "row_count": self.data.row_count,
            "columns": list(self.data.columns),
            "data_hash": self.data_hash(),
            "option_hash": self.option_hash(),
            "metadata": dict(self.metadata),
        }
        payload["evidence_hash"] = stable_sha256(payload)
        return payload

    def as_dict(self, *, include_data: bool = True) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "schema": self.schema,
            "chart_id": self.chart_id,
            "title": self.title,
            "source": self.source,
            "renderer": self.renderer,
            "option": copy.deepcopy(self.option),
            "evidence": self.evidence(),
        }
        if include_data:
            payload["data"] = self.data.as_dict()
        return payload


def build_chart_spec(
    data: Any = None,
    *,
    option: Mapping[str, Any] | None = None,
    chart_type: str = "line",
    chart_id: str | None = None,
    title: str = "",
    source: str | Path = "",
    metadata: Mapping[str, Any] | None = None,
    x: str | None = None,
    y: str | Sequence[str] | None = None,
) -> ChartSpec:
    """Build a portable chart spec from dataframe-like data and an ECharts option."""

    chart_data = normalize_chart_data(data)
    normalized_option = normalize_json_value(option) if option is not None else None
    if not isinstance(normalized_option, dict):
        normalized_option = option_from_data(chart_data, chart_type=chart_type, title=title, x=x, y=y)
    elif chart_data.records and "dataset" not in normalized_option:
        normalized_option = {
            **normalized_option,
            "dataset": _echarts_dataset(chart_data),
        }

    normalized_metadata = normalize_json_value(dict(metadata or {}))
    if not isinstance(normalized_metadata, dict):
        normalized_metadata = {}
    option_hash = stable_sha256(normalized_option)
    data_hash = stable_sha256(chart_data.as_dict())
    final_chart_id = normalize_chart_id(chart_id or title, data_hash=data_hash, option_hash=option_hash)
    return ChartSpec(
        chart_id=final_chart_id,
        title=str(title or ""),
        source=Path(source).as_posix() if isinstance(source, Path) else str(source or ""),
        data=chart_data,
        option=normalized_option,
        metadata=normalized_metadata,
    )


def normalize_chart_data(data: Any = None) -> ChartData:
    """Normalize dataframe-like input into deterministic records and columns."""

    records = [_normalize_record(record) for record in _records_from_data(data)]
    columns = _columns_from_records(records)
    normalized_records = tuple({column: record.get(column) for column in columns} for record in records)
    return ChartData(columns=columns, records=normalized_records)


def option_from_data(
    data: ChartData | Any,
    *,
    chart_type: str = "line",
    title: str = "",
    x: str | None = None,
    y: str | Sequence[str] | None = None,
) -> dict[str, JsonValue]:
    """Return a compact ECharts option for common dataframe chart shapes."""

    chart_data = data if isinstance(data, ChartData) else normalize_chart_data(data)
    chart_type = str(chart_type or "line").strip().lower()
    if chart_type not in SUPPORTED_DATASET_CHART_TYPES:
        raise ValueError(f"Unsupported dataset chart type: {chart_type}")
    if not chart_data.columns:
        return _empty_option(title=title)

    if chart_type == "heatmap":
        x_column, y_column, value_column = _resolve_heatmap_columns(chart_data, x=x, y=y)
        return {
            "title": {"text": title} if title else {},
            "tooltip": {"position": "top"},
            "dataset": _echarts_dataset(chart_data),
            "xAxis": {"type": "category"},
            "yAxis": {"type": "category"},
            "visualMap": {"calculable": True, "orient": "horizontal", "left": "center"},
            "series": [
                {
                    "type": "heatmap",
                    "encode": {"x": x_column, "y": y_column, "value": value_column},
                    "name": value_column,
                }
            ],
        }

    x_column = _resolve_x_column(chart_data, x=x)
    y_columns = _resolve_y_columns(chart_data, x_column=x_column, y=y)
    series = [
        {
            "type": chart_type,
            "name": y_column,
            "encode": {"x": x_column, "y": y_column},
        }
        for y_column in y_columns
    ]
    return {
        "title": {"text": title} if title else {},
        "tooltip": {"trigger": "axis" if chart_type in {"line", "bar"} else "item"},
        "legend": {"show": len(series) > 1},
        "dataset": _echarts_dataset(chart_data),
        "xAxis": {"type": "category" if chart_type in {"line", "bar"} else "value"},
        "yAxis": {"type": "value"},
        "series": series,
    }


def chart_spec_to_static_html(
    spec: ChartSpec,
    *,
    height: int = 420,
    width: str = "100%",
    echarts_script_url: str = DEFAULT_ECHARTS_SCRIPT_URL,
) -> str:
    """Render a chart spec as a standalone HTML fragment."""

    option_json = _json_for_script(spec.option)
    evidence_json = html.escape(to_canonical_json(spec.evidence()), quote=True)
    div_id = html.escape(spec.chart_id, quote=True)
    width_css = html.escape(str(width), quote=True)
    height_css = max(int(height), 120)
    script_url = html.escape(str(echarts_script_url), quote=True)
    return "\n".join(
        [
            f'<div id="{div_id}" data-agilab-chart-evidence="{evidence_json}" '
            f'style="width:{width_css};height:{height_css}px"></div>',
            f'<script src="{script_url}"></script>',
            "<script>",
            f"const agilabChartOption_{_js_identifier(spec.chart_id)} = {option_json};",
            f"const agilabChartElement_{_js_identifier(spec.chart_id)} = document.getElementById({json.dumps(spec.chart_id)});",
            f"if (window.echarts && agilabChartElement_{_js_identifier(spec.chart_id)}) {{",
            f"  const chart = window.echarts.init(agilabChartElement_{_js_identifier(spec.chart_id)});",
            f"  chart.setOption(agilabChartOption_{_js_identifier(spec.chart_id)});",
            "}",
            "</script>",
        ]
    )


def render_streamlit(
    spec: ChartSpec,
    streamlit: Any | None = None,
    *,
    height: int = 420,
    width: str = "100%",
) -> Any:
    """Render the chart in Streamlit using ``st.components.v1.html``."""

    st = streamlit
    if st is None:
        import streamlit as st  # type: ignore[no-redef]

    fragment = chart_spec_to_static_html(spec, height=height, width=width)
    return st.components.v1.html(fragment, height=height, scrolling=False)


def render_notebook(
    spec: ChartSpec,
    *,
    height: int = 420,
    width: str = "100%",
) -> Any:
    """Return an IPython HTML object when available, otherwise a HTML string."""

    fragment = chart_spec_to_static_html(spec, height=height, width=width)
    try:
        from IPython.display import HTML
    except Exception:
        return fragment
    return HTML(fragment)


def stable_sha256(value: Any) -> str:
    """Hash a JSON-compatible payload with deterministic formatting."""

    return hashlib.sha256(to_canonical_json(value).encode("utf-8")).hexdigest()


def to_canonical_json(value: Any) -> str:
    return json.dumps(normalize_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_json_value(value: Any) -> JsonValue:
    """Convert common dataframe values into JSON-compatible deterministic values."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        if value.is_finite():
            return int(value) if value == value.to_integral_value() else float(value)
        return None
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return normalize_json_value(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, uuid.UUID):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return normalize_json_value(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): normalize_json_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return value.hex()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_json_value(item) for item in value]
    return str(value)


def normalize_chart_id(value: str | None, *, data_hash: str, option_hash: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    if not stem:
        stem = "chart"
    return f"{stem}-{stable_sha256({'data_hash': data_hash, 'option_hash': option_hash})[:12]}"


def _records_from_data(data: Any) -> list[Mapping[str, Any]]:
    if data is None:
        return []
    if isinstance(data, ChartData):
        return list(data.records)
    to_dicts = getattr(data, "to_dicts", None)
    if callable(to_dicts):
        return _records_from_data(to_dicts())
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):
        try:
            return _records_from_data(to_dict(orient="records"))
        except TypeError:
            return _records_from_data(to_dict())
    if isinstance(data, Mapping):
        return _records_from_mapping(data)
    if isinstance(data, Iterable) and not isinstance(data, (str, bytes, bytearray)):
        records: list[Mapping[str, Any]] = []
        for index, item in enumerate(data):
            if isinstance(item, Mapping):
                records.append(item)
            elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
                records.append({f"col_{col_index}": value for col_index, value in enumerate(item)})
            else:
                records.append({"index": index, "value": item})
        return records
    return [{"value": data}]


def _records_from_mapping(data: Mapping[Any, Any]) -> list[Mapping[str, Any]]:
    if not data:
        return []
    values = list(data.values())
    if values and all(_is_column_like(value) for value in values):
        lengths = {len(value) for value in values}  # type: ignore[arg-type]
        if len(lengths) == 1:
            length = lengths.pop()
            items = [(str(key), value) for key, value in data.items()]
            return [
                {column: column_values[index] for column, column_values in items}  # type: ignore[index]
                for index in range(length)
            ]
    return [{str(key): value for key, value in data.items()}]


def _is_column_like(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _normalize_record(record: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {str(key): normalize_json_value(value) for key, value in record.items()}


def _columns_from_records(records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    columns: list[str] = []
    seen: set[str] = set()
    for record in records:
        for column in record:
            if column not in seen:
                columns.append(column)
                seen.add(column)
    return tuple(columns)


def _echarts_dataset(data: ChartData) -> dict[str, JsonValue]:
    source: list[JsonValue] = [list(data.columns)]
    for record in data.records:
        source.append([record.get(column) for column in data.columns])
    return {"source": source}


def _empty_option(*, title: str = "") -> dict[str, JsonValue]:
    return {
        "title": {"text": title} if title else {},
        "tooltip": {},
        "dataset": {"source": []},
        "xAxis": {},
        "yAxis": {},
        "series": [],
    }


def _resolve_x_column(data: ChartData, *, x: str | None) -> str:
    if x and x in data.columns:
        return x
    return data.columns[0]


def _resolve_y_columns(data: ChartData, *, x_column: str, y: str | Sequence[str] | None) -> tuple[str, ...]:
    if isinstance(y, str):
        requested = (y,)
    elif y is None:
        requested = tuple(column for column in data.columns if column != x_column)
    else:
        requested = tuple(str(column) for column in y)
    selected = tuple(column for column in requested if column in data.columns and column != x_column)
    if selected:
        return selected
    return tuple(column for column in data.columns if column != x_column)[:1] or (x_column,)


def _resolve_heatmap_columns(data: ChartData, *, x: str | None, y: str | Sequence[str] | None) -> tuple[str, str, str]:
    x_column = _resolve_x_column(data, x=x)
    if isinstance(y, str):
        y_column = y if y in data.columns else data.columns[1 if len(data.columns) > 1 else 0]
        value_column = next((column for column in data.columns if column not in {x_column, y_column}), y_column)
    elif y:
        y_items = [str(column) for column in y]
        y_column = y_items[0] if y_items and y_items[0] in data.columns else data.columns[1 if len(data.columns) > 1 else 0]
        value_column = y_items[1] if len(y_items) > 1 and y_items[1] in data.columns else next(
            (column for column in data.columns if column not in {x_column, y_column}),
            y_column,
        )
    else:
        y_column = data.columns[1 if len(data.columns) > 1 else 0]
        value_column = data.columns[2 if len(data.columns) > 2 else len(data.columns) - 1]
    return x_column, y_column, value_column


def _json_for_script(value: Any) -> str:
    return to_canonical_json(value).replace("</script", _SCRIPT_END_REPLACEMENT)


def _js_identifier(value: str) -> str:
    identifier = re.sub(r"\W+", "_", value)
    if not identifier or identifier[0].isdigit():
        identifier = f"chart_{identifier}"
    return identifier


__all__ = [
    "CHART_EVIDENCE_SCHEMA",
    "CHART_SPEC_SCHEMA",
    "DEFAULT_ECHARTS_SCRIPT_URL",
    "SUPPORTED_DATASET_CHART_TYPES",
    "ChartData",
    "ChartSpec",
    "build_chart_spec",
    "chart_spec_to_static_html",
    "normalize_chart_data",
    "normalize_chart_id",
    "normalize_json_value",
    "option_from_data",
    "render_notebook",
    "render_streamlit",
    "stable_sha256",
    "to_canonical_json",
]
