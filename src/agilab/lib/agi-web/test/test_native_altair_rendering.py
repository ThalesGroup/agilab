from __future__ import annotations

from importlib.resources import files

from agi_web import python_ui as ui
from agi_web.python_view_session import ViewSession


def test_altair_chart_sends_specification_and_session_owned_local_runtime():
    specification = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "data": {"values": [{"hour": 0, "demand": 3.5}, {"hour": 1, "demand": 4.25}]},
        "mark": "line",
        "encoding": {"x": {"field": "hour", "type": "ordinal"}, "y": {"field": "demand", "type": "quantitative"}},
    }

    class Chart:
        def to_dict(self):
            return specification

        def to_html(self):
            raise AssertionError("Altair HTML may load a CDN and must not be used.")

    session = ViewSession(lambda: ui.altair_chart(Chart(), width="stretch", key="hourly-demand"))
    payload = session.render()

    assert not payload["error"]
    node = payload["nodes"]["main"][0]
    assert node["kind"] == "altair_chart"
    assert node["props"]["spec"] == specification
    assert node["props"]["width"] == "stretch"
    assert node["props"]["key"] == "hourly-demand"
    assert "body" not in node["props"]
    asset_key = node["props"]["library"].removeprefix("/api/assets/")
    content, mime, _ = session.assets[asset_key]
    assert mime == "text/javascript"
    assert content == files("agi_web").joinpath("react_python_host_assets", "agilab_react_vega.js").read_bytes()
    assert content
    assert asset_key not in ViewSession(lambda: None).assets


def test_altair_chart_accepts_an_inline_vega_lite_mapping():
    specification = {"data": {"values": [{"cost": "Fuel", "value": 8}]}, "mark": "bar"}
    session = ViewSession(lambda: ui.altair_chart(specification))

    payload = session.render()

    assert not payload["error"]
    assert payload["nodes"]["main"][0]["props"]["spec"] == specification
