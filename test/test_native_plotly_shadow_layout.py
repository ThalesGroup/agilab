"""Exercise the shipped Python-view renderer and Plotly in real shadow DOMs."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "src/agilab/lib/agi-web/src/agi_web/react_python_host_assets"
HEIGHTS = {"a": (320, 450), "b": (520, 450)}


def _payload(name: str, revision: int) -> dict:
    def node(identifier: str, kind: str, props: dict) -> dict:
        return {"id": identifier, "kind": kind, "props": props, "children": []}

    plots = []
    for index, height in enumerate(HEIGHTS[name]):
        layout = {"title": {"text": f"{name}: chart {index}"},
                  "margin": {"l": 40, "r": 20, "t": 50, "b": 40}}
        if index == 0:
            layout["height"] = height
        plots.append(node(f"{name}-plot-{index}", "plotly_chart", {
            "library": "/plotly.js",
            "figure": {"data": [{"type": "scatter", "mode": "lines+markers",
                                 "x": [0, 1, 2], "y": [revision, revision + 1, revision + 2]}],
                       "layout": layout},
        }))
    return {"revision": revision, "csrf_token": "shadow-layout-regression", "path": "/",
            "query": {}, "config": {"page_title": "Shadow layout regression"},
            "nodes": {"main": [*plots, node(f"{name}-refresh", "button", {
                "label": f"Refresh {name}", "disabled": False})], "sidebar": []}}


HTML = b"""<!doctype html><html><head><meta charset="utf-8">
<link rel="icon" href="data:,"></head><body>
<script type="module">
import {mountPythonView} from '/host.js';
const cleanups = new Map();
const request = async (url, options) => {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`Fixture HTTP ${response.status}: ${url}`);
  return response.json();
};
const css = await (await fetch('/host.css')).text();
for (const name of ['a', 'b']) {
  const host = document.createElement('div'); host.id = `view-${name}`;
  document.body.appendChild(host);
  const root = host.attachShadow({mode: 'open'});
  const style = document.createElement('style'); style.textContent = css.replaceAll(':root', ':host');
  const view = document.createElement('div'); root.append(style, view);
  const endpoint = `/api/view?name=${name}`;
  const initialPayload = await request(endpoint);
  cleanups.set(name, mountPythonView(view, {initialPayload, transport: {
    render: () => request(endpoint),
    action: action => request(`/api/action?name=${name}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(action)
    })
  }}));
}
window.cleanupView = name => {
  cleanups.get(name)(); cleanups.delete(name);
  document.getElementById(`view-${name}`).remove();
};
window.fixtureReady = true;
</script></body></html>"""


@contextmanager
def _local_renderer():
    # The override also lets the regression exercise a preserved pre-fix bundle.
    host_asset = Path(os.environ.get("AGILAB_PLOTLY_SHADOW_HOST_ASSET",
                                    ASSETS / "agilab_react_python_host.js"))
    resources = {
        "/": ("text/html", HTML),
        "/host.js": ("text/javascript", host_asset.read_bytes()),
        "/host.css": ("text/css", (ASSETS / "agilab_react_python_host.css").read_bytes()),
        "/plotly.js": ("text/javascript", files("plotly").joinpath("package_data/plotly.min.js").read_bytes()),
    }
    revisions = {"a": 1, "b": 1}
    actions = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status: int, content_type: str, body: bytes):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            target = urlsplit(self.path)
            if target.path == "/api/view":
                name = parse_qs(target.query)["name"][0]
                with lock:
                    payload = _payload(name, revisions[name])
                self.reply(200, "application/json", json.dumps(payload).encode())
            elif target.path in resources:
                content_type, body = resources[target.path]
                self.reply(200, content_type, body)
            else:
                self.reply(404, "text/plain", b"Unknown fixture resource")

        def do_POST(self):
            target = urlsplit(self.path)
            name = parse_qs(target.query)["name"][0]
            action = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                assert target.path == "/api/action"
                assert action["id"] == f"{name}-refresh" and action["value"] is True
                assert action["revision"] == revisions[name]
                assert action["csrf_token"] == "shadow-layout-regression"
                actions.append((name, action))
                revisions[name] += 1
                payload = _payload(name, revisions[name])
            self.reply(200, "application/json", json.dumps(payload).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", actions
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


MEASURE = """names => Object.fromEntries(names.map(name => {
  const root = document.getElementById(`view-${name}`).shadowRoot;
  const charts = [...root.querySelectorAll('.py-plot')].map(plot => {
    const box = plot.getBoundingClientRect();
    return {height: box.height, width: box.width, values: [...plot.data[0].y],
      svgs: [...plot.querySelectorAll('svg.main-svg')].map(svg => {
        const rect = svg.getBoundingClientRect();
        return {position: getComputedStyle(svg).position, top: rect.top - box.top,
          left: rect.left - box.left, height: rect.height, width: rect.width};
      })};
  });
  return [name, charts];
}))"""


def _assert_layout(measurements: dict, names: tuple[str, ...]):
    for name in names:
        assert len(measurements[name]) == 2
        for chart, expected_height in zip(measurements[name], HEIGHTS[name], strict=True):
            assert abs(chart["height"] - expected_height) <= 1, chart
            assert chart["width"] > 100, chart
            assert len(chart["svgs"]) >= 2, chart
            first = chart["svgs"][0]
            for svg in chart["svgs"]:
                assert svg["position"] == "absolute", chart
                assert abs(svg["top"] - first["top"]) <= 1, chart
                assert abs(svg["left"] - first["left"]) <= 1, chart
                assert abs(svg["height"] - expected_height) <= 1, chart
                assert abs(svg["width"] - chart["width"]) <= 2, chart


def _stable_layout(page, names=("a", "b")):
    page.wait_for_function("""names => names.every(name => {
      const plots = [...document.getElementById(`view-${name}`).shadowRoot.querySelectorAll('.py-plot')];
      return plots.length === 2 && plots.every(plot => plot.data && plot._fullLayout &&
        plot.querySelectorAll('svg.main-svg').length >= 2 &&
        Math.abs(Number(plot.querySelector('svg.main-svg').getAttribute('width')) - plot.clientWidth) <= 2);
    })""", arg=list(names))
    samples = page.evaluate("""async names => {
      const measure = """ + MEASURE + """;
      const samples = [measure(names)];
      for (let frame = 0; frame < 20; frame++) {
        await new Promise(resolve => requestAnimationFrame(resolve));
        samples.push(measure(names));
      }
      return samples;
    }""", list(names))
    for sample in samples:
        _assert_layout(sample, names)
        for name in names:
            for before, after in zip(samples[0][name], sample[name], strict=True):
                assert abs(before["height"] - after["height"]) <= 1
    return samples[-1]


def test_native_plotly_shadow_layout_resize_update_and_cleanup():
    playwright = pytest.importorskip("playwright.sync_api")
    errors, requests, failures, http_errors = [], [], [], []
    with _local_renderer() as (origin, actions), playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except playwright.Error as exc:
            if "Executable doesn't exist" not in str(exc):
                raise
            browser = runtime.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")

        def guard(route):
            parsed = urlsplit(route.request.url)
            if parsed.scheme in {"http", "https"} and not route.request.url.startswith(origin + "/"):
                requests.append(route.request.url)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        context.route("**/*", guard)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text)
                if message.type == "error" or "ResizeObserver" in message.text else None)
        page.on("requestfailed", lambda request: failures.append((request.url, request.failure)))
        page.on("response", lambda response: http_errors.append((response.url, response.status))
                if response.status >= 400 else None)
        try:
            page.goto(origin, wait_until="networkidle")
            page.wait_for_function("window.fixtureReady === true")
            initial = _stable_layout(page)
            page.set_viewport_size({"width": 640, "height": 800})
            narrow = _stable_layout(page)
            for name in HEIGHTS:
                assert narrow[name][0]["width"] < initial[name][0]["width"] - 100
            page.set_viewport_size({"width": 1440, "height": 800})
            wide = _stable_layout(page)
            for name in HEIGHTS:
                assert wide[name][0]["width"] > narrow[name][0]["width"] + 100

            def refresh(name):
                with page.expect_response(origin + f"/api/action?name={name}") as reply:
                    page.get_by_role("button", name=f"Refresh {name}", exact=True).click()
                assert reply.value.status == 200
                page.wait_for_function("""name => [...document.getElementById(`view-${name}`)
                  .shadowRoot.querySelectorAll('.py-plot')].every(plot => plot.data?.[0]?.y[0] === 2)""",
                                       arg=name)

            refresh("a")
            updated = _stable_layout(page)
            assert all(chart["values"] == [2, 3, 4] for chart in updated["a"])
            assert all(chart["values"] == [1, 2, 3] for chart in updated["b"])
            page.evaluate("window.cleanupView('a')")
            assert page.locator("#view-a").count() == 0
            survivor = _stable_layout(page, ("b",))
            assert all(chart["values"] == [1, 2, 3] for chart in survivor["b"])
            refresh("b")
            survivor = _stable_layout(page, ("b",))
            assert all(chart["values"] == [2, 3, 4] for chart in survivor["b"])
            assert [name for name, _ in actions] == ["a", "b"]
            page.evaluate("window.cleanupView('b')")
            assert page.locator("#view-b").count() == 0
            assert not errors, errors
            assert not requests, requests
            assert not failures, failures
            assert not http_errors, http_errors
        finally:
            context.close()
            browser.close()
