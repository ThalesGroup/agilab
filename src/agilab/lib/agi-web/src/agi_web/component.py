"""Framework-neutral web component contract for AGILAB UI islands."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import decimal
import enum
import hashlib
import html
import json
import math
import numbers
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

AGI_WEB_COMPONENT_SCHEMA = "agilab.agi_web.component.v1"
AGI_WEB_EVIDENCE_SCHEMA = "agilab.agi_web.component_evidence.v1"
SUPPORTED_RENDERER_TECHNOLOGIES = ("html", "canvas2d", "react", "webgl", "custom")
_SCRIPT_END_REPLACEMENT = "<\\/script"

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclasses.dataclass(frozen=True, slots=True)
class AgiWebAction:
    """User action exposed by a portable AGILAB web component."""

    action_id: str
    label: str
    kind: str = "emit"
    target: str = ""
    payload: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    style: str = "secondary"

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "action_id": str(self.action_id),
            "label": str(self.label),
            "kind": str(self.kind or "emit"),
            "target": str(self.target or ""),
            "payload": normalize_json_value(dict(self.payload)),
            "style": str(self.style or "secondary"),
        }


@dataclasses.dataclass(frozen=True, slots=True)
class AgiWebAsset:
    """External asset reference required by an adapter-specific renderer."""

    asset_id: str
    kind: str
    href: str
    integrity: str = ""
    mime_type: str = ""

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "asset_id": str(self.asset_id),
            "kind": str(self.kind),
            "href": str(self.href),
            "integrity": str(self.integrity or ""),
            "mime_type": str(self.mime_type or ""),
        }


@dataclasses.dataclass(frozen=True, slots=True)
class AgiWebRendererSpec:
    """Renderer adapter metadata for one component payload contract."""

    renderer_id: str
    technology: str = "html"
    entrypoint: str = ""
    capabilities: Sequence[str] = dataclasses.field(default_factory=tuple)
    assets: Sequence[AgiWebAsset] = dataclasses.field(default_factory=tuple)
    version: str = "1"

    def as_dict(self) -> dict[str, JsonValue]:
        technology = str(self.technology or "html").strip().lower()
        if technology not in SUPPORTED_RENDERER_TECHNOLOGIES:
            technology = "custom"
        return {
            "renderer_id": normalize_component_id(self.renderer_id or "renderer"),
            "technology": technology,
            "entrypoint": str(self.entrypoint or ""),
            "capabilities": [str(capability) for capability in self.capabilities],
            "assets": [asset.as_dict() for asset in self.assets],
            "version": str(self.version or "1"),
        }


@dataclasses.dataclass(frozen=True, slots=True)
class AgiWebComponent:
    """Portable, evidence-backed UI component description."""

    component_id: str
    title: str
    renderer: AgiWebRendererSpec
    payload: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    actions: Sequence[AgiWebAction] = dataclasses.field(default_factory=tuple)
    subtitle: str = ""
    fallback_html: str = ""
    schema: str = AGI_WEB_COMPONENT_SCHEMA

    def evidence(self) -> dict[str, JsonValue]:
        return component_evidence(self)

    def as_dict(self, *, include_evidence: bool = True) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "schema": self.schema,
            "component_id": normalize_component_id(self.component_id),
            "title": str(self.title or ""),
            "subtitle": str(self.subtitle or ""),
            "renderer": self.renderer.as_dict(),
            "payload": normalize_json_value(dict(self.payload)),
            "actions": [action.as_dict() for action in self.actions],
            "fallback_html": str(self.fallback_html or ""),
        }
        if include_evidence:
            payload["evidence"] = self.evidence()
        return payload


def component_evidence(component: AgiWebComponent) -> dict[str, JsonValue]:
    """Return deterministic evidence for a component contract."""

    actions = [action.as_dict() for action in component.actions]
    assets = component.renderer.as_dict().get("assets", [])
    payload = {
        "schema": AGI_WEB_EVIDENCE_SCHEMA,
        "component_id": normalize_component_id(component.component_id),
        "title": str(component.title or ""),
        "renderer": component.renderer.as_dict(),
        "payload_hash": stable_sha256(component.payload),
        "action_hash": stable_sha256(actions),
        "asset_hash": stable_sha256(assets),
        "action_count": len(actions),
        "asset_count": len(assets) if isinstance(assets, list) else 0,
    }
    payload["evidence_hash"] = stable_sha256(payload)
    return payload


def component_to_static_html(
    component: AgiWebComponent,
    *,
    height: int = 520,
    width: str = "100%",
) -> str:
    """Render a component as a standalone static HTML fragment."""

    component_payload = component.as_dict(include_evidence=True)
    component_json = _json_for_script(component_payload)
    evidence_json = html.escape(to_canonical_json(component_payload["evidence"]), quote=True)
    component_id = normalize_component_id(component.component_id)
    container_id = f"agi-web-{component_id}"
    data_id = f"{container_id}-data"
    canvas_id = f"{container_id}-canvas"
    overlay_id = f"{container_id}-overlay"
    fallback = component.fallback_html or "This AGILAB web component requires browser JavaScript for the rich view."
    height_css = max(int(height), 240)
    width_css = html.escape(str(width), quote=True)
    title = html.escape(str(component.title or "AGILAB web component"))
    subtitle = html.escape(str(component.subtitle or "Portable component payload with deterministic evidence."))

    return "\n".join(
        [
            f'<section id="{container_id}" class="agi-web-shell" data-agilab-web-evidence="{evidence_json}" '
            f'style="width:{width_css};min-height:{height_css}px">',
            "<style>",
            _static_css(),
            "</style>",
            '<div class="agi-web-heading">',
            "<div>",
            f"<strong>{title}</strong>",
            f"<span>{subtitle}</span>",
            "</div>",
            '<code class="agi-web-tech"></code>',
            "</div>",
            '<div class="agi-web-layout">',
            '<div class="agi-web-stage">',
            '<div class="agi-web-canvas-wrap" tabindex="0" aria-label="Interactive boundary replay canvas">',
            f'<canvas id="{canvas_id}" class="agi-web-canvas" aria-label="{title}"></canvas>',
            f'<canvas id="{overlay_id}" class="agi-web-overlay" aria-hidden="true"></canvas>',
            '<div class="agi-web-canvas-hud">',
            '<span class="agi-web-live-pill">Evidence replay</span>',
            '<span class="agi-web-confidence-pill">confidence --</span>',
            "</div>",
            '<div class="agi-web-legend" aria-hidden="true">',
            '<span><i class="agi-web-dot agi-web-dot--zero"></i>class 0</span>',
            '<span><i class="agi-web-dot agi-web-dot--one"></i>class 1</span>',
            '<span><i class="agi-web-line"></i>uncertainty</span>',
            "</div>",
            '<div class="agi-web-tooltip" role="status" aria-live="polite" hidden></div>',
            "</div>",
            '<div class="agi-web-timeline" role="tablist" aria-label="Replay timeline"></div>',
            '<div class="agi-web-controls" aria-label="Boundary replay controls">',
            '<button class="agi-web-play" type="button">Play</button>',
            '<label class="agi-web-scrub-label">',
            '<span class="agi-web-frame-label">Frame</span>',
            '<input class="agi-web-scrubber" type="range" min="0" max="0" value="0" step="1">',
            "</label>",
            '<output class="agi-web-frame-count">1/1</output>',
            "</div>",
            '<div class="agi-web-hotkeys">Space plays. Left/right arrows scrub. Hover inspects probability.</div>',
            "</div>",
            '<aside class="agi-web-side">',
            '<div class="agi-web-metrics"></div>',
            '<div class="agi-web-actions"></div>',
            '<div class="agi-web-lessons"></div>',
            "</aside>",
            "</div>",
            f'<noscript><div class="agi-web-fallback">{html.escape(fallback)}</div></noscript>',
            f'<script type="application/json" id="{data_id}">{component_json}</script>',
            "<script>",
            _static_js(container_id=container_id, data_id=data_id, canvas_id=canvas_id, overlay_id=overlay_id),
            "</script>",
            "</section>",
        ]
    )


def render_streamlit(
    component: AgiWebComponent,
    streamlit: Any | None = None,
    *,
    height: int = 520,
    width: str = "100%",
) -> Any:
    """Render a component through ``st.components.v1.html``."""

    st = streamlit
    if st is None:
        import streamlit as st  # type: ignore[no-redef]

    fragment = component_to_static_html(component, height=height, width=width)
    return st.components.v1.html(fragment, height=height, scrolling=False)


def render_notebook(
    component: AgiWebComponent,
    *,
    height: int = 520,
    width: str = "100%",
) -> Any:
    """Return an IPython HTML object when available, otherwise a HTML string."""

    fragment = component_to_static_html(component, height=height, width=width)
    try:
        from IPython.display import HTML
    except Exception:
        return fragment
    return HTML(fragment)


def records_from_data(data: Any = None, *, max_rows: int | None = None) -> list[dict[str, JsonValue]]:
    """Normalize dataframe-like data to deterministic JSON records."""

    records = [_normalize_record(record) for record in _records_from_data(data)]
    if max_rows is not None and max_rows >= 0 and len(records) > max_rows:
        if max_rows == 0:
            return []
        step = max((len(records) - 1) / max(max_rows - 1, 1), 1.0)
        indexes = sorted({min(int(round(index * step)), len(records) - 1) for index in range(max_rows)})
        records = [records[index] for index in indexes]
    columns = _columns_from_records(records)
    return [{column: record.get(column) for column in columns} for record in records]


def stable_sha256(value: Any) -> str:
    """Hash a JSON-compatible payload with deterministic formatting."""

    return hashlib.sha256(to_canonical_json(value).encode("utf-8")).hexdigest()


def to_canonical_json(value: Any) -> str:
    return json.dumps(normalize_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_json_value(value: Any) -> JsonValue:
    """Convert common Python and dataframe scalar values into JSON-compatible values."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        item = float(value)
        return item if math.isfinite(item) else None
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
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return normalize_json_value(item())
        except Exception:
            pass
    return str(value)


