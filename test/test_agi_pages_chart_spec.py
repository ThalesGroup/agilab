from __future__ import annotations

import builtins
import dataclasses
import datetime as dt
import decimal
import enum
import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


AGI_PAGES_SRC = Path("src/agilab/lib/agi-pages/src").resolve()


def _load_agi_pages():
    sys.modules.pop("agi_pages.chart_spec", None)
    sys.modules.pop("agi_pages", None)
    sys.path.insert(0, AGI_PAGES_SRC.as_posix())
    try:
        return importlib.import_module("agi_pages")
    finally:
        try:
            sys.path.remove(AGI_PAGES_SRC.as_posix())
        except ValueError:
            pass


def _load_chart_spec_module():
    sys.modules.pop("agi_pages.chart_spec", None)
    sys.modules.pop("agi_pages", None)
    sys.path.insert(0, AGI_PAGES_SRC.as_posix())
    try:
        return importlib.import_module("agi_pages.chart_spec")
    finally:
        try:
            sys.path.remove(AGI_PAGES_SRC.as_posix())
        except ValueError:
            pass


class DataFrameLike:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, *, orient=None):
        assert orient == "records"
        return list(self._rows)


class DataFrameToDictsLike:
    def to_dicts(self):
        return [{"epoch": 1, "score": 0.91}]


class DataFrameNoOrientLike:
    def to_dict(self):
        return {"epoch": [1, 2], "score": [0.91, 0.93]}


class ChartMode(enum.Enum):
    TRAIN = "train"


@dataclasses.dataclass(frozen=True)
class SampleMetadata:
    when: dt.date
    value: decimal.Decimal


class Stringable:
    def __str__(self) -> str:
        return "stringable-value"


def test_agi_pages_builds_deterministic_chart_spec_from_dataframe_like() -> None:
    agi_pages = _load_agi_pages()
    frame = DataFrameLike(
        [
            {"step": "train", "accuracy": 0.84, "loss": 0.31},
            {"step": "test", "accuracy": 0.82, "loss": 0.36},
        ]
    )

    spec = agi_pages.build_chart_spec(
        frame,
        chart_type="line",
        title="Model metrics",
        source="metrics.csv",
        x="step",
        y=["accuracy", "loss"],
        metadata={"run": "demo"},
    )
    repeated = agi_pages.build_chart_spec(
        frame,
        chart_type="line",
        title="Model metrics",
        source="metrics.csv",
        x="step",
        y=["accuracy", "loss"],
        metadata={"run": "demo"},
    )

    assert spec.chart_id == repeated.chart_id
    assert spec.data.columns == ("step", "accuracy", "loss")
    assert spec.option["dataset"]["source"][0] == ["step", "accuracy", "loss"]
    assert [series["name"] for series in spec.option["series"]] == ["accuracy", "loss"]
    assert spec.evidence()["row_count"] == 2
    assert spec.evidence()["columns"] == ["step", "accuracy", "loss"]
    assert spec.evidence()["data_hash"] == repeated.evidence()["data_hash"]
    assert spec.evidence()["option_hash"] == repeated.evidence()["option_hash"]
    assert spec.evidence()["evidence_hash"] == repeated.evidence()["evidence_hash"]


def test_agi_pages_chart_spec_as_dict_controls_data_and_copies_option() -> None:
    agi_pages = _load_agi_pages()
    spec = agi_pages.build_chart_spec(
        [{"x": 1, "y": 2}],
        chart_id="123 custom chart",
        title="Serializable",
        source=Path("reports/chart.html"),
    )

    with_data = spec.as_dict()
    without_data = spec.as_dict(include_data=False)
    with_data["option"]["series"][0]["name"] = "mutated"

    assert with_data["data"]["records"] == [{"x": 1, "y": 2}]
    assert "data" not in without_data
    assert without_data["source"] == "reports/chart.html"
    assert spec.option["series"][0]["name"] == "y"


def test_agi_pages_chart_spec_hash_changes_when_data_changes() -> None:
    agi_pages = _load_agi_pages()

    first = agi_pages.build_chart_spec({"step": ["a"], "value": [1]}, title="Demo")
    second = agi_pages.build_chart_spec({"step": ["a"], "value": [2]}, title="Demo")

    assert first.evidence()["data_hash"] != second.evidence()["data_hash"]
    assert first.evidence()["evidence_hash"] != second.evidence()["evidence_hash"]


