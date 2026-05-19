from __future__ import annotations

import dataclasses
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


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


class DataFrameLike:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, *, orient=None):
        assert orient == "records"
        return list(self._rows)


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


def test_agi_pages_chart_spec_hash_changes_when_data_changes() -> None:
    agi_pages = _load_agi_pages()

    first = agi_pages.build_chart_spec({"step": ["a"], "value": [1]}, title="Demo")
    second = agi_pages.build_chart_spec({"step": ["a"], "value": [2]}, title="Demo")

    assert first.evidence()["data_hash"] != second.evidence()["data_hash"]
    assert first.evidence()["evidence_hash"] != second.evidence()["evidence_hash"]


def test_agi_pages_attaches_dataset_to_custom_echarts_option() -> None:
    agi_pages = _load_agi_pages()

    spec = agi_pages.build_chart_spec(
        [{"x": "a", "y": 3}],
        option={"series": [{"type": "bar", "encode": {"x": "x", "y": "y"}}]},
        title="Custom",
    )

    assert spec.option["series"][0]["type"] == "bar"
    assert spec.option["dataset"]["source"] == [["x", "y"], ["a", 3]]


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


def test_agi_pages_exported_api_exposes_chart_contract() -> None:
    agi_pages = _load_agi_pages()

    assert agi_pages.CHART_SPEC_SCHEMA == "agilab.agi_pages.chart_spec.v1"
    assert dataclasses.is_dataclass(agi_pages.ChartSpec)
    assert callable(agi_pages.build_chart_spec)
    assert callable(agi_pages.render_notebook)
