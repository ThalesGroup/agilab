"""Offline pydeck uses the original renderer with vetted public package assets."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pydeck as pdk
import pytest
from agi_web import python_ui as ui
from agi_web.python_view_session import ViewSession


def test_pydeck_uses_no_external_template_resources_and_preserves_options(monkeypatch):
    chart = pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", data=[{"position": [1, 2], "name": "</script><b>safe</b>"}],
                                     get_position="position", pickable=True)],
                     initial_view_state=pdk.ViewState(longitude=1, latitude=2, zoom=3),
                     map_provider=None, map_style=None, parameters={"depthTest": False},
                     tooltip={"text": "{name}"})
    payload = ViewSession(lambda: ui.pydeck_chart(chart, height=520, use_container_width=True, key="deck")).render()
    assert not payload["error"]
    node = payload["nodes"]["main"][0]
    assert node["kind"] == "html_frame"
    body = node["props"]["body"]
    assert not re.search(r'(?:src|href)=["\x27]https?://', body)
    assert "/assets/pydeck/" in body
    assert "depthTest" in body and "getPosition" in body and "initialViewState" in body
    assert "{name}" in body and "ScatterplotLayer" in body
    assert "</script><b>safe</b>" not in body
    assert node["props"]["height"] == 520
    assert node["props"]["use_container_width"] is True
    assert node["props"]["key"] == "deck"


def test_pydeck_does_not_call_the_cdn_html_template(monkeypatch):
    chart = pdk.Deck(map_provider=None, map_style=None)
    monkeypatch.setattr(chart, "to_html", lambda **kwargs: pytest.fail("CDN template called"))
    payload = ViewSession(lambda: ui.pydeck_chart(chart)).render()
    assert not payload["error"]
    assert payload["nodes"]["main"][0]["kind"] == "html_frame"


def test_unvetted_custom_library_is_visible_and_sanitized(monkeypatch):
    monkeypatch.setattr(pdk.settings, "custom_libraries", [{"libraryName": "Secret", "resourceUri": "https://secret.invalid/key?token=never-print"}])
    payload = ViewSession(lambda: ui.pydeck_chart(pdk.Deck())).render()
    assert not payload["error"]
    node = payload["nodes"]["main"][0]
    assert node["kind"] == "error"
    assert "custom library" in str(node["props"]).lower()
    assert "never-print" not in str(payload)


def test_manifest_validates_all_files_and_rejects_tampering_and_traversal(monkeypatch, tmp_path):
    from agi_web import pydeck_support as support
    original = support.asset_root()
    for item in original.iterdir():
        if item.is_file():
            (tmp_path / item.name).write_bytes(item.read_bytes())
    monkeypatch.setattr(support, "asset_root", lambda: tmp_path)
    manifest = support.load_manifest()
    record = manifest["assets"]["agilab_pydeck.js"]
    url = support.asset_url("agilab_pydeck.js", record)
    assert support.read_public_asset(url)[0]
    for path in ("/assets/pydeck/../python_ui.py", url.replace(record["sha256"], "0" * 64),
                 "/assets/pydeck/" + record["sha256"] + "/unknown.js", url + "/extra"):
        with pytest.raises(support.PydeckRenderError):
            support.read_public_asset(path)
    (tmp_path / "agilab_pydeck.js").write_bytes(b"tampered")
    with pytest.raises(support.PydeckRenderError):
        support.read_public_asset(url)
    payload = ViewSession(lambda: ui.pydeck_chart(pdk.Deck())).render()
    assert payload["nodes"]["main"][0]["kind"] == "error"
    assert "rebuild" in str(payload).lower()


def test_manifest_is_explicitly_included_in_wheel_contract():
    import tomllib
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    patterns = metadata["tool"]["setuptools"]["package-data"]["agi_web"]
    assert "pydeck_assets/*.json" in patterns
    assert "pydeck_assets/*.js" in patterns
    assert "pydeck_assets/*.css" in patterns


def test_explicitly_packaged_custom_library_keeps_its_pydeck_contract(monkeypatch, tmp_path):
    import hashlib
    from agi_web import pydeck_support as support
    root = support.asset_root()
    for item in root.iterdir():
        if item.is_file():
            (tmp_path / item.name).write_bytes(item.read_bytes())
    name = "agilab_pydeck_custom_PublicFixtureLibrary.js"
    content = b"window.PublicFixtureLibrary = {};"
    (tmp_path / name).write_bytes(content)
    path = tmp_path / "agilab_pydeck_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["custom_libraries"]["PublicFixtureLibrary"] = name
    manifest["assets"][name] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "mime": "text/javascript"}
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(support, "asset_root", lambda: tmp_path)
    monkeypatch.setattr(pdk.settings, "custom_libraries", [{"libraryName": "PublicFixtureLibrary", "resourceUri": "agilab-pydeck:PublicFixtureLibrary"}])
    payload = ViewSession(lambda: ui.pydeck_chart(pdk.Deck(map_provider=None))).render()
    assert not payload["error"]
    body = payload["nodes"]["main"][0]["props"]["body"]
    url = support.asset_url(name, manifest["assets"][name])
    assert body.count(url) == 2  # Vetted preload and the unchanged upstream library contract.
    assert support.read_public_asset(url) == (content, "text/javascript")


def test_packaged_worker_contains_its_executable_entrypoint():
    from agi_web import pydeck_support as support
    manifest = support.load_manifest()
    record = manifest["assets"]["agilab_pydeck_maplibre_worker.js"]
    worker, mime = support.read_public_asset(support.asset_url("agilab_pydeck_maplibre_worker.js", record))
    assert worker, "MapLibre worker was removed by bundler sideEffects annotations"
    assert mime == "text/javascript"


def test_manifest_rejects_empty_content_even_when_its_record_matches(monkeypatch, tmp_path):
    import hashlib
    from agi_web import pydeck_support as support
    root = support.asset_root()
    for item in sorted(root.iterdir(), key=lambda item: item.name):
        if item.is_file():
            (tmp_path / item.name).write_bytes(item.read_bytes())
    name = "agilab_pydeck_maplibre_worker.js"
    (tmp_path / name).write_bytes(b"")
    path = tmp_path / "agilab_pydeck_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["assets"][name].update(bytes=0, sha256=hashlib.sha256(b"").hexdigest())
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(support, "asset_root", lambda: tmp_path)
    with pytest.raises(support.PydeckRenderError):
        support.load_manifest()
    payload = ViewSession(lambda: ui.pydeck_chart(pdk.Deck())).render()
    assert payload["nodes"]["main"][0]["kind"] == "error"
    assert "rebuild" in str(payload).lower()