def test_agi_pages_chart_data_normalizes_common_input_shapes() -> None:
    agi_pages = _load_agi_pages()

    empty = agi_pages.normalize_chart_data()
    from_empty_mapping = agi_pages.normalize_chart_data({})
    original = agi_pages.normalize_chart_data([{"a": 1}])
    from_chart_data = agi_pages.normalize_chart_data(original)
    from_to_dicts = agi_pages.normalize_chart_data(DataFrameToDictsLike())
    from_to_dict_without_orient = agi_pages.normalize_chart_data(DataFrameNoOrientLike())
    from_row_sequences = agi_pages.normalize_chart_data([(1, 2), 3])
    from_uneven_mapping = agi_pages.normalize_chart_data({"left": [1, 2], "right": [3]})
    from_scalar = agi_pages.normalize_chart_data(7)

    assert empty.columns == ()
    assert from_empty_mapping.records == ()
    assert from_chart_data.records == original.records
    assert from_to_dicts.records == ({"epoch": 1, "score": 0.91},)
    assert from_to_dict_without_orient.records == (
        {"epoch": 1, "score": 0.91},
        {"epoch": 2, "score": 0.93},
    )
    assert from_row_sequences.columns == ("col_0", "col_1", "index", "value")
    assert from_row_sequences.records[1] == {"col_0": None, "col_1": None, "index": 1, "value": 3}
    assert from_uneven_mapping.records == ({"left": [1, 2], "right": [3]},)
    assert from_scalar.records == ({"value": 7},)


def test_agi_pages_option_from_data_covers_empty_invalid_fallback_and_heatmap() -> None:
    agi_pages = _load_agi_pages()

    assert agi_pages.option_from_data([], title="Empty") == {
        "title": {"text": "Empty"},
        "tooltip": {},
        "dataset": {"source": []},
        "xAxis": {},
        "yAxis": {},
        "series": [],
    }
    with pytest.raises(ValueError, match="Unsupported dataset chart type"):
        agi_pages.option_from_data([{"x": 1, "y": 2}], chart_type="pie")

    single_column = agi_pages.option_from_data([{"only": 1}], chart_type="scatter", x="missing", y="missing")
    assert single_column["series"][0]["encode"] == {"x": "only", "y": "only"}

    explicit_heatmap = agi_pages.option_from_data(
        [{"row": "r1", "col": "c1", "score": 3}],
        chart_type="heatmap",
        x="row",
        y=["col", "score"],
    )
    fallback_heatmap = agi_pages.option_from_data(
        [{"row": "r1", "score": 3}],
        chart_type="heatmap",
        x="missing",
        y="missing",
    )
    inferred_heatmap = agi_pages.option_from_data(
        [{"row": "r1", "col": "c1", "score": 3}],
        chart_type="heatmap",
    )

    assert explicit_heatmap["series"][0]["encode"] == {"x": "row", "y": "col", "value": "score"}
    assert fallback_heatmap["series"][0]["encode"] == {"x": "row", "y": "score", "value": "score"}
    assert inferred_heatmap["series"][0]["encode"] == {"x": "row", "y": "col", "value": "score"}


def test_agi_pages_attaches_dataset_to_custom_echarts_option() -> None:
    agi_pages = _load_agi_pages()

    spec = agi_pages.build_chart_spec(
        [{"x": "a", "y": 3}],
        option={"series": [{"type": "bar", "encode": {"x": "x", "y": "y"}}]},
        title="Custom",
    )

    assert spec.option["series"][0]["type"] == "bar"
    assert spec.option["dataset"]["source"] == [["x", "y"], ["a", 3]]


def test_agi_pages_keeps_existing_dataset_on_custom_echarts_option() -> None:
    agi_pages = _load_agi_pages()

    spec = agi_pages.build_chart_spec(
        [{"x": "a", "y": 3}],
        option={"dataset": {"source": [["x", "y"], ["preset", 9]]}, "series": [{"type": "bar"}]},
    )

    assert spec.option["dataset"]["source"] == [["x", "y"], ["preset", 9]]


def test_agi_pages_static_html_embeds_option_and_escaped_evidence() -> None:
    agi_pages = _load_agi_pages()
    spec = agi_pages.build_chart_spec(
        [{"label": "</script><b>x</b>", "value": 1}],
        chart_type="bar",
        title="Unsafe label",
    )

    html = agi_pages.chart_spec_to_static_html(spec, height=240)

    assert f'id="{spec.chart_id}"' in html
    assert "data-agilab-chart-evidence=" in html
    assert "window.echarts.init" in html
    assert "<\\/script" in html
    assert "</script><b>x</b>" not in html


def test_agi_pages_static_html_clamps_height_and_sanitizes_identifier() -> None:
    agi_pages = _load_agi_pages()
    spec = agi_pages.build_chart_spec([{"x": "a", "y": 1}], chart_id="123 odd id", title="Identifier")

    html = agi_pages.chart_spec_to_static_html(spec, height=10, width="80%")

    assert "height:120px" in html
    assert "width:80%" in html
    assert "agilabChartOption_chart_123_odd_id" in html


