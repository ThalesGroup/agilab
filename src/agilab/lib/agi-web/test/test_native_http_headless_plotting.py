"""Keep threaded HTTP plots safe without changing notebook-only imports."""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from agi_web import react_python_host as host_module


def test_server_selects_agg_when_matplotlib_is_already_loaded(monkeypatch):
    selected = []
    monkeypatch.setenv("MPLBACKEND", "TkAgg")
    monkeypatch.setitem(
        sys.modules, "matplotlib",
        SimpleNamespace(use=lambda backend, *, force: selected.append((backend, force))),
    )
    server = host_module.ReactPythonServer(("127.0.0.1", 0), lambda: None)
    try:
        assert os.environ["MPLBACKEND"] == "Agg"
        assert selected == [("Agg", True)]
    finally:
        server.server_close()


def test_importing_host_preserves_notebook_backend():
    result = subprocess.run(
        [sys.executable, "-c", (
            "import os, sys; from agi_web import react_python_host; "
            "assert os.environ['MPLBACKEND'] == 'svg'; "
            "assert 'matplotlib' not in sys.modules"
        )],
        env={**os.environ, "MPLBACKEND": "svg"},
        text=True, capture_output=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_http_plot_survives_gui_backend_and_serves_two_pngs(tmp_path):
    pytest.importorskip("matplotlib")
    ready = tmp_path / "native_http_plot_ready_port.txt"
    script = tmp_path / "native_http_headless_plot_process.py"
    script.write_text(
        """from pathlib import Path
import sys
from agi_web import python_ui as ui
from agi_web.react_python_host import ReactPythonServer

def view():
    import matplotlib
    import matplotlib.pyplot as plt
    assert matplotlib.get_backend().lower() == "agg"
    fig, axis = plt.subplots()
    axis.plot([0, 1, 2], [0, 1, 0])
    ui.pyplot(fig, alt="A triangular test curve", width="stretch")
    plt.close(fig)

server = ReactPythonServer(("127.0.0.1", 0), view)
Path(sys.argv[1]).write_text(str(server.server_port))
try:
    server.serve_forever(poll_interval=0.01)
finally:
    server.server_close()
""",
        encoding="utf-8",
    )
    log_path = tmp_path / "native_http_headless_plot_process.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, str(script), str(ready)],
            env={**os.environ, "MPLBACKEND": "TkAgg"},
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            log.flush()
            assert ready.exists(), log_path.read_text()
            port = int(ready.read_text())
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            try:
                cookie = ""
                for _ in range(2):
                    connection.request("GET", "/api/view", headers={"Cookie": cookie})
                    response = connection.getresponse()
                    payload = json.loads(response.read())
                    assert response.status == 200, payload
                    if session_cookie := response.getheader("Set-Cookie"):
                        cookie = session_cookie.split(";", 1)[0]
                    assert not payload.get("error"), payload
                    images = [node for node in payload["nodes"]["main"] if node["kind"] == "image"]
                    assert len(images) == 1, payload
                    assert images[0]["props"]["alt"] == "A triangular test curve"
                    connection.request(
                        "GET", images[0]["props"]["urls"][0], headers={"Cookie": cookie},
                    )
                    image_response = connection.getresponse()
                    assert image_response.status == 200
                    assert image_response.read().startswith(b"\x89PNG\r\n\x1a\n")
                    assert process.poll() is None, log_path.read_text()
            finally:
                connection.close()
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
