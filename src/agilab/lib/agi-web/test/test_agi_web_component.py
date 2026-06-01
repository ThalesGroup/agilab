from __future__ import annotations

import builtins
import dataclasses
import datetime as dt
import decimal
import enum
import importlib
import importlib.metadata
import sys
import tomllib
import uuid
from pathlib import Path
from types import SimpleNamespace


AGI_WEB_ROOT = Path(__file__).resolve().parents[1]


def _load_agi_web():
    sys.modules.pop("agi_web.component", None)
    sys.modules.pop("agi_web", None)
    src = AGI_WEB_ROOT / "src"
    sys.path.insert(0, src.as_posix())
    try:
        return importlib.import_module("agi_web")
    finally:
        try:
            sys.path.remove(src.as_posix())
        except ValueError:
            pass


def test_agi_web_package_metadata_points_to_lib_package() -> None:
    data = tomllib.loads((AGI_WEB_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "agi-web"
    assert data["project"]["urls"]["Source"].endswith("/src/agilab/lib/agi-web")


def test_agi_web_exposes_version() -> None:
    agi_web = _load_agi_web()
    try:
        installed_version = importlib.metadata.version("agi-web")
    except importlib.metadata.PackageNotFoundError:
        installed_version = "0+unknown"

    assert agi_web.__version__ == installed_version


def test_agi_web_component_evidence_is_deterministic_and_payload_sensitive() -> None:
    agi_web = _load_agi_web()
    renderer = agi_web.AgiWebRendererSpec(
        renderer_id="demo-canvas",
        technology="canvas2d",
        capabilities=("boundary", "history"),
    )
    first = agi_web.AgiWebComponent(
        component_id="Demo Component",
        title="Demo",
        renderer=renderer,
        payload={"value": 1, "bad": float("nan")},
        actions=[agi_web.AgiWebAction("run", "Run", style="primary")],
    )
    repeated = agi_web.AgiWebComponent(
        component_id="Demo Component",
        title="Demo",
        renderer=renderer,
        payload={"bad": float("nan"), "value": 1},
        actions=[agi_web.AgiWebAction("run", "Run", style="primary")],
    )
    changed = agi_web.AgiWebComponent(
        component_id="Demo Component",
        title="Demo",
        renderer=renderer,
        payload={"value": 2},
    )

    assert first.as_dict()["component_id"] == "demo-component"
    assert first.evidence()["payload_hash"] == repeated.evidence()["payload_hash"]
    assert first.evidence()["payload_hash"] != changed.evidence()["payload_hash"]
    assert first.as_dict()["payload"]["bad"] is None


def test_agi_web_records_from_dataframe_like_are_bounded_and_stable() -> None:
    agi_web = _load_agi_web()

    class Frame:
        def to_dict(self, *, orient=None):
            assert orient == "records"
            return [{"b": 2, "a": 1}, {"b": 4, "a": 3}, {"b": 6, "a": 5}]

    records = agi_web.records_from_data(Frame(), max_rows=2)

    assert records == [{"b": 2, "a": 1}, {"b": 6, "a": 5}]


def test_agi_web_static_html_escapes_script_end_and_embeds_evidence() -> None:
    agi_web = _load_agi_web()
    component = agi_web.AgiWebComponent(
        component_id="unsafe </script> id",
        title="Unsafe",
        renderer=agi_web.AgiWebRendererSpec("demo", technology="custom"),
        payload={"text": "</script><script>alert(1)</script>"},
    )

    html = agi_web.component_to_static_html(component)

    assert 'data-agilab-web-evidence="' in html
    assert "<canvas" in html
    assert 'class="agi-web-canvas-hud"' in html
    assert 'class="agi-web-overlay"' in html
    assert 'class="agi-web-timeline"' in html
    assert 'class="agi-web-play"' in html
    assert 'class="agi-web-scrubber"' in html
    assert "buildFrames(payload)" in html
    assert "function renderTimeline()" in html
    assert "function drawUncertaintyContour" in html
    assert "function handleKeydown" in html
    assert "function renderWebglBoundary" in html
    assert "data-agilab-renderer-active" in html
    assert '<script>alert(1)</script>' not in html
    assert "<\\/script>" in html


def test_agi_web_render_streamlit_uses_components_html() -> None:
    agi_web = _load_agi_web()
    calls: list[tuple[str, int, bool]] = []

    def html_renderer(fragment, *, height, scrolling):
        calls.append((fragment, height, scrolling))
        return "rendered"

    fake_st = SimpleNamespace(components=SimpleNamespace(v1=SimpleNamespace(html=html_renderer)))
    component = agi_web.AgiWebComponent(
        component_id="demo",
        title="Demo",
        renderer=agi_web.AgiWebRendererSpec("demo"),
    )

    assert agi_web.render_streamlit(component, streamlit=fake_st, height=400) == "rendered"
    assert calls[0][1:] == (400, False)


def test_agi_web_records_from_data_covers_mapping_and_scalar_shapes() -> None:
    agi_web = _load_agi_web()

    class PolarsLike:
        def to_dicts(self):
            return [{"b": 2, "a": 1}]

    class MappingFrame:
        def to_dict(self, **kwargs):
            if kwargs:
                raise TypeError("orient is not supported")
            return {"x": [1, 2], "y": [3, 4]}

    assert agi_web.records_from_data(PolarsLike()) == [{"b": 2, "a": 1}]
    assert agi_web.records_from_data(MappingFrame()) == [
        {"x": 1, "y": 3},
        {"x": 2, "y": 4},
    ]
    assert agi_web.records_from_data({"x": [1, 2], "y": [3, 4]}) == [
        {"x": 1, "y": 3},
        {"x": 2, "y": 4},
    ]
    assert agi_web.records_from_data([(1, 2), "plain"], max_rows=0) == []
    assert agi_web.records_from_data(7) == [{"value": 7}]


def test_agi_web_normalize_json_value_handles_portable_scalars() -> None:
    agi_web = _load_agi_web()

    @dataclasses.dataclass(frozen=True)
    class Payload:
        path: Path
        count: int

    class Mood(enum.Enum):
        HAPPY = "happy"

    class Scalar:
        def item(self):
            return decimal.Decimal("2.5")

    class BrokenScalar:
        def item(self):
            raise RuntimeError("not scalar")

        def __str__(self) -> str:
            return "broken"

    payload_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    normalized = agi_web.normalize_json_value(
        {
            "bytes": b"\x00\xff",
            "date": dt.date(2026, 6, 1),
            "datetime": dt.datetime(2026, 6, 1, 12, 30),
            "decimal": decimal.Decimal("2"),
            "enum": Mood.HAPPY,
            "path": Path("artifact.json"),
            "payload": Payload(Path("nested.txt"), 3),
            "scalar": Scalar(),
            "uuid": payload_id,
        }
    )

    assert normalized == {
        "bytes": "00ff",
        "date": "2026-06-01",
        "datetime": "2026-06-01T12:30:00",
        "decimal": 2,
        "enum": "happy",
        "path": "artifact.json",
        "payload": {"count": 3, "path": "nested.txt"},
        "scalar": 2.5,
        "uuid": str(payload_id),
    }
    assert agi_web.normalize_json_value(decimal.Decimal("NaN")) is None
    assert agi_web.normalize_json_value(float("inf")) is None
    assert agi_web.normalize_json_value(BrokenScalar()) == "broken"


def test_agi_web_component_variants_and_notebook_fallback(monkeypatch) -> None:
    agi_web = _load_agi_web()
    component = agi_web.AgiWebComponent(
        component_id=None,
        title="Portable",
        subtitle="Evidence island",
        renderer=agi_web.AgiWebRendererSpec(
            renderer_id="Renderer ID",
            technology="unknown-tech",
            assets=[
                agi_web.AgiWebAsset(
                    asset_id="style",
                    kind="css",
                    href="style.css",
                    integrity="sha256-demo",
                    mime_type="text/css",
                )
            ],
        ),
        actions=[
            agi_web.AgiWebAction(
                action_id="open",
                label="Open",
                target="details",
                payload={"path": Path("result.json")},
                style="primary",
            )
        ],
    )

    payload = component.as_dict(include_evidence=False)
    assert "evidence" not in payload
    assert payload["component_id"] == "component"
    assert payload["renderer"]["renderer_id"] == "renderer-id"
    assert payload["renderer"]["technology"] == "custom"
    assert payload["renderer"]["assets"][0]["mime_type"] == "text/css"
    assert payload["actions"][0]["payload"] == {"path": "result.json"}

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "IPython.display":
            raise ImportError("IPython unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    fallback = agi_web.render_notebook(component, height=10, width="<100%>")
    assert isinstance(fallback, str)
    assert "min-height:240px" in fallback
    assert "&lt;100%&gt;" in fallback
