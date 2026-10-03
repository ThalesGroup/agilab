#!/usr/bin/env python3
"""Exercise retained Python rendering and actions in the real native browser host."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import threading
import time

from agi_web import python_ui as ui
from agi_web.react_python_host import ReactPythonServer


def demo_view():
    ui.title("Native Python view validation")
    ui.markdown("| View | Status |\n|---|---|\n| Python | Retained |\n\n- Map\n- Curve\n\nInline $x^2$ and `code $untouched$`.\n\n$$\n\\int_0^1 x\\,dx = \\frac{1}{2}\n$$")
    ui.latex(r"E = mc^2")
    ui.markdown("<b>Literal HTML</b>")
    ui.html('<style>.native-render-card{color:rgb(12, 34, 56);padding:12px}</style><div class="native-render-card">Styled Python card</div><script>window.nativeInjected=true</script><img src="data:image/png;base64," onerror="window.nativeInjected=true"><a href="javascript:window.nativeInjected=true">Unsafe link</a>')
    ui.graphviz_chart('digraph Pipeline { inputs -> analysis -> export; }')
    ui.image('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="32"><rect width="64" height="32" fill="#345678"/></svg>', caption="Inline SVG image")
    ui.caption("Source: https://example.test/" + "long-source-reference/" * 30)
    ui.file_uploader("Notebook", type=["ipynb"], key="notebook")
    if ui.session_state.get("notebook"):
        ui.success(f"Uploaded {ui.session_state.notebook.name}: {ui.session_state.notebook.size} bytes")
    outside = ui.text_input("Outside input", key="outside")
    if ui.button("Apply outside value"):
        ui.session_state["outside_saved"] = outside
        ui.session_state["outside_clicks"] = ui.session_state.get("outside_clicks", 0) + 1
    ui.metric("Outside saved", ui.session_state.get("outside_saved", ""))
    ui.metric("Outside clicks", ui.session_state.get("outside_clicks", 0))
    with ui.form("save"):
        draft = ui.text_input("Project name", key="project_name")
        if ui.form_submit_button("Save project"):
            ui.session_state["saved"] = draft
            ui.session_state["saves"] = ui.session_state.get("saves", 0) + 1
    ui.metric("Saved project", ui.session_state.get("saved", ""))
    ui.metric("Save count", ui.session_state.get("saves", 0))
    with ui.form("independent"):
        independent = ui.text_input("Independent draft", key="independent")
        if ui.form_submit_button("Save independent"):
            ui.session_state["independent_saved"] = independent
    ui.metric("Independent saved", ui.session_state.get("independent_saved", ""))
    if ui.button("Run calculation"):
        with ui.spinner("Calculation running"):
            progress = ui.progress(0, text="Starting")
            progress.progress(50, text="Half done")
            time.sleep(1.2)
            progress.progress(100, text="Calculation complete")
        ui.success("Calculation complete")
    ui.download_button("Export result", "native notebook result", "native_result.txt")


def run(output: Path):
    from playwright.sync_api import sync_playwright, expect

    distributions = sorted(distribution.metadata["Name"] for distribution in importlib.metadata.distributions()
                           if distribution.metadata["Name"].lower().replace("_", "-").startswith("streamlit"))
    assert not distributions, f"Unexpected Streamlit distributions: {distributions}"
    output.mkdir(parents=True, exist_ok=True)
    server = ReactPythonServer(("127.0.0.1", 0), demo_view)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors, failures, external = [], [], []
    base = f"http://127.0.0.1:{server.server_port}"
    checks = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("requestfailed", lambda request: failures.append({"url": request.url, "error": request.failure}))
            page.on("request", lambda request: external.append(request.url) if not request.url.startswith((base, "data:", "blob:")) else None)
            page.on("response", lambda response: failures.append({"url": response.url, "status": response.status}) if response.status >= 400 else None)
            page.goto(base, wait_until="networkidle")
            expect(page.get_by_role("heading", name="Native Python view validation")).to_be_visible()
            expect(page.locator(".py-markdown table")).to_have_count(1)
            expect(page.locator(".py-markdown li")).to_have_count(2)
            expect(page.locator(".katex")).to_have_count(3)
            expect(page.locator(".py-markdown code")).to_have_text("code $untouched$")
            expect(page.get_by_text("<b>Literal HTML</b>", exact=True)).to_be_visible()
            assert page.locator(".native-render-card").evaluate("element => getComputedStyle(element).color") == "rgb(12, 34, 56)"
            assert not page.evaluate("Boolean(window.nativeInjected)")
            assert page.locator("a").filter(has_text="Unsafe link").get_attribute("href") is None
            expect(page.locator(".py-graph svg")).to_be_visible(timeout=15000)
            assert all(label in page.locator(".py-graph").inner_text() for label in ["inputs", "analysis", "export"])
            checks.extend(["markdown_table_and_list", "math_and_literal_code", "trusted_python_css", "html_sanitization", "local_graphviz"])
            svg_image = page.locator('img[src^="/api/assets/"]')
            expect(svg_image).to_be_visible()
            assert svg_image.evaluate("image => image.complete && image.naturalWidth === 64 && image.naturalHeight === 32")
            checks.append("private_inline_svg_image")

            page.get_by_label("Notebook", exact=True).set_input_files({"name": "project.ipynb", "mimeType": "application/x-ipynb+json", "buffer": b'{"cells": []}'})
            expect(page.get_by_text("Uploaded project.ipynb: 13 bytes", exact=True)).to_be_visible()
            page.get_by_label("Outside input", exact=True).fill("edited")
            page.get_by_role("button", name="Apply outside value", exact=True).click()
            expect(page.locator(".py-metric").filter(has_text="Outside saved").locator("strong")).to_have_text("edited")
            expect(page.locator(".py-metric").filter(has_text="Outside clicks").locator("strong")).to_have_text("1")
            page.get_by_label("Independent draft", exact=True).fill("Keep independent draft")
            page.get_by_label("Project name", exact=True).fill("Keyboard project")
            page.get_by_label("Project name", exact=True).press("Enter")
            expect(page.locator(".py-metric").filter(has_text="Saved project").locator("strong")).to_have_text("Keyboard project")
            expect(page.locator(".py-metric").filter(has_text="Save count").locator("strong")).to_have_text("1")
            expect(page.get_by_label("Independent draft", exact=True)).to_have_value("Keep independent draft")
            page.get_by_role("button", name="Save independent", exact=True).click()
            expect(page.locator(".py-metric").filter(has_text="Independent saved").locator("strong")).to_have_text("Keep independent draft")
            page.get_by_label("Project name", exact=True).fill("Notebook project")
            page.get_by_role("button", name="Save project", exact=True).click()
            expect(page.locator(".py-metric").filter(has_text="Saved project").locator("strong")).to_have_text("Notebook project")
            expect(page.locator(".py-metric").filter(has_text="Save count").locator("strong")).to_have_text("2")
            page.get_by_role("button", name="Run calculation", exact=True).click()
            expect(page.locator("progress")).to_have_attribute("value", "0.5")
            expect(page.get_by_text("Calculation complete", exact=True).last).to_be_visible()
            expect(page.locator("progress")).to_have_attribute("value", "1")
            expect(page.locator('[data-widget-kind="status"]')).to_have_attribute("data-state", "complete")
            expect(page.locator(".py-metric").filter(has_text="Save count").locator("strong")).to_have_text("2")
            checks.extend(["notebook_upload", "blur_then_button_click", "form_enter_submission", "independent_form_drafts", "atomic_form_submit", "one_shot_save", "live_progress"])
            with page.expect_download() as download_info:
                page.get_by_role("link", name="Export result", exact=True).click()
            download = download_info.value
            assert download.suggested_filename == "native_result.txt"
            assert Path(download.path()).read_bytes() == b"native notebook result"
            checks.append("session_asset_download")
            page.screenshot(path=str(output / "agilab_native_python_view_desktop_preview.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(output / "agilab_native_python_view_mobile_preview.png"), full_page=True)
            checks.append("mobile_layout")
            context.close()
            browser.close()
        assert not errors, errors
        assert not failures, failures
        assert not external, external
        result = {"status": "passed", "checks": checks, "streamlit_distributions": distributions,
                  "browser_errors": errors, "request_failures": failures, "external_requests": external}
        (output / "agilab_native_python_view_browser_validation.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/agilab_native_python_view_browser_smoke"))
    run(parser.parse_args().output_dir.resolve())
