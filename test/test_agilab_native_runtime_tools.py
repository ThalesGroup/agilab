from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_HOME = Path.home()


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(
        f"agilab_native_runtime_tools_{name}", REPO_ROOT / "tools" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("port", [None, 8912])
def test_apps_page_launcher_keeps_host_options_before_view_arguments(monkeypatch, tmp_path, port):
    launcher = _load_tool("apps_pages_launcher")
    captured = []

    def launch(command, *, env):
        captured.append(command)
        assert env["PYTHONUNBUFFERED"] == "1"
        return 17

    monkeypatch.setattr(launcher.subprocess, "call", launch)
    assert launcher.run_react("view_maps", tmp_path / "view.py", tmp_path / "project", port=port) == 17
    command = captured[0]
    assert command[command.index("--address") + 1] == "127.0.0.1"
    separator = command.index("--")
    assert command[separator + 1:] == ["--active-app", str(tmp_path / "project")]
    assert command[command.index("-m") + 1] == "agi_web.react_python_host"
    if port is None:
        assert "--port" not in command
    else:
        assert command.index("--port") < separator
        assert command[command.index("--port") + 1] == str(port)


def test_fresh_install_ui_extra_pins_own_packages_to_the_reviewed_checkout(monkeypatch, tmp_path):
    regression = _load_tool("regression_fresh_install")
    monkeypatch.setattr(regression, "_has_native_ui", lambda *_args, **_kwargs: False)
    captured = {}

    def install(command, *, env, cwd):
        assert cwd == REPO_ROOT
        override = Path(command[command.index("--overrides") + 1])
        captured["override"] = override
        captured["lines"] = override.read_text(encoding="utf-8").splitlines()
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="native source install")

    monkeypatch.setattr(regression, "_run", install)
    regression._ensure_ui_extra(tmp_path / "python", env={})
    assert captured["command"][-1] == ".[ui]"
    assert len(captured["lines"]) >= 30
    assert all(line.split(" @ ", 1)[1].startswith(REPO_ROOT.as_uri() + "/") for line in captured["lines"])
    assert any(line.startswith("agi-web @ ") for line in captured["lines"])
    assert any(line.startswith("agi-gui @ ") for line in captured["lines"])
    assert not captured["override"].exists()


def test_native_widget_robot_collects_and_operates_the_real_host(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    import json
    import os
    import socket
    import time
    import urllib.request

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        candidates = [REAL_HOME / "Library/Caches/ms-playwright", REAL_HOME / ".cache/ms-playwright", REAL_HOME / "AppData/Local/ms-playwright"]
        browser_cache = next((path for path in candidates if path.is_dir()), None)
        if browser_cache is None:
            pytest.skip("Playwright browser binaries are not installed")
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browser_cache))
    robot = _load_tool("agilab_widget_robot")
    python = Path(os.environ.get("AGILAB_NATIVE_ROBOT_HOST_PYTHON", sys.executable)).absolute()
    source = tmp_path / "agilab_native_widget_robot_fixture.py"
    source.write_text(
        """from agi_web import python_ui as st
from datetime import date
import importlib.util
assert importlib.util.find_spec("streamlit") is None
st.title("Native robot fixture")
st.checkbox("Enabled", key="enabled")
st.toggle("Mode", key="mode")
st.radio("Scale", ["Small", "Large"], key="scale")
selected = st.selectbox("Model", ["Alpha", "Beta"], key="model")
st.write(f"Selected: {selected}")
st.multiselect("Signals", ["x", "y"], key="signals")
st.slider("Threshold", 0, 10, 3, key="threshold")
st.text_input("Name", key="name")
st.date_input("Day", date(2026, 10, 3), key="day")
st.file_uploader("Input", type=["txt"], key="input")
st.dataframe({"value": [1, 2]})
st.download_button("Export proof", b"native proof bytes", file_name="agilab_native_robot_proof.txt")
with st.sidebar:
    st.button("Sidebar action", key="sidebar-action")
""",
        encoding="utf-8",
    )
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["AGILAB_DISABLE_BACKGROUND_SERVICES"] = "1"
    server = subprocess.Popen(
        [str(python), "-m", "agi_web.react_python_host", str(source), "--port", str(port), "--no-browser"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if server.poll() is not None:
                pytest.fail(server.communicate()[0])
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                    assert response.status == 200
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("Native robot fixture server did not become healthy")
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            page = browser.new_page(accept_downloads=True)
            page.goto(url)
            page.get_by_role("heading", name="Native robot fixture").wait_for()
            page.evaluate("""() => {
                const host = document.createElement("div");
                document.body.append(host);
                host.attachShadow({mode: "open"}).innerHTML = '<button>Shadow action</button>';
            }""")
            widgets = page.evaluate(robot.WIDGET_COLLECTOR_JS)
            assert {"radio", "selectbox", "multiselect", "slider", "file_uploader", "download_button", "date_input"} <= {item["kind"] for item in widgets}
            assert any(item["label"] == "Shadow action" for item in widgets)
            assert any(item["label"] == "Sidebar action" and item["scope"] == "sidebar" for item in widgets)
            page.get_by_role("button", name="Shadow action").focus()
            assert page.evaluate(robot.ACTIVE_FOCUS_STATE_JS)["label"] == "Shadow action"
            model = next(item for item in widgets if item["kind"] == "selectbox" and item["label"] == "Model")
            control, issue = robot._selectbox_widget_control(
                page, model, app_name="fixture", page_name="", timeout_ms=5000, max_options_per_widget=8
            )
            assert issue is None
            assert [choice.value for choice in control.choices] == ["Alpha", "Beta"]
            assert [choice.option_index for choice in control.choices] == [1, 2]
            robot._apply_widget_choice(page, control.choices[1], timeout_ms=5000)
            page.get_by_text("Selected: Beta", exact=True).wait_for()
            download = next(item for item in page.evaluate(robot.WIDGET_COLLECTOR_JS) if item["kind"] == "download_button")
            with page.expect_download() as pending:
                robot._widget_locator(page, download).click()
            exported = tmp_path / pending.value.suggested_filename
            pending.value.save_as(exported)
            assert exported.read_bytes() == b"native proof bytes"
            report_root = REPO_ROOT / "reports/agilab_native_widget_robot_browser_smoke"
            report_root.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(report_root / "agilab_native_widget_robot_browser_preview.png"))
            (report_root / "agilab_native_widget_robot_browser_validation.json").write_text(
                json.dumps({"status": "pass", "host_python": str(python), "streamlit": "absent",
                            "widget_kinds": sorted({item["kind"] for item in widgets}),
                            "native_select_callback": "Beta", "download_bytes_verified": True,
                            "shadow_dom_button_found": True, "sidebar_scope_verified": True}, indent=2) + "\n",
                encoding="utf-8",
            )
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
