"""Vetted public pydeck assets and an opaque-origin, CDN-free HTML adapter."""
from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path

_BUNDLE_ERROR = "Pydeck renderer assets are missing or invalid. Rebuild agi-web frontend assets and reinstall its wheel."
_CUSTOM_ERROR = "This pydeck custom library is not packaged. Add it to the frontend's agilabPydeckCustomLibraries build inputs and use its agilab-pydeck:<libraryName> URI."
_REQUIRED = {"agilab_pydeck.js", "agilab_pydeck_bootstrap.js", "agilab_pydeck_maplibre_worker.js", "agilab_pydeck.css", "agilab_pydeck.LICENSE.txt"}
_ROUTE = re.compile(r"/assets/pydeck/([0-9a-f]{64})/([A-Za-z0-9_.-]+)\Z")


class PydeckRenderError(ValueError):
    """An actionable message that never includes chart data or credentials."""


def asset_root():
    return files("agi_web").joinpath("pydeck_assets")


def _asset_bytes(root, name):
    asset = root.joinpath(name)
    if isinstance(asset, Path) and asset.is_symlink():
        raise PydeckRenderError(_BUNDLE_ERROR)
    return asset.read_bytes()


def load_manifest():
    """Validate the exact allowlist and payload; no chart/session asset is public."""
    try:
        root = asset_root()
        raw = _asset_bytes(root, "agilab_pydeck_manifest.json")
        if len(raw) > 128 * 1024:
            raise ValueError
        manifest = json.loads(raw)
        if manifest["schema"] != "agilab.pydeck_assets.v1":
            raise ValueError
        records = manifest["assets"]
        custom = manifest["custom_libraries"]
        if not isinstance(custom, dict) or len(custom) > 32:
            raise ValueError
        allowed = set(_REQUIRED)
        for name, filename in custom.items():
            if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name):
                raise ValueError
            if filename != f"agilab_pydeck_custom_{name}.js":
                raise ValueError
            allowed.add(filename)
        if not isinstance(records, dict) or set(records) != allowed:
            raise ValueError
        for name, record in records.items():
            mime = "text/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "text/plain"
            if record["mime"] != mime or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
                raise ValueError
            data = _asset_bytes(root, name)
            if not data or len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError
        return manifest
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PydeckRenderError(_BUNDLE_ERROR) from exc


def asset_url(name, record):
    return f"/assets/pydeck/{record['sha256']}/{name}"


def read_public_asset(path):
    match = _ROUTE.fullmatch(path)
    if not match:
        raise PydeckRenderError(_BUNDLE_ERROR)
    digest, name = match.groups()
    manifest = load_manifest()
    record = manifest["assets"].get(name)
    if record is None or digest != record["sha256"]:
        raise PydeckRenderError(_BUNDLE_ERROR)
    data = _asset_bytes(asset_root(), name)
    if hashlib.sha256(data).hexdigest() != digest:
        raise PydeckRenderError(_BUNDLE_ERROR)
    return data, record["mime"]


def _script_json(value):
    return json.dumps(value, ensure_ascii=True).replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026")


def pydeck_html(chart):
    from pydeck import settings

    manifest = load_manifest()
    records = manifest["assets"]
    urls = {name: asset_url(name, record) for name, record in records.items()}
    libraries = []
    scripts = []
    for library in settings.custom_libraries or []:
        if not isinstance(library, dict):
            raise PydeckRenderError(_CUSTOM_ERROR)
        name = library.get("libraryName")
        filename = manifest["custom_libraries"].get(name) if isinstance(name, str) else None
        uri = library.get("resourceUri")
        if filename is None or not isinstance(uri, str) or uri not in {f"agilab-pydeck:{name}", urls[filename]}:
            raise PydeckRenderError(_CUSTOM_ERROR)
        libraries.append({**library, "resourceUri": urls[filename]})
        scripts.append(f'<script crossorigin="anonymous" src="{urls[filename]}" onerror="agilabPydeckAssetError()"></script>')
    try:
        specification = json.loads(chart.to_json())
    except (ValueError, TypeError, AttributeError) as exc:
        raise PydeckRenderError("Pydeck chart data could not be serialized. Supply a pydeck Deck with valid JSON layer inputs.") from exc
    options = {
        "jsonInput": specification,
        "tooltip": getattr(chart, "_tooltip", True),
        "customLibraries": libraries,
        "configuration": settings.configuration,
        "mapboxApiKey": getattr(chart, "mapbox_key", None),
        "googleMapsKey": getattr(chart, "google_maps_key", None),
        "maplibreWorkerUrl": urls["agilab_pydeck_maplibre_worker.js"],
        "showError": bool(getattr(chart, "_show_error", False)),
    }
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Pydeck visualization</title>'
        f'<link rel="stylesheet" crossorigin="anonymous" href="{urls["agilab_pydeck.css"]}">'
        '</head><body><div id="agilab-pydeck-status" role="status">Loading visualization…</div>'
        '<div id="deck-container"></div>'
        '<script>function agilabPydeckAssetError(){const s=document.getElementById("agilab-pydeck-status");'
        's.hidden=false;s.setAttribute("role","alert");s.textContent="Pydeck renderer could not load. Rebuild agi-web frontend assets and reinstall its wheel.";}</script>'
        f'<script crossorigin="anonymous" src="{urls["agilab_pydeck.js"]}" onerror="agilabPydeckAssetError()"></script>'
        + "".join(scripts)
        + '<script type="module">'
        + f'import("{urls["agilab_pydeck_bootstrap.js"]}").then(({{mountPydeck}})=>mountPydeck({_script_json(options)})).catch(agilabPydeckAssetError);'
        + '</script></body></html>'
    )
