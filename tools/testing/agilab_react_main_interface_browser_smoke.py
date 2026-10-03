#!/usr/bin/env python3
"""Exercise the actual main navigation with isolated project and Python page fixtures.

Existing Python page bodies are covered by their AppTests; this browser probe
validates the React/main_page boundary, URLs, project switching and session state.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import expect, sync_playwright


SOURCE = '''
from pathlib import Path
from types import SimpleNamespace
from agi_web import python_ui as st
import agilab.main_page as main
from agilab.about_page import bootstrap
from agilab.ui.page_project_selector import render_project_selector
from agilab.ui import react_project_workspace as workspace
from agilab.ui.react_analysis_workspace import render_analysis_workspace
from agilab.environment.environment_health import EnvironmentHealth, EnvironmentHealthCard

ROOT = Path(__file__).parent
NAMES = ["alpha_project", "beta_project"]
for name in NAMES:
    (ROOT / name).mkdir(exist_ok=True)

def make_env(name):
    return SimpleNamespace(app=name, target=name.removesuffix("_project"), AGILAB_EXPORT_ABS=ROOT / "exports", active_app=ROOT / name, apps_path=ROOT,
        builtin_apps_path=ROOT, projects=NAMES, get_projects=lambda *_: NAMES)

def ensure(*args, **kwargs):
    requested = Path(st.query_params.get("active_app", "alpha_project")).name
    current = st.session_state.get("env")
    if current is None or st.session_state.get("first_run"):
        current = make_env(requested if requested in NAMES else "alpha_project")
        st.session_state["env"] = current
        st.session_state["first_run"] = False
    return current

def body(label):
    st.header("Python " + label)
    env = st.session_state["env"]
    if label == "PROJECT":
        workspace.render_project_workspace(st, env)
    if label == "4_ANALYSIS":
        if st.query_params.get("current_page"):
            st.subheader("Python view: " + Path(st.query_params["current_page"]).stem)
        elif st.query_params.get("current_notebook"):
            st.subheader("Python notebook: " + Path(st.query_params["current_notebook"]).name)
        else:
            selection_key = "analysis_smoke_selection__" + env.app
            saved = st.session_state.setdefault(selection_key, {"views": ["geo"], "notebooks": ["lab.ipynb"]})
            selection = render_analysis_workspace(st, env,
                overview={"cards": [{"label": "Output files", "value": "3", "caption": "Local evidence"}],
                    "evidence": "Discovered evidence: predictions.csv", "message": ""},
                view_options={"geo": "Specialized map", "coordinates": "Coordinates", "curves": "Analysis curves"},
                view_routes={name: {"current_page": str(ROOT / env.app / (name + ".py"))}
                    for name in ("geo", "coordinates", "curves")},
                notebook_routes={"lab.ipynb": {"current_notebook": str(ROOT / env.app / "lab.ipynb")}},
                selected_views=saved["views"], selected_notebooks=saved["notebooks"])
            if selection:
                if not selection.get("discard"):
                    st.session_state[selection_key] = selection
                st.rerun()
    render_project_selector(st, NAMES, env.app, on_change=lambda _: None)
    st.text_input("Python input", key=f"{env.app}:app_args_form:notes")
    st.session_state.setdefault("pipeline_config_snapshot", env.app)
    st.caption("Pipeline cache: " + st.session_state["pipeline_config_snapshot"])
    if st.button("Python rerun"):
        st.session_state["smoke_clicks"] = st.session_state.get("smoke_clicks", 0) + 1
    st.caption("Project: " + env.app)
    st.caption("Clicks: " + str(st.session_state.get("smoke_clicks", 0)))

main._ensure_navigation_environment = ensure
main._render_about_page_entry = lambda: body("home")
main._render_notebook_agent_demo = lambda: body("notebook")
main._page_file_runner = lambda path: lambda: body(path.stem)
main._SETTINGS_PAGE_FILE = lambda: body("settings")
main.detect_agilab_version = lambda env: "test"
workspace.build_environment_health = lambda env: EnvironmentHealth(
    cards=(EnvironmentHealthCard("Manager env", "missing", "Install the environment", "incomplete"),
           EnvironmentHealthCard("Runs", env.app, "Project history", "ready"),
           EnvironmentHealthCard("Documentation", "<script>throw Error('unsafe')</script>", "Text only", "incomplete")),
    details=())
bootstrap.resolve_active_app_query_target = lambda env, name: ROOT / name if Path(name).name in NAMES else None
main.main()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/agilab-react-main-interface-browser-smoke"))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    errors, warnings, failed_requests, failed_responses = [], [], [], []
    import agi_web
    from importlib.metadata import distributions

    with tempfile.TemporaryDirectory(prefix="agilab-react-main-interface-") as temp:
        fixture = Path(temp) / "agilab_react_main_interface_fixture.py"
        fixture.write_text(SOURCE)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with (output / "agilab_react_main_interface_native_host.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "agi_web.react_python_host", str(fixture),
                "--address", "127.0.0.1", "--port", str(port), "--no-browser"], stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ))
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Native React fixture exited; inspect its log")
                    try:
                        urllib.request.urlopen(url + "/api/health", timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise TimeoutError("Native React health timeout")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        context = browser.new_context(viewport={"width": 1440, "height": 1100})
                        page = context.new_page()
                        page.set_default_timeout(15000)
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("console", lambda msg: (errors if msg.type == "error" else warnings).append({"message": msg.text, "location": msg.location}) if msg.type in ("error", "warning") else None)
                        page.on("requestfailed", lambda req: failed_requests.append({"url": req.url, "failure": req.failure}))
                        page.on("response", lambda response: failed_responses.append({"url": response.url, "status": response.status}) if response.status >= 400 else None)
                        page.goto(url)
                        shell = page.locator(".agilab-main-interface")
                        shell.get_by_role("heading", name="From a project to replayable results").wait_for(timeout=60000)
                        picker = shell.get_by_label("Project", exact=True)
                        assert picker.input_value() == "alpha_project"
                        shell.get_by_role("button", name="WORKFLOW", exact=True).first.click()
                        page.get_by_role("heading", name="Python 3_WORKFLOW").wait_for()
                        assert "/WORKFLOW" in page.url and "active_app=" in page.url
                        assert page.get_by_role("combobox").count() == 1
                        page.get_by_label("Python input").fill("alpha pipeline")
                        page.get_by_label("Python input").press("Enter")
                        page.get_by_role("button", name="Python rerun").click()
                        page.get_by_text("Clicks: 1", exact=True).wait_for()
                        assert page.get_by_label("Python input").input_value() == "alpha pipeline"
                        picker.select_option("beta_project")
                        page.get_by_text("Project: beta_project", exact=True).wait_for()
                        page.get_by_text("Pipeline cache: beta_project", exact=True).wait_for()
                        expect(page.get_by_label("Python input")).to_have_value("")
                        assert "/WORKFLOW" in page.url
                        page.get_by_role("button", name="Python rerun").click()
                        page.get_by_text("Clicks: 2", exact=True).wait_for()
                        assert picker.input_value() == "beta_project"
                        shell.get_by_role("button", name="PROJECT", exact=True).first.click()
                        workspace_view = page.get_by_role("region", name="Project workspace", exact=True)
                        workspace_view.get_by_role("heading", name="beta_project", exact=True).wait_for()
                        workspace_view.get_by_text("Needs attention", exact=True).first.wait_for()
                        expect(workspace_view.locator("script")).to_have_count(0)
                        page.screenshot(path=str(output / "agilab_react_project_workspace_desktop_preview.png"))
                        workspace_view.get_by_role("button", name="Run project", exact=False).click()
                        page.get_by_role("heading", name="Python 2_ORCHESTRATE").wait_for()
                        assert "/ORCHESTRATE" in page.url and "beta_project" in page.url
                        shell.get_by_role("button", name="PROJECT", exact=True).first.click()
                        workspace_view.get_by_role("heading", name="beta_project", exact=True).wait_for()
                        # Diagnostics update after a native Python rerun and a cold project switch.
                        page.get_by_role("button", name="Python rerun").click()
                        page.get_by_text("Clicks: 3", exact=True).wait_for()
                        workspace_view.get_by_role("heading", name="beta_project", exact=True).wait_for()
                        picker.select_option("alpha_project")
                        workspace_view.get_by_role("heading", name="alpha_project", exact=True).wait_for()
                        expect(workspace_view.get_by_text("alpha_project", exact=True)).to_have_count(2)
                        workspace_view.get_by_role("button", name="Analysis and notebook export", exact=False).click()
                        page.get_by_role("heading", name="Python 4_ANALYSIS").wait_for()
                        assert "/ANALYSIS" in page.url and "alpha_project" in page.url
                        expect(workspace_view).to_have_count(0)
                        analysis_view = page.get_by_role("region", name="Analysis workspace", exact=True)
                        analysis_view.get_by_role("heading", name="Explore alpha_project", exact=True).wait_for()
                        analysis_view.get_by_label("Coordinates", exact=True).check()
                        analysis_view.get_by_role("button", name="Discard changes", exact=True).click()
                        expect(analysis_view.get_by_label("Coordinates", exact=True)).not_to_be_checked()
                        analysis_view.get_by_role("status").get_by_text("Selection saved", exact=True).wait_for()
                        analysis_view.get_by_label("Coordinates", exact=True).check()
                        analysis_view.get_by_label("Analysis curves", exact=True).check()
                        analysis_view.get_by_role("status").get_by_text("Unsaved selection", exact=True).wait_for()
                        expect(analysis_view.get_by_role("button", name="Open Coordinates", exact=True)).to_be_disabled()
                        analysis_view.get_by_role("button", name="Save selection", exact=True).click()
                        analysis_view.get_by_role("status").get_by_text("Selection saved", exact=True).wait_for()
                        expect(analysis_view.get_by_role("button", name="Open Coordinates", exact=True)).to_be_enabled()
                        page.get_by_role("button", name="Python rerun").click()
                        expect(analysis_view.get_by_label("Coordinates", exact=True)).to_be_checked()
                        expect(analysis_view.get_by_label("Analysis curves", exact=True)).to_be_checked()
                        page.screenshot(path=str(output / "agilab_react_analysis_workspace_desktop_preview.png"))
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                        page.screenshot(path=str(output / "agilab_react_analysis_workspace_mobile_preview.png"))
                        page.set_viewport_size({"width": 1440, "height": 1100})
                        analysis_view.get_by_role("button", name="Open Specialized map", exact=True).click()
                        page.get_by_role("heading", name="Python view: geo", exact=True).wait_for()
                        assert "current_page=" in page.url and "alpha_project" in page.url
                        expect(analysis_view).to_have_count(0)
                        shell.get_by_role("button", name="ANALYSIS", exact=True).first.click()
                        analysis_view.get_by_role("heading", name="Explore alpha_project", exact=True).wait_for()
                        analysis_view.get_by_role("button", name="Open lab.ipynb", exact=True).click()
                        page.get_by_role("heading", name="Python notebook: lab.ipynb", exact=True).wait_for()
                        assert "current_notebook=" in page.url and "current_page=" not in page.url
                        shell.get_by_role("button", name="ANALYSIS", exact=True).first.click()
                        analysis_view.get_by_role("heading", name="Explore alpha_project", exact=True).wait_for()
                        analysis_view.get_by_role("button", name="Export app to notebook", exact=True).click()
                        page.get_by_role("heading", name="Python 3_WORKFLOW", exact=True).wait_for()
                        assert "/WORKFLOW" in page.url and "alpha_project" in page.url
                        assert "current_page=" not in page.url and "current_notebook=" not in page.url
                        shell.get_by_role("button", name="ANALYSIS", exact=True).first.click()
                        analysis_view.get_by_role("heading", name="Explore alpha_project", exact=True).wait_for()
                        analysis_view.get_by_label("Coordinates", exact=True).uncheck()
                        analysis_view.get_by_label("Analysis curves", exact=True).uncheck()
                        analysis_view.get_by_label("Specialized map", exact=True).uncheck()
                        analysis_view.get_by_label("lab.ipynb", exact=True).uncheck()
                        analysis_view.get_by_role("button", name="Save selection", exact=True).click()
                        analysis_view.get_by_role("status").get_by_text("Selection saved", exact=True).wait_for()
                        expect(analysis_view.get_by_role("button", name="Open Specialized map", exact=True)).to_be_disabled()
                        expect(analysis_view.get_by_role("button", name="Open lab.ipynb", exact=True)).to_be_disabled()
                        picker.select_option("beta_project")
                        analysis_view.get_by_role("heading", name="Explore beta_project", exact=True).wait_for()
                        expect(analysis_view.get_by_label("Coordinates", exact=True)).not_to_be_checked()
                        expect(analysis_view.get_by_label("Specialized map", exact=True)).to_be_checked()
                        expect(analysis_view.get_by_label("lab.ipynb", exact=True)).to_be_checked()
                        shell.get_by_role("button", name="PROJECT", exact=True).first.click()
                        workspace_view.get_by_role("heading", name="beta_project", exact=True).wait_for()
                        workspace_view.get_by_role("button", name="Open pipeline", exact=False).click()
                        page.get_by_role("heading", name="Python 3_WORKFLOW").wait_for()
                        shell.get_by_role("button", name="PROJECT", exact=True).first.click()
                        workspace_view.get_by_role("heading", name="beta_project", exact=True).wait_for()
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                        page.screenshot(path=str(output / "agilab_react_project_workspace_mobile_preview.png"))
                        page.set_viewport_size({"width": 1440, "height": 1100})
                        picker.select_option("beta_project")
                        workspace_view.get_by_role("heading", name="beta_project", exact=True).wait_for()
                        workspace_view.get_by_role("button", name="Edit project files", exact=False).click()
                        page.get_by_role("heading", name="Python PROJECT_EDITOR").wait_for()
                        assert "/PROJECT_EDITOR" in page.url
                        shell.get_by_text("Tools", exact=True).click()
                        shell.get_by_role("button", name="SETTINGS", exact=True).click()
                        page.get_by_role("heading", name="Python settings").wait_for()
                        shell.get_by_role("button", name="AGILAB home", exact=True).click()
                        shell.get_by_role("heading", name="From a project to replayable results").wait_for()
                        assert picker.input_value() == "beta_project"
                        shell.get_by_role("button", name="ANALYSIS", exact=True).first.click()
                        page.get_by_role("heading", name="Python 4_ANALYSIS").wait_for()
                        page.reload()
                        page.get_by_role("heading", name="Python 4_ANALYSIS").wait_for()
                        assert picker.input_value() == "beta_project"
                        # A new browser session keeps its own project and supports direct URLs.
                        second = browser.new_context()
                        other = second.new_page()
                        other.goto(url + "/WORKFLOW?active_app=alpha_project")
                        other.get_by_role("heading", name="Python 3_WORKFLOW").wait_for(timeout=60000)
                        assert other.get_by_label("Project", exact=True).input_value() == "alpha_project"
                        assert picker.input_value() == "beta_project"
                        second.close()
                        page.set_viewport_size({"width": 390, "height": 844})
                        shell.get_by_role("button", name="AGILAB home", exact=True).click()
                        shell.get_by_role("heading", name="From a project to replayable results").wait_for()
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                        page.screenshot(path=str(output / "agilab_react_main_interface_mobile_preview.png"), full_page=True)
                        page.set_viewport_size({"width": 1440, "height": 1100})
                        page.screenshot(path=str(output / "agilab_react_main_interface_desktop_preview.png"), full_page=True)
                    except Exception:
                        page.screenshot(path=str(output / "agilab_react_main_interface_native_browser_failure.png"), full_page=True)
                        (output / "agilab_react_main_interface_native_browser_failure_dom.txt").write_text(page.locator("body").inner_text())
                        (output / "agilab_react_main_interface_native_browser_failure.json").write_text(json.dumps({
                            "url": page.url, "errors": errors, "warnings": warnings,
                            "failed_requests": failed_requests, "failed_responses": failed_responses,
                        }, indent=2))
                        raise
                    finally:
                        browser.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    # Navigation can cancel the previous run's fetch; retain the exact evidence.
    cancellations = [req for req in failed_requests if req["failure"] == "net::ERR_ABORTED"]
    failures = [req for req in failed_requests if req not in cancellations]
    result = {"host": "agilab-react", "agi_web": agi_web.__version__,
              "streamlit_distributions": [d.metadata["Name"] for d in distributions()
                  if "streamlit" in d.metadata["Name"].lower()],
              "errors": errors, "warnings": warnings,
              "failed_requests": failures, "failed_responses": failed_responses,
              "navigation_cancellations": cancellations}
    (output / "agilab_react_main_interface_browser_validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    assert not errors and not warnings and not failures and not failed_responses, result
    assert not result["streamlit_distributions"], result


if __name__ == "__main__":
    main()
