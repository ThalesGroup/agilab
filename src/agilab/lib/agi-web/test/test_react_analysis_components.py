"""Contract and host integration checks for the two shared React views."""

from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from agi_web import (
    analysis_curves_component,
    coordinate_map_component,
    render_notebook,
    render_streamlit,
)
from agi_web.react_analysis import _asset, _streamlit_mount


def test_coordinate_map_preserves_labels_and_excludes_invalid_positions():
    component = coordinate_map_component(
        [
            {"lat": 48, "lon": 2, "id": "001", "flight": "A"},
            {"lat": 91, "lon": 2, "id": "bad"},
            {"lat": float("nan"), "lon": 2},
            {"lat": 49, "lon": 181},
            {"lat": -90, "lon": -180, "id": "<script>", "flight": ""},
        ],
        latitude="lat",
        longitude="lon",
        label="id",
        group="flight",
    )
    assert component.payload["points"] == [
        {"row": 0, "latitude": 48.0, "longitude": 2.0, "label": "001", "group": "A"},
        {
            "row": 4,
            "latitude": -90.0,
            "longitude": -180.0,
            "label": "<script>",
            "group": "",
        },
    ]
    assert component.payload["invalid_rows"] == 3


def test_curves_order_utc_dates_and_keep_missing_values_as_gaps():
    component = analysis_curves_component(
        [
            {"date": "2026-01-02T00:00:00Z", "actual": 12, "predicted": float("inf")},
            {"date": "2026-01-01T01:00:00+01:00", "actual": 10, "predicted": 11},
            {"date": "invalid", "actual": 99, "predicted": 99},
        ],
        x="date",
        series=("actual", "predicted"),
    )
    rows = component.payload["rows"]
    assert [row["row"] for row in rows] == [1, 0]
    assert rows[1]["x"] - rows[0]["x"] == 24 * 60 * 60 * 1000
    assert rows[1]["values"] == {"actual": 12.0, "predicted": None}
    assert component.payload["invalid_rows"] == 1
    json.dumps(component.as_dict(), allow_nan=False)


@pytest.mark.parametrize(
    "builder,data,options,key",
    [
        (
            coordinate_map_component,
            [{"latitude": i, "longitude": i} for i in range(4)],
            {},
            "points",
        ),
        (
            analysis_curves_component,
            [{"x": i, "y": i} for i in range(4)],
            {"x": "x", "series": ("y",), "x_type": "number"},
            "rows",
        ),
    ],
)
def test_chart_limits_are_reported(builder, data, options, key):
    component = builder(data, max_rows=2, **options)
    assert len(component.payload[key]) == 2
    assert component.payload["omitted_rows"] == 2
    with pytest.raises(ValueError, match="positive"):
        builder(data, max_rows=0, **options)


def test_numeric_curves_and_empty_inputs():
    component = analysis_curves_component(
        [
            {"x": 2, "y": 2},
            {"x": None, "y": 8},
            {"x": 1, "y": None},
        ],
        x="x",
        series=("y",),
        x_type="number",
    )
    assert [row["x"] for row in component.payload["rows"]] == [1, 2]
    assert coordinate_map_component([]).payload["points"] == []
    assert analysis_curves_component([], x="x", series=("y",)).payload["rows"] == []


@pytest.mark.parametrize(
    "options",
    [{"series": ()}, {"series": ("y", "y")}, {"series": ("y",), "x_type": "other"}],
)
def test_invalid_curve_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        analysis_curves_component([], x="x", **options)


def test_bundled_assets_have_actual_sri_hashes():
    component = coordinate_map_component([])
    assert component.renderer.technology == "react"
    for asset in component.renderer.assets:
        contents = _asset(asset.href)
        expected = base64.b64encode(hashlib.sha256(contents.encode()).digest()).decode()
        assert asset.integrity == "sha256-" + expected
        assert not asset.href.startswith(("http:", "https:"))


def test_notebook_widget_exposes_component_and_selection():
    pytest.importorskip("anywidget")
    component = coordinate_map_component([{"latitude": 48, "longitude": 2}])
    widget = render_notebook(component)
    try:
        assert widget.component == component.as_dict(include_evidence=True)
        assert widget.selection == {}
        widget.selection = {"row": 0, "latitude": 48, "longitude": 2}
        assert widget.get_state()["selection"]["row"] == 0
    finally:
        widget.close()


@pytest.mark.parametrize("width", ["100%", "320px", "65%", "calc(100% - 2rem)"])
def test_notebook_preserves_css_width(width):
    pytest.importorskip("anywidget")
    widget = render_notebook(coordinate_map_component([]), width=width)
    try:
        assert widget.layout.width == width
    finally:
        widget.close()


@pytest.mark.parametrize("width", ["100%", "320px", "65%", "calc(100% - 2rem)"])
def test_streamlit_css_width_respects_v2_layout_contract(width):
    pytest.importorskip("streamlit")
    from streamlit.elements.lib.layout_utils import validate_width

    mounted = []

    def factory(_name, **_assets):
        def mount(**arguments):
            validate_width(arguments["width"])
            mounted.append(arguments)
            return SimpleNamespace(selection={})

        return mount

    host = SimpleNamespace(
        components=SimpleNamespace(v2=SimpleNamespace(component=factory))
    )
    component = coordinate_map_component([])
    try:
        render_streamlit(component, streamlit=host, width=width)
        assert mounted[0]["data"].get("render_width", "100%") == width
        assert mounted[0]["data"]["evidence"] == component.as_dict()["evidence"]
    finally:
        _streamlit_mount.cache_clear()


def test_streamlit_v2_registration_tracks_each_runtime():
    registered, mounted = [], []

    def factory(name, **assets):
        registered.append((name, assets))

        def mount(**arguments):
            mounted.append(arguments)
            return SimpleNamespace(selection={"row": 0})

        return mount

    runtime = SimpleNamespace(
        exists=lambda: True,
        get_instance=lambda: SimpleNamespace(bidi_component_registry=manager[0]),
    )
    fake = SimpleNamespace(
        components=SimpleNamespace(v2=SimpleNamespace(component=factory)),
        runtime=runtime,
    )
    manager = [object()]
    _streamlit_mount.cache_clear()
    component = coordinate_map_component([])
    try:
        assert render_streamlit(component, streamlit=fake).selection == {"row": 0}
        render_streamlit(component, streamlit=fake)
        manager[0] = object()
        render_streamlit(component, streamlit=fake)
        assert len(registered) == 2
        assert all(assets["isolate_styles"] for _, assets in registered)
        assert mounted[-1]["data"] == component.as_dict(include_evidence=True)
    finally:
        _streamlit_mount.cache_clear()
