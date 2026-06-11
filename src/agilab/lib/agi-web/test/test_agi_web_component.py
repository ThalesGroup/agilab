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


def test_agi_web_version_falls_back_when_package_metadata_missing(monkeypatch) -> None:
    def missing_version(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing_version)

    assert _load_agi_web().__version__ == "0+unknown"


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


def test_agi_web_render_streamlit_imports_default_streamlit(monkeypatch) -> None:
    agi_web = _load_agi_web()
    calls: list[tuple[str, int, bool]] = []

    def html_renderer(fragment, *, height, scrolling):
        calls.append((fragment, height, scrolling))
        return "rendered"

    fake_st = SimpleNamespace(components=SimpleNamespace(v1=SimpleNamespace(html=html_renderer)))
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "streamlit":
            return fake_st
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    component = agi_web.AgiWebComponent(
        component_id="demo",
        title="Demo",
        renderer=agi_web.AgiWebRendererSpec("demo"),
    )

    assert agi_web.render_streamlit(component, height=360) == "rendered"
    assert calls[0][1:] == (360, False)


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
    assert agi_web.records_from_data() == []
    assert agi_web.records_from_data({}) == []
    assert agi_web.records_from_data({"x": 1, "y": 2}) == [{"x": 1, "y": 2}]
    assert agi_web.records_from_data({"x": [1], "y": [2, 3]}) == [{"x": [1], "y": [2, 3]}]
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

    class NonCallableItem:
        item = "not-callable"

        def __str__(self) -> str:
            return "non-callable"

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
    assert agi_web.normalize_json_value(NonCallableItem()) == "non-callable"


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
    assert "width:100%;" in fallback


def test_agi_web_render_notebook_returns_ipython_html(monkeypatch) -> None:
    agi_web = _load_agi_web()
    component = agi_web.AgiWebComponent(
        component_id="demo",
        title="Demo",
        renderer=agi_web.AgiWebRendererSpec("demo"),
    )

    class FakeHTML:
        def __init__(self, fragment):
            self.fragment = fragment

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "IPython.display":
            return SimpleNamespace(HTML=FakeHTML)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    rendered = agi_web.render_notebook(component)

    assert isinstance(rendered, FakeHTML)
    assert 'class="agi-web-shell"' in rendered.fragment


def test_agi_web_json_island_escapes_mixed_case_script_end_and_line_separators() -> None:
    agi_web = _load_agi_web()
    component = agi_web.AgiWebComponent(
        component_id="unsafe",
        title="Unsafe",
        renderer=agi_web.AgiWebRendererSpec("demo", technology="canvas2d"),
        payload={
            "mixed": "</ScRiPt><ScRiPt>alert(1)</ScRiPt>",
            "comment": "<!-- sneaky -->",
            "separators": "line and end",
        },
    )

    html = agi_web.component_to_static_html(component)

    assert "</ScRiPt>" not in html
    assert "<\\/ScRiPt>" in html
    assert "<!-- sneaky" not in html
    assert "<\\!-- sneaky" in html
    assert " " not in html
    assert " " not in html
    assert "\\u2028" in html
    assert "\\u2029" in html


def test_agi_web_action_target_validation() -> None:
    agi_web = _load_agi_web()

    stripped = agi_web.AgiWebAction("bad", "Bad", target="javascript:alert(1)").as_dict()
    assert stripped["target"] == ""
    assert stripped["kind"] == "emit"

    for unsafe in ("data:text/html,x", "vbscript:msgbox", "file:///etc/passwd"):
        assert agi_web.AgiWebAction("bad", "Bad", target=unsafe).as_dict()["target"] == ""

    assert agi_web.AgiWebAction("ok", "Ok", target="https://agilab.dev").as_dict()["target"] == "https://agilab.dev"
    assert agi_web.AgiWebAction("ok", "Ok", target="mailto:team@agilab.dev").as_dict()["target"] == "mailto:team@agilab.dev"
    assert agi_web.AgiWebAction("ok", "Ok", target="details?tab=1#top").as_dict()["target"] == "details?tab=1#top"


def test_agi_web_action_enum_validation() -> None:
    agi_web = _load_agi_web()
    import pytest

    with pytest.raises(ValueError, match="surprise"):
        agi_web.AgiWebAction("a", "A", kind="surprise").as_dict()
    with pytest.raises(ValueError, match="tertiary"):
        agi_web.AgiWebAction("a", "A", style="tertiary").as_dict()
    for kind in ("emit", "link", "download"):
        assert agi_web.AgiWebAction("a", "A", kind=kind).as_dict()["kind"] == kind


def test_agi_web_static_html_width_validation_falls_back() -> None:
    agi_web = _load_agi_web()
    component = agi_web.AgiWebComponent(
        component_id="demo",
        title="Demo",
        renderer=agi_web.AgiWebRendererSpec("demo", technology="canvas2d"),
    )

    injected = agi_web.component_to_static_html(component, width="100%;position:fixed")
    assert "position:fixed" not in injected
    assert "width:100%;" in injected

    sized = agi_web.component_to_static_html(component, width="42.5rem")
    assert "width:42.5rem;" in sized


def test_agi_web_static_html_renderer_notice_for_unimplemented_technology() -> None:
    agi_web = _load_agi_web()

    def render(technology):
        return agi_web.component_to_static_html(
            agi_web.AgiWebComponent(
                component_id="demo",
                title="Demo",
                renderer=agi_web.AgiWebRendererSpec("demo", technology=technology),
            )
        )

    react_html = render("react")
    assert 'class="agi-web-renderer-notice"' in react_html
    assert 'renderer technology &quot;react&quot; is not available in this host' in react_html or \
        'renderer technology "react" is not available in this host' in react_html
    assert "<canvas" in react_html

    for technology in ("canvas2d", "webgl"):
        assert 'class="agi-web-renderer-notice"' not in render(technology)


def test_agi_web_static_html_host_origin_and_link_rel() -> None:
    agi_web = _load_agi_web()
    component = agi_web.AgiWebComponent(
        component_id="demo",
        title="Demo",
        renderer=agi_web.AgiWebRendererSpec("demo", technology="canvas2d"),
        actions=[agi_web.AgiWebAction("open", "Open", target="https://agilab.dev")],
    )

    default_html = agi_web.component_to_static_html(component)
    assert 'const hostOrigin = "";' in default_html
    assert "hostOrigin || '*'" in default_html
    assert 'rel="noopener noreferrer"' in default_html

    pinned_html = agi_web.component_to_static_html(component, host_origin="https://lab.example")
    assert 'const hostOrigin = "https://lab.example";' in pinned_html
