#!/usr/bin/env python3
"""Exercise the packaged React views in real Streamlit and JupyterLab hosts.

Run with the repository UI/notebook environment plus playwright and jupyterlab.
Servers, kernels and config use task-owned temporary paths; no user server is stopped.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

import nbformat
from playwright.sync_api import sync_playwright


DATA = """
from agi_web import coordinate_map_component, analysis_curves_component
positions = [
    {"latitude": 48, "longitude": 2, "id": "001", "flight": "A"},
    {"latitude": 49, "longitude": 3, "id": "002", "flight": "A"},
    {"latitude": 47, "longitude": 1, "id": "003", "flight": "B"},
]
map_component = coordinate_map_component(positions, label="id", group="flight",
    title="Primary positions", component_id="primary-map")
secondary_component = coordinate_map_component(positions[:2], label="id",
    title="Secondary positions", component_id="secondary-map")
curve_component = analysis_curves_component([
    {"date": "2026-01-01", "actual": 10, "predicted": 11},
    {"date": "2026-01-02", "actual": 12, "predicted": 13},
    {"date": "2026-01-03", "actual": 14, "predicted": 15},
], x="date", series=("actual", "predicted"),
    labels={"actual": "Observed", "predicted": "Predicted"},
    title="Analysis curves", component_id="analysis-curves")
numeric_component = analysis_curves_component([
    {"x": .0001, "y": .0001}, {"x": .0002, "y": .0002}, {"x": .0003, "y": .0003},
], x="x", series=("y",), x_type="number", title="Small values", component_id="small-values")
seconds_component = analysis_curves_component([
    {"x": f"2026-01-01T00:00:0{i}Z", "y": i} for i in range(3)
], x="x", series=("y",), title="Second resolution", component_id="seconds")
millis_component = analysis_curves_component([
    {"x": f"2026-01-01T00:00:00.{i:03d}Z", "y": i} for i in range(3)
], x="x", series=("y",), title="Millisecond resolution", component_id="milliseconds")
"""

STREAMLIT_SOURCE = (
    DATA
    + """
import json
import streamlit as st
from agi_web import render_streamlit
st.set_page_config(page_title="AGILAB React host smoke", layout="wide")
map_state = render_streamlit(map_component)
render_streamlit(secondary_component, width="320px")
curve_state = render_streamlit(curve_component)
for component in (numeric_component, seconds_component, millis_component):
    render_streamlit(component)
st.code(json.dumps({"map": map_state.selection or {}, "curves": curve_state.selection or {}}, sort_keys=True))
st.button("Refresh same recorded data")
"""
)

NOTEBOOK_SOURCE = (
    DATA
    + """
import html, json
import ipywidgets as widgets
from IPython.display import display
from agi_web import render_notebook
map_widget = render_notebook(map_component)
secondary_widget = render_notebook(secondary_component, width="320px")
curve_widget = render_notebook(curve_component)
precision_widgets = [render_notebook(component)
    for component in (numeric_component, seconds_component, millis_component)]
readout = widgets.HTML()
def read_selection(_=None):
    value = json.dumps({"map": map_widget.selection, "curves": curve_widget.selection}, sort_keys=True)
    readout.value = '<pre data-role="python-selection">' + html.escape(value) + '</pre>'
read_button = widgets.Button(description="Read Python selection")
read_button.on_click(read_selection)
def replace_data(_):
    map_widget.component = coordinate_map_component(positions[:2], label="id", group="flight",
        title="Primary positions", component_id="primary-map").as_dict()
