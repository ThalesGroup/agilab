from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path("tools/agi_web_visual_regression.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agi_web_visual_regression_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agi_web_visual_regression_fixture_uses_webgl_contract() -> None:
    module = _load_module()

    component = module.build_demo_component()
    payload = component.as_dict()

    assert payload["renderer"]["technology"] == "webgl"
    assert payload["renderer"]["renderer_id"] == "agi-web-webgl-visual-regression"
    assert "gpu-heatmap" in payload["renderer"]["capabilities"]
    assert payload["payload"]["snapshots"]
    assert payload["evidence"]["payload_hash"]


def test_agi_web_visual_regression_static_fixture_contains_webgl_runtime(tmp_path: Path) -> None:
    module = _load_module()

    html_path = module.write_static_fixture(tmp_path)
    html = html_path.read_text(encoding="utf-8")

    assert html_path.name == "agi-web-webgl-visual-regression.html"
    assert "renderWebglBoundary" in html
    assert "data-agilab-renderer-active" in html
    assert "agi-web-overlay" in html


def test_agi_web_visual_regression_browser_contract_helpers() -> None:
    module = _load_module()

    assert module.expand_browser_names(None) == ("chromium",)
    assert module.expand_browser_names(["firefox", "chromium", "firefox"]) == ("firefox", "chromium")
    assert module.expand_browser_names(["all"]) == ("chromium", "firefox", "webkit")

    assert module.evaluate_browser_result(
        browser_name="chromium",
        active_renderer="webgl",
        webgl_supported=True,
        render_ms=500.0,
        require_webgl=True,
        max_render_ms=1000.0,
    ) == (True, "ok")
    success, detail = module.evaluate_browser_result(
        browser_name="chromium",
        active_renderer="canvas2d",
        webgl_supported=True,
        render_ms=1500.0,
        require_webgl=True,
        max_render_ms=1000.0,
    )
    assert success is False
    assert "WebGL renderer did not activate" in detail
    assert "render budget exceeded" in detail