def test_agi_pages_render_streamlit_uses_component_html() -> None:
    agi_pages = _load_agi_pages()
    spec = agi_pages.build_chart_spec([{"x": "a", "y": 1}], title="Streamlit")
    calls = []

    def _html(fragment, *, height, scrolling):
        calls.append({"fragment": fragment, "height": height, "scrolling": scrolling})
        return "component-result"

    fake_streamlit = SimpleNamespace(components=SimpleNamespace(v1=SimpleNamespace(html=_html)))

    result = agi_pages.render_streamlit(spec, fake_streamlit, height=300)

    assert result == "component-result"
    assert calls[0]["height"] == 300
    assert calls[0]["scrolling"] is False
    assert spec.chart_id in calls[0]["fragment"]


def test_agi_pages_render_streamlit_imports_streamlit_when_not_injected(monkeypatch) -> None:
    agi_pages = _load_agi_pages()
    spec = agi_pages.build_chart_spec([{"x": "a", "y": 1}], title="Streamlit import")
    calls = []

    def _html(fragment, *, height, scrolling):
        calls.append({"fragment": fragment, "height": height, "scrolling": scrolling})
        return "imported-component"

    fake_streamlit = ModuleType("streamlit")
    fake_streamlit.components = SimpleNamespace(v1=SimpleNamespace(html=_html))
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    assert agi_pages.render_streamlit(spec, height=280) == "imported-component"
    assert calls[0]["height"] == 280


def test_agi_pages_render_notebook_returns_html_object_when_ipython_exists(monkeypatch) -> None:
    agi_pages = _load_agi_pages()
    spec = agi_pages.build_chart_spec([{"x": "a", "y": 1}], title="Notebook")

    fake_ipython = ModuleType("IPython")
    fake_display = ModuleType("IPython.display")
    fake_display.HTML = lambda fragment: {"html": fragment}
    monkeypatch.setitem(sys.modules, "IPython", fake_ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", fake_display)

    rendered = agi_pages.render_notebook(spec, height=260)

    assert rendered["html"].count(spec.chart_id) >= 1
    assert "height:260px" in rendered["html"]


def test_agi_pages_render_notebook_falls_back_to_html_string(monkeypatch) -> None:
    agi_pages = _load_agi_pages()
    spec = agi_pages.build_chart_spec([{"x": "a", "y": 1}], title="Notebook fallback")
    original_import = builtins.__import__

    def _raise_for_ipython(name, *args, **kwargs):
        if name == "IPython.display":
            raise ImportError("blocked for fallback test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raise_for_ipython)

    rendered = agi_pages.render_notebook(spec, height=260)

    assert isinstance(rendered, str)
    assert spec.chart_id in rendered


def test_agi_pages_normalize_json_value_covers_supported_types() -> None:
    chart_spec = _load_chart_spec_module()
    identifier = uuid.UUID("12345678-1234-5678-1234-567812345678")
    payload = {
        "decimal_int": decimal.Decimal("2"),
        "decimal_float": decimal.Decimal("2.5"),
        "decimal_nan": decimal.Decimal("NaN"),
        "date": dt.date(2026, 5, 21),
        "datetime": dt.datetime(2026, 5, 21, 8, 30),
        "time": dt.time(8, 30),
        "enum": ChartMode.TRAIN,
        "path": Path("reports/chart.html"),
        "uuid": identifier,
        "dataclass": SampleMetadata(dt.date(2026, 5, 20), decimal.Decimal("4.5")),
        "bytes": b"\x00\x0f",
        "memoryview": memoryview(b"\x01\x02"),
        "sequence": (1, float("nan")),
        "fallback": Stringable(),
    }

    normalized = chart_spec.normalize_json_value(payload)
    canonical = chart_spec.to_canonical_json({"b": 1, "a": 2})

    assert normalized["decimal_int"] == 2
    assert normalized["decimal_float"] == 2.5
    assert normalized["decimal_nan"] is None
    assert normalized["date"] == "2026-05-21"
    assert normalized["datetime"] == "2026-05-21T08:30:00"
    assert normalized["time"] == "08:30:00"
    assert normalized["enum"] == "train"
    assert normalized["path"] == "reports/chart.html"
    assert normalized["uuid"] == str(identifier)
    assert normalized["dataclass"] == {"value": 4.5, "when": "2026-05-20"}
    assert normalized["bytes"] == "000f"
    assert normalized["memoryview"] == "0102"
    assert normalized["sequence"] == [1, None]
    assert normalized["fallback"] == "stringable-value"
    assert canonical == '{"a":2,"b":1}'


def test_agi_pages_exported_api_exposes_chart_contract() -> None:
    agi_pages = _load_agi_pages()

    assert agi_pages.CHART_SPEC_SCHEMA == "agilab.agi_pages.chart_spec.v1"
    assert dataclasses.is_dataclass(agi_pages.ChartSpec)
    assert callable(agi_pages.build_chart_spec)
    assert callable(agi_pages.render_notebook)
