"""Browser regression for native columns with long notebook/template options."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def native_chromium_executable() -> str:
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="Native layout regression requires Playwright"
    )
    # Resolve the installed browser before per-test HOME isolation changes its cache.
    with playwright.sync_playwright() as engine:
        return engine.chromium.executable_path


@pytest.mark.parametrize("viewport_width", [1440, 390])
def test_native_columns_keep_long_select_options_inside_the_viewport(
    tmp_path: Path, viewport_width: int, native_chromium_executable: str
) -> None:
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="Native layout regression requires Playwright"
    )
    from tools.agilab_web_robot import (
        ReactPythonServer,
        _free_port,
        wait_for_react_health,
    )

    page_source = tmp_path / "agilab_native_long_select_columns_repro.py"
    page_source.write_text(
        "from agi_web import python_ui as ui\n"
        "ui.set_page_config(page_title='Native columns layout regression', layout='wide')\n"
        "ui.title('Native columns layout regression')\n"
        "with ui.sidebar:\n"
        "    ui.text_input('Workspace preference', value='saved preference', key='sidebar_preference')\n"
        "left, right = ui.columns([2, 1])\n"
        "with left:\n"
        "    ui.selectbox('Import notebook', ['/workspace/' + 'notebook_path_' * 80], key='notebook')\n"
        "with right:\n"
        "    ui.selectbox('Stage template', ['template_' * 80], key='template')\n"
        "with ui.expander('Stage code preview', expanded=True):\n"
        "    ui.code('long_stage_expression_' * 100)\n",
        encoding="utf-8",
    )
    url = f"http://127.0.0.1:{_free_port()}"
    command = [
        sys.executable,
        "-m",
        "agi_web.react_python_host",
        str(page_source),
        "--address",
        "127.0.0.1",
        "--port",
        url.rsplit(":", 1)[1],
        "--no-browser",
    ]
    with ReactPythonServer(command, env=dict(os.environ), url=url) as server:
        health = wait_for_react_health(url, timeout=30)
        assert health.success, server.output_tail()
        with playwright.sync_playwright() as engine:
            browser = engine.chromium.launch(executable_path=native_chromium_executable)
            try:
                page = browser.new_page(
                    viewport={"width": viewport_width, "height": 900}
                )
                issues: list[str] = []
                page.on("pageerror", lambda error: issues.append(str(error)))
                page.on(
                    "console",
                    lambda message: issues.append(message.text)
                    if message.type in {"warning", "error"}
                    else None,
                )
                page.on(
                    "requestfailed", lambda request: issues.append(str(request.failure))
                )
                page.on(
                    "response",
                    lambda response: issues.append(
                        f"HTTP {response.status}: {response.url}"
                    )
                    if response.status >= 400
                    else None,
                )
                page.goto(url)
                page.get_by_role("button", name="Tools", exact=True).click()
                fields = [
                    page.get_by_label("Import notebook"),
                    page.get_by_label("Stage template"),
                ]
                for field in fields:
                    field.wait_for(state="visible")
                    assert field.input_value(), (
                        "The authored option must remain selected"
                    )
                    bounds = field.bounding_box()
                    assert bounds is not None
                    assert bounds["width"] > 0
                    assert bounds["x"] >= 0
                    assert bounds["x"] + bounds["width"] <= viewport_width + 1, bounds
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth + 1"
                ), "Native controls must fit without clipping page overflow"
                assert page.locator(".py-code").evaluate(
                    "el => el.scrollWidth > el.clientWidth"
                ), "Long stage code must remain available through its own scroll area"
                if viewport_width == 1440:
                    left, right = [field.bounding_box() for field in fields]
                    assert left is not None and right is not None
                    assert left["width"] > right["width"], (
                        "Preserve the authored 2:1 layout"
                    )
                assert not issues, issues
            finally:
                browser.close()