def normalize_component_id(value: str | None) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return stem or "component"


def _records_from_data(data: Any) -> list[Mapping[str, Any]]:
    if data is None:
        return []
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
                {key: value[index] for key, value in items}
                for index in range(length)
            ]
    return [data]


def _normalize_record(record: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {str(key): normalize_json_value(value) for key, value in record.items()}


def _columns_from_records(records: Sequence[Mapping[str, JsonValue]]) -> tuple[str, ...]:
    columns: list[str] = []
    for record in records:
        for column in record:
            if column not in columns:
                columns.append(column)
    return tuple(columns)


def _is_column_like(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _json_for_script(value: Any) -> str:
    return to_canonical_json(value).replace("</script", _SCRIPT_END_REPLACEMENT)


def _static_css() -> str:
    return """
.agi-web-shell{box-sizing:border-box;display:flex;flex-direction:column;gap:14px;padding:16px;border:1px solid rgba(148,163,184,.28);border-radius:22px;background:radial-gradient(circle at 18% 0%,rgba(56,189,248,.18),transparent 28%),linear-gradient(145deg,#07111f 0%,#0b1726 44%,#101827 100%);color:#e5edf7;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;box-shadow:0 18px 60px rgba(0,0,0,.28);overflow:hidden}
.agi-web-heading{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
.agi-web-heading strong{display:block;font-size:18px;line-height:1.15;letter-spacing:-.01em}
.agi-web-heading span{display:block;margin-top:5px;color:#9fb1c8;font-size:13px}
.agi-web-tech{border:1px solid rgba(148,163,184,.28);border-radius:999px;padding:5px 9px;color:#bae6fd;background:rgba(15,23,42,.72);font-size:11px;white-space:nowrap}
.agi-web-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(190px,270px);gap:14px;align-items:stretch;min-height:382px}
.agi-web-stage{position:relative;display:flex;flex-direction:column;gap:10px;min-width:0}
.agi-web-canvas-wrap{position:relative;min-height:340px;border-radius:22px;outline:none;overflow:hidden;background:linear-gradient(145deg,rgba(2,6,23,.92),rgba(15,23,42,.92));box-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 20px 45px rgba(2,6,23,.32)}
.agi-web-canvas-wrap:focus-visible{box-shadow:0 0 0 2px rgba(56,189,248,.62),0 20px 45px rgba(2,6,23,.32)}
.agi-web-canvas,.agi-web-overlay{position:absolute;inset:0;display:block;width:100%;height:100%;min-height:340px}
.agi-web-canvas{background:#08111f;border:1px solid rgba(148,163,184,.18);cursor:crosshair}
.agi-web-overlay{pointer-events:none}
.agi-web-canvas-hud{position:absolute;left:12px;right:12px;top:12px;display:flex;justify-content:space-between;gap:10px;pointer-events:none}
.agi-web-live-pill,.agi-web-confidence-pill{border:1px solid rgba(226,232,240,.16);border-radius:999px;padding:6px 9px;background:rgba(2,6,23,.62);backdrop-filter:blur(12px);color:#dff8ff;font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
.agi-web-live-pill{color:#bbf7d0;border-color:rgba(34,197,94,.34)}
.agi-web-confidence-pill{color:#fde68a;border-color:rgba(250,204,21,.28)}
.agi-web-legend{position:absolute;left:14px;bottom:14px;display:flex;flex-wrap:wrap;gap:8px;pointer-events:none}
.agi-web-legend span{display:inline-flex;align-items:center;gap:5px;border:1px solid rgba(148,163,184,.16);border-radius:999px;padding:5px 7px;background:rgba(2,6,23,.55);backdrop-filter:blur(10px);color:#cbd5e1;font-size:10px;font-weight:750}
.agi-web-dot{display:inline-block;width:8px;height:8px;border-radius:999px}
.agi-web-dot--zero{background:#38bdf8}
.agi-web-dot--one{background:#facc15}
.agi-web-line{display:inline-block;width:16px;height:2px;border-radius:999px;background:#f8fafc;box-shadow:0 0 8px rgba(248,250,252,.8)}
.agi-web-tooltip{position:absolute;z-index:4;pointer-events:none;border:1px solid rgba(125,211,252,.36);border-radius:12px;padding:7px 9px;background:rgba(2,6,23,.9);color:#e0f2fe;font-size:11px;box-shadow:0 10px 30px rgba(0,0,0,.35);transform:translate(10px,-50%)}
.agi-web-tooltip[hidden]{display:none}
.agi-web-timeline{display:grid;grid-template-columns:repeat(auto-fit,minmax(24px,1fr));gap:6px;align-items:center}
.agi-web-timeline button{height:12px;border:0;border-radius:999px;background:rgba(51,65,85,.86);box-shadow:inset 0 0 0 1px rgba(148,163,184,.16);cursor:pointer;transition:transform .14s ease,background .14s ease,box-shadow .14s ease}
.agi-web-timeline button:hover{transform:translateY(-1px);background:rgba(56,189,248,.72)}
.agi-web-timeline button[aria-selected="true"]{background:linear-gradient(90deg,#38bdf8,#22c55e);box-shadow:0 0 16px rgba(56,189,248,.42)}
.agi-web-controls{display:grid;grid-template-columns:auto minmax(120px,1fr) auto;gap:10px;align-items:center;border:1px solid rgba(148,163,184,.2);border-radius:16px;padding:9px 10px;background:rgba(15,23,42,.62)}
.agi-web-play{border:0;border-radius:999px;padding:8px 13px;background:linear-gradient(135deg,#38bdf8,#22c55e);color:#02131d;font-weight:800;cursor:pointer}
.agi-web-play:disabled{cursor:not-allowed;filter:grayscale(.5);opacity:.58}
.agi-web-scrub-label{display:grid;grid-template-columns:auto minmax(90px,1fr);gap:9px;align-items:center;color:#9fb1c8;font-size:12px}
.agi-web-frame-label{white-space:nowrap}
.agi-web-scrubber{width:100%;accent-color:#38bdf8}
.agi-web-frame-count{color:#bae6fd;font-size:12px;font-variant-numeric:tabular-nums;text-align:right}
.agi-web-hotkeys{color:#7f91a8;font-size:11px;text-align:center}
.agi-web-side{display:flex;flex-direction:column;gap:10px}
.agi-web-metric{border:1px solid rgba(148,163,184,.2);border-radius:16px;padding:10px 12px;background:rgba(15,23,42,.62)}
.agi-web-metric span{display:block;color:#8fa4bd;font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.agi-web-metric strong{display:block;margin-top:3px;color:#f8fafc;font-size:18px}
.agi-web-action{display:block;width:100%;box-sizing:border-box;margin-top:8px;border:1px solid rgba(56,189,248,.45);border-radius:14px;padding:9px 10px;background:rgba(8,47,73,.55);color:#dff8ff;text-align:center;text-decoration:none;font-weight:650}
.agi-web-action--primary{background:linear-gradient(135deg,#0ea5e9,#22c55e);border-color:transparent;color:#04111f}
.agi-web-lessons{display:grid;gap:8px}
.agi-web-lesson{border:1px solid rgba(148,163,184,.18);border-radius:14px;padding:9px 10px;background:rgba(15,23,42,.45)}
.agi-web-lesson span{display:block;color:#7dd3fc;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
.agi-web-lesson strong{display:block;margin-top:3px;color:#f8fafc;font-size:12px;line-height:1.2}
.agi-web-lesson em{display:block;margin-top:4px;color:#9fb1c8;font-size:11px;font-style:normal;line-height:1.28}
.agi-web-lesson--active{border-color:rgba(251,191,36,.48);background:rgba(88,55,16,.3)}
.agi-web-fallback{border:1px solid rgba(251,191,36,.4);border-radius:14px;padding:10px;background:rgba(120,53,15,.35);color:#fde68a}
@media (max-width:720px){.agi-web-layout{grid-template-columns:1fr}.agi-web-canvas,.agi-web-canvas-wrap{min-height:320px}.agi-web-heading{flex-direction:column}.agi-web-tech{white-space:normal}.agi-web-controls{grid-template-columns:1fr}.agi-web-frame-count{text-align:left}.agi-web-canvas-hud{position:static;margin:10px 10px -2px}.agi-web-legend{display:none}}
"""


def _static_js(*, container_id: str, data_id: str, canvas_id: str, overlay_id: str) -> str:
    script = """
(function(){
  const root = document.getElementById(__CONTAINER_ID__);
  const data = document.getElementById(__DATA_ID__);
  const canvas = document.getElementById(__CANVAS_ID__);
  const overlayCanvas = document.getElementById(__OVERLAY_ID__);
  if (!root || !data || !canvas) return;
  const component = JSON.parse(data.textContent || '{}');
  const payload = component.payload || {};
  const renderer = component.renderer || {};
  const frames = buildFrames(payload);
  const frameStats = frames.map(frame => summarizeFrame(frame.rows));
  const state = {
    frameIndex: Math.max(0, frames.length - 1),
    geometry: null,
    pointer: null,
    pendingDraw: false,
    playing: false,
    timer: null,
    webgl: null,
    renderMode: 'canvas2d'
  };
  const tech = root.querySelector('.agi-web-tech');
  if (tech) tech.textContent = (renderer.technology || 'html') + ' / ' + (renderer.renderer_id || 'renderer');
  renderMetrics();
  renderActions();
  renderLessons();

  const playButton = root.querySelector('.agi-web-play');
  const scrubber = root.querySelector('.agi-web-scrubber');
  const frameLabel = root.querySelector('.agi-web-frame-label');
  const frameCount = root.querySelector('.agi-web-frame-count');
  const tooltip = root.querySelector('.agi-web-tooltip');
  const canvasWrap = root.querySelector('.agi-web-canvas-wrap');
  const confidencePill = root.querySelector('.agi-web-confidence-pill');
  const timelineRoot = root.querySelector('.agi-web-timeline');
  renderTimeline();
  if (scrubber) {
    scrubber.min = '0';
    scrubber.max = String(Math.max(frames.length - 1, 0));
    scrubber.value = String(state.frameIndex);
    scrubber.disabled = frames.length <= 1;
    scrubber.addEventListener('input', () => {
      setFrame(Number(scrubber.value));
    });
  }
  if (playButton) {
    playButton.disabled = frames.length <= 1;
    playButton.addEventListener('click', () => togglePlay());
  }
  if (canvasWrap) canvasWrap.addEventListener('keydown', event => handleKeydown(event));
  canvas.addEventListener('mousemove', event => showTooltip(event));
  canvas.addEventListener('mouseleave', () => {
    state.pointer = null;
    if (tooltip) tooltip.hidden = true;
    requestDraw();
  });

  requestDraw();
  if (window.ResizeObserver) new ResizeObserver(requestDraw).observe(canvas);

  function renderMetrics() {
    const metricRoot = root.querySelector('.agi-web-metrics');
    const metrics = payload.metrics || payload.summary || {};
    const metricItems = Object.entries(metrics).slice(0, 5);
    if (!metricRoot) return;
    metricRoot.innerHTML = metricItems.length ? metricItems.map(([key, value]) =>
      '<div class="agi-web-metric"><span>' + escapeHtml(String(key).replaceAll('_',' ')) + '</span><strong>' +
      escapeHtml(formatValue(value)) + '</strong></div>'
    ).join('') : '<div class="agi-web-metric"><span>contract</span><strong>ready</strong></div>';
  }

  function renderActions() {
    const actionRoot = root.querySelector('.agi-web-actions');
    if (!actionRoot) return;
    actionRoot.innerHTML = (component.actions || []).map(action => {
      const label = escapeHtml(action.label || action.action_id || 'Action');
      const cls = action.style === 'primary' ? ' agi-web-action--primary' : '';
      if (action.target) return '<a class="agi-web-action' + cls + '" href="' + escapeAttr(action.target) + '">' + label + '</a>';
      return '<button class="agi-web-action' + cls + '" type="button" data-action="' + escapeAttr(action.action_id || '') + '">' + label + '</button>';
    }).join('');
    actionRoot.querySelectorAll('button[data-action]').forEach(button => {
      button.addEventListener('click', () => window.parent && window.parent.postMessage({
        schema: 'agilab.agi_web.action.v1',
        component_id: component.component_id,
        action_id: button.getAttribute('data-action')
      }, '*'));
    });
  }

  function renderLessons() {
    const lessonRoot = root.querySelector('.agi-web-lessons');
    const lessons = Array.isArray(payload.lessons) ? payload.lessons.slice(0, 3) : [];
    if (!lessonRoot) return;
    lessonRoot.innerHTML = lessons.map(lesson => {
      const active = lesson.state === 'active' ? ' agi-web-lesson--active' : '';
      return '<div class="agi-web-lesson' + active + '"><span>' + escapeHtml(lesson.preset || 'lesson') +
        '</span><strong>' + escapeHtml(lesson.lesson || 'What to learn') +
        '</strong><em>' + escapeHtml(lesson.watch || '') + '</em></div>';
    }).join('');
  }

  function renderTimeline() {
    if (!timelineRoot) return;
    timelineRoot.innerHTML = frames.map((frame, index) =>
      '<button type="button" role="tab" title="' + escapeAttr(frame.label) + '" aria-selected="' +
      (index === state.frameIndex ? 'true' : 'false') + '" data-frame="' + String(index) + '"></button>'
    ).join('');
    timelineRoot.querySelectorAll('button[data-frame]').forEach(button => {
      button.addEventListener('click', () => {
        stopPlay();
        setFrame(Number(button.getAttribute('data-frame') || 0));
      });
    });
  }

  function handleKeydown(event) {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      togglePlay();
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      stopPlay();
      setFrame(state.frameIndex + 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      stopPlay();
      setFrame(state.frameIndex - 1);
    }
  }

  function togglePlay() {
    if (state.playing) {
      stopPlay();
      return;
    }
    state.playing = true;
    if (playButton) playButton.textContent = 'Pause';
    state.timer = window.setInterval(() => {
      setFrame((state.frameIndex + 1) % Math.max(frames.length, 1));
    }, 520);
  }

  function stopPlay() {
    state.playing = false;
    if (playButton) playButton.textContent = 'Play';
    if (state.timer) window.clearInterval(state.timer);
    state.timer = null;
  }

  function setFrame(index) {
    state.frameIndex = clampInt(Number(index), 0, frames.length - 1);
    if (scrubber) scrubber.value = String(state.frameIndex);
    requestDraw();
  }

  function requestDraw() {
    if (state.pendingDraw) return;
    state.pendingDraw = true;
    window.requestAnimationFrame(() => {
      state.pendingDraw = false;
      drawCanvas(canvas, payload);
      updateFrameUi();
    });
  }

  function updateFrameUi() {
    const frame = currentFrame();
    if (scrubber && scrubber.value !== String(state.frameIndex)) scrubber.value = String(state.frameIndex);
    if (frameLabel) frameLabel.textContent = frame.label;
    if (frameCount) frameCount.textContent = String(state.frameIndex + 1) + '/' + String(Math.max(frames.length, 1));
    if (confidencePill) {
      const stats = frameStats[state.frameIndex] || {confidence: null};
      confidencePill.textContent = stats.confidence === null ? 'confidence --' : 'confidence ' + formatPercent(stats.confidence);
    }
    if (timelineRoot) {
      timelineRoot.querySelectorAll('button[data-frame]').forEach((button, index) => {
        button.setAttribute('aria-selected', index === state.frameIndex ? 'true' : 'false');
      });
    }
  }

  function currentFrame() {
    return frames[clampInt(state.frameIndex, 0, frames.length - 1)] || {label: 'empty', epoch: null, rows: []};
  }

  function drawCanvas(canvas, payload) {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(320, rect.width || 640);
    const height = Math.max(280, rect.height || 360);
    const dpr = window.devicePixelRatio || 1;
    resizeCanvas(canvas, width, height, dpr);
    if (overlayCanvas) resizeCanvas(overlayCanvas, width, height, dpr);
    const samples = Array.isArray(payload.samples) ? payload.samples : [];
    const frame = currentFrame();
    const grid = Array.isArray(frame.rows) ? frame.rows : [];
    const previousFrame = frames[Math.max(0, state.frameIndex - 1)] || frame;
    const previousGrid = Array.isArray(previousFrame.rows) ? previousFrame.rows : [];
    const history = Array.isArray(payload.history) ? payload.history : [];
    const bounds = resolveBounds(samples, flattenFrameRows(frames));
    const mainHeight = Math.round(height * 0.72);
    const wantsWebgl = String(renderer.technology || '').toLowerCase() === 'webgl';
    const overlayCtx = overlayCanvas ? overlayCanvas.getContext('2d') : null;
    if (overlayCtx) {
      overlayCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      overlayCtx.clearRect(0, 0, width, height);
    }
    if (wantsWebgl && renderWebglBoundary(canvas, grid, bounds, width, mainHeight, dpr)) {
      state.renderMode = 'webgl';
      if (overlayCtx) {
        state.geometry = drawBoundary(overlayCtx, grid, previousGrid, samples, bounds, width, mainHeight, frame.label, false);
        drawHistory(overlayCtx, history, 22, mainHeight + 24, width - 44, Math.max(70, height - mainHeight - 40), frame.epoch);
      }
      return;
    }
    state.renderMode = 'canvas2d';
    const ctx = wantsWebgl && overlayCtx ? overlayCtx : canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    root.setAttribute('data-agilab-renderer-active', 'canvas2d');
    state.geometry = drawBoundary(ctx, grid, previousGrid, samples, bounds, width, mainHeight, frame.label, true);
    drawHistory(ctx, history, 22, mainHeight + 24, width - 44, Math.max(70, height - mainHeight - 40), frame.epoch);
  }

  function resizeCanvas(target, width, height, dpr) {
    const pixelWidth = Math.floor(width * dpr);
    const pixelHeight = Math.floor(height * dpr);
    if (target.width !== pixelWidth) target.width = pixelWidth;
    if (target.height !== pixelHeight) target.height = pixelHeight;
  }

  function drawBoundary(ctx, grid, previousGrid, samples, bounds, width, height, label, paintHeatmap) {
    const pad = 24;
    const plotW = width - pad * 2;
    const plotH = height - pad * 2;
    const mapX = x => pad + ((Number(x) - bounds.minX) / Math.max(bounds.maxX - bounds.minX, 1e-9)) * plotW;
    const mapY = y => pad + (1 - ((Number(y) - bounds.minY) / Math.max(bounds.maxY - bounds.minY, 1e-9))) * plotH;
    const cell = Math.max(3, Math.ceil(Math.sqrt((plotW * plotH) / Math.max(grid.length, 1))));
    if (paintHeatmap) {
      const background = ctx.createLinearGradient(0, 0, width, height);
      background.addColorStop(0, '#06111f');
      background.addColorStop(1, '#0f172a');
      ctx.fillStyle = background;
      ctx.fillRect(0, 0, width, height);
    }
    drawLattice(ctx, pad, pad, plotW, plotH);
    if (paintHeatmap) {
      for (const row of grid) {
        const p = clamp(Number(row.probability ?? row.value ?? 0.5), 0, 1);
        ctx.fillStyle = mixColor(p);
        ctx.globalAlpha = 0.76;
        ctx.fillRect(mapX(row.x1) - cell / 2, mapY(row.x2) - cell / 2, cell + 1, cell + 1);
      }
    }
    ctx.globalAlpha = 1;
    drawUncertaintyContour(ctx, previousGrid, mapX, mapY, cell, 'rgba(148,163,184,.38)', 1.2);
    drawUncertaintyContour(ctx, grid, mapX, mapY, cell, 'rgba(248,250,252,.92)', 2.4);
    ctx.strokeStyle = 'rgba(226,232,240,.62)';
    ctx.lineWidth = 1;
    ctx.strokeRect(pad, pad, plotW, plotH);
    ctx.fillStyle = 'rgba(226,232,240,.72)';
    ctx.font = '12px ui-sans-serif, system-ui';
    ctx.fillText('Decision surface', pad, 16);
    ctx.textAlign = 'right';
    ctx.fillStyle = 'rgba(186,230,253,.9)';
    ctx.fillText(label || 'current', width - pad, 16);
    ctx.textAlign = 'left';
    for (const row of samples) {
      const target = Number(row.target ?? row.class ?? 0);
      ctx.beginPath();
      ctx.arc(mapX(row.x1), mapY(row.x2), target > 0 ? 4.2 : 3.7, 0, Math.PI * 2);
      ctx.fillStyle = target > 0 ? '#facc15' : '#38bdf8';
      ctx.fill();
      ctx.strokeStyle = 'rgba(15,23,42,.92)';
      ctx.stroke();
    }
    drawPointer(ctx, state.pointer, {pad, plotW, plotH, mapX, mapY});
    return {bounds, pad, plotW, plotH, mapX, mapY, plotBottom: height};
  }

  function renderWebglBoundary(canvas, grid, bounds, width, height, dpr) {
    if (!Array.isArray(grid) || !grid.length) return false;
    const webgl = getWebglState(canvas);
    if (!webgl) return false;
    const {gl, program, positionBuffer, probabilityBuffer, locations} = webgl;
    const positions = [];
    const probabilities = [];
    for (const row of grid) {
      const x1 = Number(row.x1);
      const x2 = Number(row.x2);
      const probability = Number(row.probability ?? row.value ?? 0.5);
      if (!Number.isFinite(x1) || !Number.isFinite(x2)) continue;
      positions.push(x1, x2);
      probabilities.push(clamp(Number.isFinite(probability) ? probability : 0.5, 0, 1));
    }
    if (!probabilities.length) return false;
    gl.viewport(0, Math.floor((canvas.height || 1) - height * dpr), Math.floor(width * dpr), Math.floor(height * dpr));
    gl.clearColor(0.024, 0.067, 0.122, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(locations.position);
    gl.vertexAttribPointer(locations.position, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, probabilityBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(probabilities), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(locations.probability);
    gl.vertexAttribPointer(locations.probability, 1, gl.FLOAT, false, 0, 0);
    gl.uniform4f(locations.bounds, bounds.minX, bounds.maxX, bounds.minY, bounds.maxY);
    const plotArea = Math.max(width * height, 1);
    const pointSize = Math.max(2.4, Math.sqrt(plotArea / Math.max(probabilities.length, 1)) * dpr * 1.18);
    gl.uniform1f(locations.pointSize, pointSize);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.drawArrays(gl.POINTS, 0, probabilities.length);
    gl.disableVertexAttribArray(locations.position);
    gl.disableVertexAttribArray(locations.probability);
    root.setAttribute('data-agilab-renderer-active', 'webgl');
    return true;
  }

  function getWebglState(canvas) {
    if (state.webgl && state.webgl.canvas === canvas) return state.webgl;
    const gl = canvas.getContext('webgl', {antialias: true, alpha: false, preserveDrawingBuffer: true}) ||
      canvas.getContext('experimental-webgl', {antialias: true, alpha: false, preserveDrawingBuffer: true});
    if (!gl) return null;
    const vertexShader = compileShader(gl, gl.VERTEX_SHADER, [
      'attribute vec2 a_position;',
      'attribute float a_probability;',
      'uniform vec4 u_bounds;',
      'uniform float u_point_size;',
      'varying float v_probability;',
      'void main(){',
      '  float x = ((a_position.x - u_bounds.x) / max(u_bounds.y - u_bounds.x, 0.000001)) * 2.0 - 1.0;',
      '  float y = ((a_position.y - u_bounds.z) / max(u_bounds.w - u_bounds.z, 0.000001)) * 2.0 - 1.0;',
      '  gl_Position = vec4(x, y, 0.0, 1.0);',
      '  gl_PointSize = u_point_size;',
      '  v_probability = a_probability;',
      '}'
    ].join('\\n'));
    const fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, [
      'precision mediump float;',
      'varying float v_probability;',
      'void main(){',
      '  vec2 p = gl_PointCoord - vec2(0.5);',
      '  float alpha = smoothstep(0.74, 0.12, length(p)) * 0.92;',
      '  vec3 cold = vec3(0.055, 0.647, 0.914);',
      '  vec3 warm = vec3(0.980, 0.800, 0.082);',
      '  vec3 color = mix(cold, warm, clamp(v_probability, 0.0, 1.0));',
      '  gl_FragColor = vec4(color, alpha);',
      '}'
    ].join('\\n'));
    if (!vertexShader || !fragmentShader) return null;
    const program = gl.createProgram();
    if (!program) return null;
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
    state.webgl = {
      canvas,
      gl,
      program,
      positionBuffer: gl.createBuffer(),
      probabilityBuffer: gl.createBuffer(),
      locations: {
        position: gl.getAttribLocation(program, 'a_position'),
        probability: gl.getAttribLocation(program, 'a_probability'),
        bounds: gl.getUniformLocation(program, 'u_bounds'),
        pointSize: gl.getUniformLocation(program, 'u_point_size')
      }
    };
    return state.webgl;
  }

  function compileShader(gl, kind, source) {
    const shader = gl.createShader(kind);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null;
  }

  function drawLattice(ctx, x, y, width, height) {
    ctx.save();
    ctx.strokeStyle = 'rgba(148,163,184,.08)';
    ctx.lineWidth = 1;
    const step = Math.max(28, Math.round(width / 12));
    for (let px = x; px <= x + width; px += step) {
      ctx.beginPath();
      ctx.moveTo(px, y);
      ctx.lineTo(px, y + height);
      ctx.stroke();
    }
    for (let py = y; py <= y + height; py += step) {
      ctx.beginPath();
      ctx.moveTo(x, py);
      ctx.lineTo(x + width, py);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawUncertaintyContour(ctx, grid, mapX, mapY, cell, color, width) {
    if (!Array.isArray(grid) || !grid.length) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = width;
    ctx.shadowBlur = width > 2 ? 12 : 0;
    ctx.shadowColor = 'rgba(248,250,252,.65)';
    const threshold = 0.08;
    const points = [];
    for (const row of grid) {
      const p = Number(row.probability ?? row.value ?? 0.5);
      if (!Number.isFinite(p) || Math.abs(p - 0.5) > threshold) continue;
      points.push({x: mapX(row.x1), y: mapY(row.x2)});
    }
    points.sort((left, right) => left.x === right.x ? left.y - right.y : left.x - right.x);
    for (const point of points) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, Math.max(1.6, cell * 0.18), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function drawPointer(ctx, pointer, geometry) {
    if (!pointer) return;
    const {px, py} = pointer;
    if (px < geometry.pad || px > geometry.pad + geometry.plotW || py < geometry.pad || py > geometry.pad + geometry.plotH) return;
    ctx.save();
    ctx.strokeStyle = 'rgba(125,211,252,.46)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(geometry.pad, py);
    ctx.lineTo(geometry.pad + geometry.plotW, py);
    ctx.moveTo(px, geometry.pad);
    ctx.lineTo(px, geometry.pad + geometry.plotH);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(px, py, 5, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(250,204,21,.9)';
    ctx.stroke();
    ctx.restore();
  }

  function drawHistory(ctx, history, x, y, width, height, currentEpoch) {
    ctx.fillStyle = 'rgba(15,23,42,.78)';
    roundRect(ctx, x, y, width, height, 14);
    ctx.fill();
    ctx.fillStyle = 'rgba(226,232,240,.72)';
    ctx.font = '12px ui-sans-serif, system-ui';
    ctx.fillText('Learning replay', x + 12, y + 18);
    if (!history.length) return;
    const values = history.map(row => Number(row.validation_accuracy ?? row.accuracy ?? 0)).filter(Number.isFinite);
    if (!values.length) return;
    const min = Math.min(...values, 0);
    const max = Math.max(...values, 1);
    ctx.strokeStyle = '#22c55e';
    ctx.lineWidth = 2;
    ctx.beginPath();
    const points = [];
    values.forEach((value, index) => {
      const px = x + 12 + (index / Math.max(values.length - 1, 1)) * (width - 24);
      const py = y + height - 14 - ((value - min) / Math.max(max - min, 1e-9)) * (height - 40);
      points.push({x: px, y: py, epoch: Number(history[index]?.epoch ?? index)});
      if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.stroke();
    const epochNumber = Number(currentEpoch);
    if (!Number.isFinite(epochNumber) || !points.length) return;
    const marker = points.reduce((best, point) =>
      Math.abs(point.epoch - epochNumber) < Math.abs(best.epoch - epochNumber) ? point : best
    );
    ctx.beginPath();
    ctx.arc(marker.x, marker.y, 4.8, 0, Math.PI * 2);
    ctx.fillStyle = '#facc15';
    ctx.fill();
    ctx.strokeStyle = '#0f172a';
    ctx.stroke();
  }

  function showTooltip(event) {
    if (!tooltip || !state.geometry) return;
    const geometry = state.geometry;
    const rect = canvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    if (px < geometry.pad || px > geometry.pad + geometry.plotW || py < geometry.pad || py > geometry.pad + geometry.plotH) {
      tooltip.hidden = true;
      return;
    }
    const point = toDataPoint(px, py, geometry);
    const nearest = nearestGridPoint(currentFrame().rows, point);
    state.pointer = {px, py};
    tooltip.innerHTML = 'x1 ' + formatCompact(point.x1) + '<br>x2 ' + formatCompact(point.x2) +
      (nearest ? '<br>p(class 1) ' + formatPercent(nearest.probability) : '');
    tooltip.style.left = String(Math.min(Math.max(px, 12), rect.width - 150)) + 'px';
    tooltip.style.top = String(Math.min(Math.max(py, 26), geometry.plotBottom - 12)) + 'px';
    tooltip.hidden = false;
    requestDraw();
  }

  function toDataPoint(px, py, geometry) {
    return {
      x1: geometry.bounds.minX + ((px - geometry.pad) / Math.max(geometry.plotW, 1)) * (geometry.bounds.maxX - geometry.bounds.minX),
      x2: geometry.bounds.maxY - ((py - geometry.pad) / Math.max(geometry.plotH, 1)) * (geometry.bounds.maxY - geometry.bounds.minY)
    };
  }

  function nearestGridPoint(grid, point) {
    if (!Array.isArray(grid) || !grid.length) return null;
    let best = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const row of grid) {
      const x1 = Number(row.x1);
      const x2 = Number(row.x2);
      if (!Number.isFinite(x1) || !Number.isFinite(x2)) continue;
      const distance = (x1 - point.x1) * (x1 - point.x1) + (x2 - point.x2) * (x2 - point.x2);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = {probability: Number(row.probability ?? row.value ?? 0.5)};
      }
    }
    return best;
  }

  function buildFrames(payload) {
    const snapshots = Array.isArray(payload.snapshots) ? payload.snapshots : [];
    const groups = new Map();
    snapshots.forEach(row => {
      const epoch = Number(row.epoch);
      if (!Number.isFinite(epoch)) return;
      const key = String(Math.round(epoch));
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    });
    const frames = Array.from(groups.entries())
      .sort((left, right) => Number(left[0]) - Number(right[0]))
      .map(([epoch, rows]) => ({label: 'epoch ' + epoch, epoch: Number(epoch), rows}));
    if (!frames.length && Array.isArray(payload.start_grid) && payload.start_grid.length) {
      frames.push({label: 'start', epoch: null, rows: payload.start_grid});
    }
    if (Array.isArray(payload.grid) && payload.grid.length) {
      const label = frames.length ? 'final' : 'current';
      frames.push({label, epoch: null, rows: payload.grid});
    }
    if (!frames.length) frames.push({label: 'empty', epoch: null, rows: []});
    return frames;
  }

  function flattenFrameRows(frames) {
    return frames.flatMap(frame => Array.isArray(frame.rows) ? frame.rows : []);
  }

  function summarizeFrame(rows) {
    const values = (Array.isArray(rows) ? rows : [])
      .map(row => Number(row.probability ?? row.value))
      .filter(Number.isFinite);
    if (!values.length) return {confidence: null};
    const confidence = values.reduce((total, value) => total + Math.abs(clamp(value, 0, 1) - 0.5) * 2, 0) / values.length;
    return {confidence: clamp(confidence, 0, 1)};
  }

  function resolveBounds(samples, grid) {
    const rows = samples.concat(grid);
    const xs = rows.map(row => Number(row.x1)).filter(Number.isFinite);
    const ys = rows.map(row => Number(row.x2)).filter(Number.isFinite);
    return {
      minX: xs.length ? Math.min(...xs) : -1,
      maxX: xs.length ? Math.max(...xs) : 1,
      minY: ys.length ? Math.min(...ys) : -1,
      maxY: ys.length ? Math.max(...ys) : 1
    };
  }

  function mixColor(p) {
    const a = [14, 165, 233];
    const b = [250, 204, 21];
    const r = Math.round(a[0] + (b[0] - a[0]) * p);
    const g = Math.round(a[1] + (b[1] - a[1]) * p);
    const bl = Math.round(a[2] + (b[2] - a[2]) * p);
    return 'rgb(' + r + ',' + g + ',' + bl + ')';
  }
  function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
  function clampInt(value, min, max) { return Math.max(min, Math.min(max, Math.round(value || 0))); }
  function formatValue(value) { return typeof value === 'number' ? (Math.abs(value) <= 1 ? Math.round(value * 100) + '%' : String(Math.round(value * 1000) / 1000)) : String(value); }
  function formatCompact(value) { return Number.isFinite(Number(value)) ? String(Math.round(Number(value) * 1000) / 1000) : 'n/a'; }
  function formatPercent(value) { return Number.isFinite(Number(value)) ? String(Math.round(Number(value) * 100)) + '%' : 'n/a'; }
  function escapeHtml(value) { return value.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[char]); }
  function escapeAttr(value) { return escapeHtml(value).replaceAll('`', '&#96;'); }
  function roundRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + width, y, x + width, y + height, radius);
    ctx.arcTo(x + width, y + height, x, y + height, radius);
    ctx.arcTo(x, y + height, x, y, radius);
    ctx.arcTo(x, y, x + width, y, radius);
    ctx.closePath();
  }
})();
"""
    return (
        script.replace("__CONTAINER_ID__", json.dumps(container_id))
        .replace("__DATA_ID__", json.dumps(data_id))
        .replace("__CANVAS_ID__", json.dumps(canvas_id))
        .replace("__OVERLAY_ID__", json.dumps(overlay_id))
    )
