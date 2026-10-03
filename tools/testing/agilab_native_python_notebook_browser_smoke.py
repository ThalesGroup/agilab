#!/usr/bin/env python3
"""Exercise an exported Python view inside real JupyterLab with React and comms."""

from __future__ import annotations

import argparse
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import uuid

import nbformat
from playwright.sync_api import sync_playwright

from agilab_jupyter_widget_extension_fixture import stage_installed_widget_extensions


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "console_errors": [], "failed_requests": [], "http_errors": []}
    report["streamlit_distributions"] = [distribution.metadata["Name"] for distribution in distributions()
                                         if "streamlit" in distribution.metadata["Name"].lower()]
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="agilab-native-notebook-view-") as temporary:
            root = Path(temporary)
            project = root / "specialized_project"
            project.mkdir()
            (project / "pyproject.toml").write_text('[project]\nname="specialized-project"\nversion="0.0.0"\n')
            script = project / "specialized_python_view.py"
            script.write_text(
                "from pathlib import Path\nfrom agi_web import python_ui as st\n"
                "st.title('Specialized notebook view')\n"
                "from agi_web.python_view_session import current_session\n"
                "st.caption('Notebook project: ' + st.query_params.get('active_app', 'missing'))\n"
                "st.caption('Notebook route: ' + current_session().path)\n"
                "@st.fragment(run_every=1)\n"
                "def refresh_contract():\n"
                "    st.session_state['refresh_count'] = st.session_state.get('refresh_count', 0) + 1\n"
                "    st.caption('Notebook refresh count: ' + str(st.session_state['refresh_count']))\n"
                "refresh_contract()\n"
                "def submit():\n"
                "    st.session_state['runs'] = st.session_state.get('runs', 0) + 1\n"
                "    Path('notebook-submission.txt').write_text(str(st.session_state['runs']))\n"
                "st.text_input('Notebook label', key='label')\n"
                "st.button('Submit notebook view', key='submit', on_click=submit)\n"
                "st.metric('Notebook submissions', st.session_state.get('runs', 0))\n"
                "st.caption('Saved label: ' + st.session_state.get('label', ''))\n"
                "st.selectbox('Selected nullable option', [None, 'Other'], key='selected_nullable')\n"
                "st.selectbox('Initially empty nullable option', [None, 'Other'], index=None, key='empty_nullable')\n"
                "st.radio('Nullable radio', [None, 'Other'], key='nullable_radio')\n"
                "st.pills('Nullable pills', [None, 'Other'], key='nullable_pills')\n"
                "st.segmented_control('Nullable segmented', [None, 'Other'], key='nullable_segmented')\n"
                "with st.form('nullable_notebook_form'):\n"
                "    form_value = st.selectbox('Nullable form option', [None, 'Other'], index=None, key='nullable_form_option')\n"
                "    form_workers = st.number_input('Nullable form workers', min_value=1, max_value=4, value=2, key='nullable_form_workers')\n"
                "    if st.form_submit_button('Save nullable form'):\n"
                "        st.session_state['nullable_form_saved'] = (form_value, form_workers)\n"
                "st.caption('Nullable form saved: ' + repr(st.session_state.get('nullable_form_saved', 'not submitted')))\n"
                "st.download_button('Download notebook evidence', b'notebook-evidence', file_name='notebook-evidence.txt')\n"
                "st.graphviz_chart('digraph { Notebook -> React; React -> Python; }')\n"
                "import altair as alt\n"
                "st.altair_chart(alt.Chart(alt.Data(values=[{'x': 0, 'y': 1}, {'x': 1, 'y': 3}, {'x': 2, 'y': 2}]))"
                ".mark_line(point=True).encode(x='x:Q', y='y:Q').properties(width='container', height=180))\n"
                "st.markdown('Native **Markdown** with $E = mc^2$.')\n"
                "st.latex(r'\\int_0^1 x\\,dx = \\frac{1}{2}')\n"
            )
            payload = {"schema": "agilab.notebook_export.v1", "version": 1,
                       "project_name": project.name, "active_app": str(project),
                       "module_path": str(project), "artifact_dir": str(project), "stages": [],
                       "related_pages": [{"name": "specialized", "module": "specialized", "script_path": str(script)}]}
            from agilab.notebooks.notebook_helper_cell import _helper_cell
            cell = (
                "import builtins\n_original_import = builtins.__import__\n"
                "def _deny_streamlit(name, *args, **kwargs):\n"
                "    if name == 'streamlit' or name.startswith('streamlit.'):\n"
                "        raise AssertionError('Notebook imported Streamlit')\n"
                "    return _original_import(name, *args, **kwargs)\n"
                "builtins.__import__ = _deny_streamlit\n"
                + _helper_cell(payload)
                + "\nnotebook_view = render_analysis_page('specialized')\n"
            )
            notebook = root / "agilab_native_python_export_jupyter_smoke.ipynb"
            nbformat.write(nbformat.v4.new_notebook(
                cells=[nbformat.v4.new_code_cell(
                    "from IPython.display import HTML, display\n"
                    "display(HTML('<div id=\"agilab-ordinary-output\"><h1>Ordinary notebook output</h1>"
                    "<button>Ordinary notebook button</button><pre>Ordinary notebook code</pre></div>'))"
                ), nbformat.v4.new_code_cell(cell)],
                metadata={"kernelspec": {"name": "agilab-native-view", "display_name": "AGILAB native view", "language": "python"}},
            ), notebook)
            env = dict(os.environ, JUPYTER_CONFIG_DIR=str(root / "config"),
                       JUPYTER_DATA_DIR=str(root / "data"), JUPYTER_RUNTIME_DIR=str(root / "runtime"),
                       JUPYTERLAB_SETTINGS_DIR=str(root / "settings"))
            report["widget_extensions"] = stage_installed_widget_extensions(root / "data")
            kernel = root / "data/kernels/agilab-native-view"
            kernel.mkdir(parents=True)
            (kernel / "kernel.json").write_text(json.dumps({"argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                                                          "display_name": "AGILAB native view", "language": "python"}))
            config = root / "config/labconfig"
            config.mkdir(parents=True)
            (config / "page_config.json").write_text(json.dumps({"disabledExtensions": {"@jupyterlab/debugger-extension": True}}))
            settings = root / "settings/@jupyterlab/apputils-extension"
            settings.mkdir(parents=True)
            (settings / "notification.jupyterlab-settings").write_text(json.dumps({"fetchNews": "false", "checkForUpdates": False}))
            port, token = free_port(), uuid.uuid4().hex
            url = f"http://127.0.0.1:{port}/lab/tree/{notebook.name}?token={token}"
            with (output / "agilab_native_python_notebook_jupyter.log").open("w") as log:
                process = subprocess.Popen([sys.executable, "-m", "jupyterlab", "--ServerApp.ip=127.0.0.1",
                                            f"--ServerApp.port={port}", "--ServerApp.port_retries=0", "--ServerApp.open_browser=False",
                                            f"--ServerApp.root_dir={root}", f"--IdentityProvider.token={token}"],
                                           cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 45
                while True:
                    try:
                        with urlopen(url, timeout=1):
                            break
                    except Exception:
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError("The Jupyter host did not start.")
                        time.sleep(0.2)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1280, "height": 1000})
                    page.on("pageerror", lambda error: report["console_errors"].append(str(error)))
                    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)
                    page.on("requestfailed", lambda request: report["failed_requests"].append(request.url) if "ERR_ABORTED" not in str(request.failure) else None)
                    page.on("response", lambda response: report["http_errors"].append({"url": response.url, "status": response.status}) if response.status >= 400 else None)
                    try:
                        page.goto(url)
                        page.get_by_text("AGILAB native view | Idle", exact=True).wait_for(timeout=60000)
                        page.get_by_role("button", name=re.compile(r"^Run this cell and advance")).click(timeout=60000)
                        page.locator("#agilab-ordinary-output").wait_for(timeout=30000)
                        external_styles = """toolbar => {
                            const read = element => {const style = getComputedStyle(element); return {
                                padding:style.padding, borderRadius:style.borderRadius,
                                backgroundColor:style.backgroundColor, color:style.color,
                                fontFamily:style.fontFamily, fontSize:style.fontSize,
                            };};
                            return {toolbar: read(toolbar), ...Object.fromEntries(['body',
                                '#agilab-ordinary-output h1', '#agilab-ordinary-output button',
                                '#agilab-ordinary-output pre'].map(selector =>
                                    [selector, read(document.querySelector(selector))]))};
                        }"""
                        toolbar_button = page.get_by_role("button", name=re.compile(r"^Run this cell and advance")).element_handle()
                        report["external_styles_before"] = page.evaluate(external_styles, arg=toolbar_button)
                        page.get_by_role("button", name=re.compile(r"^Run this cell and advance")).click(timeout=60000)
                        app = page.locator(".jp-OutputArea .py-app")
                        app.get_by_role("heading", name="Specialized notebook view").wait_for(timeout=90000)
                        report["external_styles_after"] = page.evaluate(external_styles, arg=toolbar_button)
                        assert report["external_styles_before"] == report["external_styles_after"]
                        page.wait_for_function("""app => {
                            const count = app?.textContent.match(/Notebook refresh count: (\\d+)/);
                            return count && Number(count[1]) >= 2;
                        }""", arg=app.element_handle(), timeout=30000)
                        app.get_by_text("Notebook project: " + str(project.resolve()), exact=True).wait_for()
                        app.get_by_text("Notebook route: /", exact=True).wait_for()
                        label = app.get_by_role("textbox", name="Notebook label", exact=True)
                        label.fill("retained Python view")
                        label.press("Tab")
                        app.get_by_text("Saved label: retained Python view", exact=True).wait_for(timeout=30000)
                        app.get_by_role("button", name="Submit notebook view", exact=True).click()
                        app.locator(".py-metric strong").get_by_text("1", exact=True).wait_for(timeout=30000)
                        selected_nullable = app.get_by_label("Selected nullable option", exact=True)
                        empty_nullable = app.get_by_label("Initially empty nullable option", exact=True)
                        assert selected_nullable.locator("option:checked").inner_text() == "None"
                        assert empty_nullable.locator("option:checked").inner_text() == "Choose an option"
                        selected_nullable.select_option("1")
                        page.wait_for_function("select => select.value === '1'", arg=selected_nullable.element_handle())
                        selected_nullable.select_option("0")
                        empty_nullable.select_option("0")
                        # The same label is a real None option in each group;
                        # initially empty pills/segmented groups have no check.
                        groups = {label: app.locator(".py-control").filter(has_text=label)
                                  for label in ["Nullable radio", "Nullable pills", "Nullable segmented"]}
                        none_choice = lambda group: group.locator(".py-options label").filter(has_text=re.compile(r"^None$")).locator('input[type="radio"]')
                        assert none_choice(groups["Nullable radio"]).is_checked()
                        for label in ["Nullable pills", "Nullable segmented"]:
                            assert none_choice(groups[label]).is_checked() is False
                            none_choice(groups[label]).check()
                        form_choice = app.get_by_label("Nullable form option", exact=True)
                        form_choice.select_option("0")
                        form_workers = app.get_by_role("spinbutton", name="Nullable form workers", exact=True)
                        form_workers.fill("3")
                        form_workers.press("Tab")
                        app.get_by_text("Nullable form saved: 'not submitted'", exact=True).wait_for()
                        app.get_by_role("button", name="Save nullable form", exact=True).click()
                        app.get_by_text("Nullable form saved: (None, 3)", exact=True).wait_for(timeout=30000)
                        assert form_choice.locator("option:checked").inner_text() == "None"
                        form_choice.select_option("")
                        form_workers.fill("4")
                        form_workers.press("Tab")
                        app.get_by_text("Nullable form saved: (None, 3)", exact=True).wait_for()
                        app.get_by_role("button", name="Save nullable form", exact=True).click()
                        app.get_by_text("Nullable form saved: (None, 4)", exact=True).wait_for(timeout=30000)
                        assert form_choice.locator("option:checked").inner_text() == "Choose an option"
                        empty_nullable.select_option("")
                        # Survive a real Python rerender, rather than checking
                        # only the optimistic React selection immediately.
                        refresh_text = app.get_by_text(re.compile(r"^Notebook refresh count: \d+$")).inner_text()
                        refresh_count = int(refresh_text.rsplit(" ", 1)[-1])
                        page.wait_for_function("""({app, previous}) => {
                            const count = app.textContent.match(/Notebook refresh count: (\\d+)/);
                            return count && Number(count[1]) >= previous + 2;
                        }""", arg={"app": app.element_handle(), "previous": refresh_count}, timeout=30000)
                        assert selected_nullable.locator("option:checked").inner_text() == "None"
                        assert empty_nullable.locator("option:checked").inner_text() == "Choose an option"
                        for group in groups.values():
                            assert none_choice(group).is_checked()
                        assert (project / "notebook-submission.txt").read_text() == "1"
                        with page.expect_download() as download_info:
                            app.get_by_role("link", name="Download notebook evidence", exact=True).click()
                        download = download_info.value
                        download.save_as(output / "agilab_native_python_notebook_download.txt")
                        assert (output / "agilab_native_python_notebook_download.txt").read_bytes() == b"notebook-evidence"
                        app.locator(".py-graph svg").wait_for(timeout=30000)
                        assert "Notebook" in app.locator(".py-graph").inner_text()
                        vega = app.locator(".py-vega svg")
                        vega.wait_for(timeout=30000)
                        bounds = vega.bounding_box()
                        assert bounds and bounds["width"] > 0 and bounds["height"] > 0
                        assert vega.locator(".mark-line path").count() > 0
                        app.locator(".katex").first.wait_for(timeout=30000)
                        assert app.locator(".katex").count() >= 2
                        page.screenshot(path=str(output / "agilab_native_python_notebook_desktop.png"), full_page=True)
                        # Jupyter keeps its file browser open across viewport
                        # changes. Close that host panel before checking the view.
                        page.locator(".jp-SideBar .lm-TabBar-tab").first.click()
                        page.set_viewport_size({"width": 390, "height": 844})
                        app.scroll_into_view_if_needed()
                        app.get_by_role("heading", name="Specialized notebook view").wait_for()
                        assert app.evaluate("element => element.scrollWidth <= element.clientWidth + 2")
                        page.screenshot(path=str(output / "agilab_native_python_notebook_mobile.png"), full_page=True)
                        assert not report["console_errors"] and not report["failed_requests"] and not report["http_errors"], report
                        report.update(status="passed", streamlit_imports_blocked=True,
                                      checks=["exported_specialized_view", "widget_comm_callback", "persistent_input", "local_file_write", "nullable_selected_vs_empty", "nullable_radio_pills_segmented", "nullable_form_atomicity", "blob_download", "graphviz_wasm", "vega_local", "markdown_math", "auto_refresh_project_and_route", "external_notebook_styles_unchanged", "mobile_layout"])
                    except Exception:
                        page.screenshot(path=str(output / "agilab_native_python_notebook_failure.png"), full_page=True)
                        (output / "agilab_native_python_notebook_failure_dom.txt").write_text(page.locator("body").inner_text())
                        raise
                    finally:
                        browser.close()
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        (output / "agilab_native_python_notebook_browser_validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
