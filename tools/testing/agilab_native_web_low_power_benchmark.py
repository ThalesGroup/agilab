#!/usr/bin/env python3
"""Measure real React navigation and table selection under Chromium CPU throttling.

The existing routing fixture deliberately replaces scientific page bodies. This
benchmark measures the shared frontend, not scientific compute or a physical PC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

import psutil
from playwright.sync_api import sync_playwright

from agilab_react_main_interface_browser_smoke import SOURCE

REPO = Path(__file__).resolve().parents[2]
TABLE_SOURCE = '''
    if label == "3_WORKFLOW":
        rows = [{"sample": i, **{f"channel {c}": {"value": i * c, "unit": "mV"} for c in range(8)}} for i in range(1000)]
        selection = st.dataframe(rows, key="benchmark_rows", on_select="rerun")
        st.caption("Selected rows: " + str(selection.selection.rows))
'''
IDENTITY_SOURCE = '''
import hashlib
import json
import agi_web
identity = {}
for name, module in (("agi_web", agi_web), ("python_ui", st), ("main_page", main)):
    path = Path(module.__file__).resolve()
    identity[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
(ROOT / "agilab_native_web_low_power_loaded_sources.json").write_text(json.dumps(identity))
'''


def summarize(samples):
    ordered = sorted(samples)
    if not ordered:
        raise ValueError("A benchmark phase needs samples")
    return {"samples": len(ordered), "median_ms": statistics.median(ordered),
            "p95_ms": ordered[math.ceil(.95 * len(ordered)) - 1], "max_ms": ordered[-1]}


def painted(page):
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-repo", type=Path, default=REPO)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--cpu-rates", type=float, nargs="+", default=[1, 4])
    parser.add_argument("--js-heap-limit-mib", type=int, default=256)
    args = parser.parse_args()
    repo = args.source_repo.resolve()
    if args.repetitions < 3 or any(rate < 1 for rate in args.cpu_rates) or args.js_heap_limit_mib < 128:
        parser.error("Use >=3 repetitions, CPU rates >=1 and a heap budget >=128 MiB")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "agilab_native_web_low_power_benchmark_validation.json"
    if receipt.exists():
        parser.error("Choose a new output directory; previous measurements are immutable")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(repo / "src"), str(repo / "src/agilab/lib/agi-web/src")))
    result = {"schema": "agilab.native_web.low_power_benchmark.v1", "status": "running",
              "source_repo": str(repo), "profiles": [], "external_requests": [], "errors": [],
              "limits": ["CPU slowdown simulates frontend pressure; it does not qualify a physical low-power computer.",
                         "The V8 heap budget is not a limit on system RAM or browser RSS.",
                         "Page bodies are routing fixtures; scientific execution is qualified separately."]}
    asset_path = repo / "src/agilab/lib/agi-web/src/agi_web/react_python_host_assets/agilab_react_python_host.js"
    expected_modules = {"agi_web": repo / "src/agilab/lib/agi-web/src/agi_web/__init__.py",
                        "python_ui": repo / "src/agilab/lib/agi-web/src/agi_web/python_ui.py",
                        "main_page": repo / "src/agilab/main_page.py"}
    result["source_files"] = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (*expected_modules.values(), asset_path)}
    try:
        with tempfile.TemporaryDirectory(prefix="agilab-low-power-benchmark-") as temporary:
            fixture = Path(temporary) / "agilab_native_web_low_power_benchmark_fixture.py"
            fixture_source = SOURCE.replace('    st.text_input("Python input"', TABLE_SOURCE + '    st.text_input("Python input"')
            fixture.write_text(fixture_source.replace("main.main()", IDENTITY_SOURCE + "\nmain.main()"))
            result["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            url = f"http://127.0.0.1:{port}"
            with (output / "agilab_native_web_low_power_benchmark_host.log").open("w") as log:
                server = subprocess.Popen([sys.executable, "-m", "agi_web.react_python_host", str(fixture),
                    "--address", "127.0.0.1", "--port", str(port), "--no-browser"], env=env, cwd=repo,
                    stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        if server.poll() is not None:
                            raise RuntimeError("Benchmark host exited; inspect its log")
                        try:
                            with urlopen(url + "/api/health", timeout=1) as response:
                                if response.status == 200:
                                    break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise TimeoutError("Benchmark host did not become healthy")
                    with urlopen(url + "/assets/agilab_react_python_host.js", timeout=10) as response:
                        served_sha256 = hashlib.sha256(response.read()).hexdigest()
                    if served_sha256 != result["source_files"][str(asset_path.relative_to(repo))]:
                        raise RuntimeError("The served JavaScript differs from the requested source")
                    result["served_javascript_sha256"] = served_sha256
                    with urlopen(url + "/api/view", timeout=30) as response:
                        preflight = json.loads(response.read())
                    if not (Path(temporary) / "agilab_native_web_low_power_loaded_sources.json").exists():
                        result["source_preflight_failure"] = preflight.get("nodes", {})
                        raise RuntimeError("The routing fixture failed before source identity was recorded")
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(args=[f"--js-flags=--max-old-space-size={args.js_heap_limit_mib}"])
                        try:
                            for rate in args.cpu_rates:
                                samples = {"cold_load": [], "navigation": [], "table_selection": []}
                                memories = []
                                for repeat in range(args.repetitions):
                                    context = browser.new_context(viewport={"width": 1280, "height": 900})
                                    try:
                                        def route_request(route):
                                            if urlsplit(route.request.url).hostname in ("127.0.0.1", "localhost"):
                                                route.continue_()
                                            else:
                                                result["external_requests"].append(route.request.url)
                                                route.abort()
                                        context.route("**/*", route_request)
                                        page = context.new_page()
                                        page.add_init_script("document.addEventListener('click', () => { window.__agilabBenchmarkClick = performance.now(); }, true)")
                                        page.on("pageerror", lambda error: result["errors"].append(str(error)))
                                        cdp = context.new_cdp_session(page)
                                        cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
                                        cdp.send("Performance.enable")
                                        start = time.perf_counter()
                                        page.goto(url)
                                        shell = page.locator(".agilab-main-interface")
                                        shell.get_by_role("heading", name="Run a project, explore its results").wait_for(timeout=60000)
                                        painted(page)
                                        samples["cold_load"].append((time.perf_counter() - start) * 1000)
                                        loaded = json.loads((Path(temporary) / "agilab_native_web_low_power_loaded_sources.json").read_text())
                                        for name, path in expected_modules.items():
                                            expected = {"path": str(path.resolve()), "sha256": result["source_files"][str(path.relative_to(repo))]}
                                            if loaded.get(name) != expected:
                                                raise RuntimeError(f"Unexpected loaded module: {name}")
                                        result["loaded_sources"] = loaded
                                        for target, heading in [("PROJECT", "Python PROJECT"), ("ORCHESTRATE", "Python 2_ORCHESTRATE"),
                                                                ("WORKFLOW", "Python 3_WORKFLOW"), ("ANALYSIS", "Python 4_ANALYSIS"),
                                                                ("WORKFLOW", "Python 3_WORKFLOW")]:
                                            shell.get_by_role("button", name=target, exact=True).first.click()
                                            page.get_by_role("heading", name=heading, exact=True).wait_for()
                                            painted(page)
                                            samples["navigation"].append(page.evaluate("performance.now() - window.__agilabBenchmarkClick"))
                                        for selected in (True, False):
                                            checkbox = page.get_by_label("Select row 1", exact=True)
                                            checkbox.click()
                                            page.get_by_text("Selected rows: " + ("[0]" if selected else "[]"), exact=True).wait_for()
                                            page.locator(".py-app[aria-busy=false]").wait_for()
                                            painted(page)
                                            assert checkbox.is_checked() == selected
                                            samples["table_selection"].append(page.evaluate("performance.now() - window.__agilabBenchmarkClick"))
                                        memories.append({"heap": cdp.send("Runtime.getHeapUsage"),
                                            "owned_process_rss_bytes": sum(child.memory_info().rss for child in psutil.Process().children(recursive=True) if child.is_running()),
                                            "dom_cells": page.locator(".py-table td").count(),
                                            "performance": cdp.send("Performance.getMetrics")["metrics"]})
                                        if repeat == 0:
                                            next_page = page.get_by_role("button", name="Next table page", exact=True)
                                            if next_page.count():
                                                for _ in range(9):
                                                    next_page.click()
                                                page.get_by_label("Select row 1000", exact=True).wait_for()
                                                assert next_page.is_disabled()
                                                for _ in range(9):
                                                    page.get_by_role("button", name="Previous table page", exact=True).click()
                                                page.get_by_label("Select row 1", exact=True).wait_for()
                                                result.setdefault("pagination_checks", []).append({"cpu_slowdown": rate,
                                                    "last_row_reachable": 1000, "returned_to_first_page": True})
                                            page.screenshot(path=str(output / f"agilab_native_web_low_power_cpu_{rate:g}_preview.png"))
                                    finally:
                                        context.close()
                                result["profiles"].append({"cpu_slowdown": rate, "js_heap_limit_mib": args.js_heap_limit_mib,
                                    "measurements": {name: summarize(values) for name, values in samples.items()},
                                    "raw_ms": samples, "memory_samples": memories})
                        finally:
                            browser.close()
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
                    result["server_exit_code"] = server.returncode
        if result["errors"] or result["external_requests"]:
            raise RuntimeError("Benchmark recorded a frontend error or an external request")
        result["status"] = "passed"
    except Exception as error:
        result["status"] = "failed"
        result["failure"] = repr(error)
        raise
    finally:
        receipt.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"status": result["status"], "receipt": str(receipt), "profiles": len(result["profiles"])}))


if __name__ == "__main__":
    main()