replace_button = widgets.Button(description="Replace recorded data")
replace_button.on_click(replace_data)
read_selection()
display(map_widget, secondary_widget, curve_widget, *precision_widgets, read_button, replace_button, readout)
"""
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_server(url: str, process: subprocess.Popen, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Task-owned server exited; inspect the host log")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("Task-owned server did not become ready")


def wait_state(page, host, predicate):
    deadline = time.monotonic() + 15
    value = None
    while time.monotonic() < deadline:
        if host == "jupyter":
            page.get_by_role("button", name="Read Python selection", exact=True).click()
            page.wait_for_timeout(200)
            text = page.locator('pre[data-role="python-selection"]').inner_text()
        else:
            text = page.locator('[data-testid="stCode"] pre').inner_text()
        value = json.loads(text)
        if predicate(value):
            return value
        page.wait_for_timeout(200)
    raise AssertionError(f"Python selection did not synchronize: {value}")


def exercise(page, host, output):
    from playwright.sync_api import expect

    primary = page.locator('[data-component-id="primary-map"]')
    secondary = page.locator('[data-component-id="secondary-map"]')
    curves = page.locator('[data-component-id="analysis-curves"]')
    expect(primary).to_be_visible(timeout=60000)
    expect(primary.locator("circle")).to_have_count(3)
    expect(secondary.locator("circle")).to_have_count(2)
    expect(curves.locator("circle")).to_have_count(6)
    assert abs(secondary.bounding_box()["width"] - 320) <= 1
    for component_id in ("small-values", "seconds", "milliseconds"):
        region = page.locator(f'[data-component-id="{component_id}"]')
        expect(region.locator("circle")).to_have_count(3)
        tick_labels = region.locator("svg text").all_text_contents()[:10]
        assert len(set(tick_labels[::2])) == 5, (component_id, tick_labels)
        assert len(set(tick_labels[1::2])) == 5, (component_id, tick_labels)
    primary.get_by_role("button", name="Position 001", exact=True).press("Enter")
    selected = wait_state(page, host, lambda state: state["map"].get("label") == "001")
    assert selected["map"]["latitude"] == 48 and selected["map"]["longitude"] == 2
    primary.get_by_label("Map group", exact=True).select_option("0")
    wait_state(page, host, lambda state: state["map"] == {})
    expect(primary.locator("circle")).to_have_count(2)
    expect(secondary.locator("circle")).to_have_count(2)
    if host == "streamlit":
        page.get_by_role(
            "button", name="Refresh same recorded data", exact=True
        ).click()
        expect(primary.get_by_label("Map group", exact=True)).to_have_value("0")
        expect(primary.locator("circle")).to_have_count(2)
    primary.get_by_role("button", name="Reset view", exact=True).click()
    expect(primary.locator("circle")).to_have_count(3)
    curves.get_by_role("button", name="Observed 2026-01-01", exact=True).click()
    wait_state(page, host, lambda state: state["curves"].get("series") == "actual")
    curves.get_by_label("Predicted", exact=True).uncheck()
    wait_state(page, host, lambda state: state["curves"] == {})
    expect(curves.locator("circle")).to_have_count(3)
    curves.get_by_label("Range start", exact=True).press("ArrowRight")
    expect(curves.locator("circle")).to_have_count(2)
    curves.get_by_label("Range start", exact=True).press("ArrowRight")
    expect(curves.locator("circle")).to_have_count(1)
    date_ticks = curves.locator("svg text").all_text_contents()[::2][:5]
    assert len(set(date_ticks)) == 5, date_ticks
    curves.get_by_role("button", name="Reset view", exact=True).click()
    expect(curves.locator("circle")).to_have_count(6)
    expect(curves.get_by_label("Range start", exact=True)).to_have_value("0")
    if host == "jupyter":
        primary.get_by_role("button", name="Position 001", exact=True).click()
        wait_state(page, host, lambda state: state["map"].get("row") == 0)
        page.get_by_role("button", name="Replace recorded data", exact=True).click()
        expect(primary.locator("circle")).to_have_count(2)
        wait_state(page, host, lambda state: state["map"] == {})
    for name, region in (("coordinates", primary), ("curves", curves)):
        region.screenshot(
            path=str(output / f"agilab_shared_react_{host}_{name}_preview.png")
        )
    page.screenshot(
        path=str(output / f"agilab_shared_react_{host}_preview.png"), full_page=True
    )
    return {
        "selection_roundtrip": True,
        "filters_ranges_reset": True,
        "instances_isolated": True,
        "payload_change_reset": host == "jupyter",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/agilab-shared-react-browser-smoke"),
    )
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    processes, logs = [], []
    import streamlit
    import anywidget
    import jupyterlab

    results = {
        "versions": {
            "streamlit": streamlit.__version__,
            "anywidget": anywidget.__version__,
            "jupyterlab": jupyterlab.__version__,
        }
    }
    try:
        with tempfile.TemporaryDirectory(prefix="agilab-shared-react-hosts-") as temp:
            root = Path(temp)
            streamlit_file = root / "agilab_shared_react_streamlit_smoke.py"
            streamlit_file.write_text(STREAMLIT_SOURCE)
            notebook_file = root / "agilab_shared_react_jupyter_smoke.ipynb"
            notebook = nbformat.v4.new_notebook(
                cells=[nbformat.v4.new_code_cell(NOTEBOOK_SOURCE)],
                metadata={
                    "kernelspec": {
                        "name": "agilab-react-smoke",
                        "display_name": "AGILAB React smoke",
                        "language": "python",
                    }
                },
            )
            nbformat.write(notebook, notebook_file)
            env = dict(
                os.environ,
                JUPYTER_CONFIG_DIR=str(root / "config"),
                JUPYTER_DATA_DIR=str(root / "data"),
                JUPYTER_RUNTIME_DIR=str(root / "runtime"),
                JUPYTERLAB_SETTINGS_DIR=str(root / "settings"),
            )
            # This task kernel does not start a debugger session; keep the
            # separate Jupyter debugger plugin outside the host smoke.
            labconfig = root / "config/labconfig"
            labconfig.mkdir(parents=True)
            (labconfig / "page_config.json").write_text(
                json.dumps(
                    {"disabledExtensions": {"@jupyterlab/debugger-extension": True}}
                )
            )
            kernel = root / "data/kernels/agilab-react-smoke"
            kernel.mkdir(parents=True)
            (kernel / "kernel.json").write_text(
                json.dumps(
                    {
                        "argv": [
                            sys.executable,
                            "-m",
                            "ipykernel_launcher",
                            "-f",
                            "{connection_file}",
                        ],
                        "display_name": "AGILAB React smoke",
                        "language": "python",
                    }
                )
            )
            settings = root / "settings/@jupyterlab/apputils-extension"
            settings.mkdir(parents=True)
            (settings / "notification.jupyterlab-settings").write_text(
                json.dumps({"fetchNews": "false", "checkForUpdates": False})
            )
            streamlit_port, jupyter_port, token = (
                free_port(),
                free_port(),
                uuid.uuid4().hex,
            )
            commands = {
                "streamlit": [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(streamlit_file),
                    "--server.address=127.0.0.1",
                    f"--server.port={streamlit_port}",
                    "--server.headless=true",
                    "--browser.gatherUsageStats=false",
                ],
                "jupyter": [
                    sys.executable,
                    "-m",
                    "jupyterlab",
                    "--ServerApp.ip=127.0.0.1",
                    f"--ServerApp.port={jupyter_port}",
                    "--ServerApp.port_retries=0",
                    "--ServerApp.open_browser=False",
                    f"--ServerApp.root_dir={root}",
                    f"--IdentityProvider.token={token}",
                ],
            }
            urls = {
                "streamlit": f"http://127.0.0.1:{streamlit_port}",
                "jupyter": f"http://127.0.0.1:{jupyter_port}/lab/tree/{notebook_file.name}?token={token}",
            }
            for host, command in commands.items():
                log = (output / f"agilab_shared_react_{host}_host.log").open("w")
                logs.append(log)
                process = subprocess.Popen(
                    command, env=env, cwd=root, stdout=log, stderr=subprocess.STDOUT
                )
                processes.append(process)
                wait_server(urls[host], process)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for host, url in urls.items():
                        page = browser.new_page(
                            viewport={"width": 1280, "height": 1100}
                        )
                        errors, warnings, failed, canceled, http_errors, external = (
                            [],
                            [],
                            [],
                            [],
                            [],
                            [],
                        )
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on(
                            "console",
                            lambda message: (
                                errors.append(message.text)
                                if message.type == "error"
                                else None
                            ),
                        )
                        page.on(
                            "console",
                            lambda message: (
                                warnings.append(message.text)
                                if message.type == "warning"
                                else None
                            ),
                        )

                        def request_failed(request):
                            entry = {"url": request.url, "reason": request.failure}
                            # Jupyter replaces pending workspace autosaves.
                            if (
                                request.failure == "net::ERR_ABORTED"
                                and "/lab/api/workspaces/" in request.url
                            ):
                                canceled.append(entry)
                            else:
                                failed.append(entry)

                        page.on("requestfailed", request_failed)
                        page.on(
                            "response",
                            lambda response: (
                                http_errors.append(
                                    {"url": response.url, "status": response.status}
                                )
                                if response.status >= 400
                                else None
                            ),
                        )
                        page.on(
                            "request",
                            lambda request: (
                                external.append(request.url)
                                if request.url.startswith(("http:", "https:"))
                                and not request.url.startswith("http://127.0.0.1:")
                                else None
                            ),
                        )
                        page.goto(url)
                        if host == "jupyter":
                            page.locator(
                                ".jp-Notebook .jp-InputArea-editor"
                            ).first.click(timeout=60000)
                            page.get_by_role(
                                "button", name="AGILAB React smoke | Idle", exact=True
                            ).wait_for(timeout=60000)
                            page.get_by_role(
                                "button", name=re.compile(r"^Run this cell and advance")
                            ).click()
                        results[host] = {}
                        try:
                            results[host].update(exercise(page, host, output))
                            assert (
                                not errors
                                and not failed
                                and not http_errors
                                and not external
                            ), results[host]
                        except Exception:
                            page.screenshot(
                                path=str(
                                    output / f"agilab_shared_react_{host}_failure.png"
                                ),
                                full_page=True,
                            )
                            (
                                output / f"agilab_shared_react_{host}_failure_dom.txt"
                            ).write_text(page.locator("body").inner_text())
                            raise
                        finally:
                            results[host].update(
                                console_errors=errors,
                                console_warnings=warnings,
                                failed_requests=failed,
                                canceled_workspace_requests=canceled,
                                http_errors=http_errors,
                                external_requests=external,
                            )
                            page.close()
                finally:
                    browser.close()
        results["status"] = "pass"
    except Exception as exc:
        results.update(status="fail", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()
        (output / "agilab_shared_react_browser_validation.json").write_text(
            json.dumps(results, indent=2) + "\n"
        )
        print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
