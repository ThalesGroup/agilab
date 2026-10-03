#!/usr/bin/env python3
"""Verify an exported native host in a real browser without installed site packages."""
from __future__ import annotations

import argparse
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

from agilab.bridge_cli import export_hf_space


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "console_errors": [], "failed_requests": [],
              "http_errors": [], "external_requests": [],
              "streamlit_distributions": [item.metadata["Name"] for item in distributions()
                                         if "streamlit" in item.metadata["Name"].lower()]}
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="agilab-native-portable-export-") as temporary:
            root = Path(temporary)
            project = root / "portable_project"
            project.mkdir()
            (project / "README.md").write_text(
                "# Portable native evidence\n\n**Local React** and $E = mc^2$.\n\n"
                "https://example.invalid/" + "long-source-identifier/" * 15 + "\n\n"
                "<script>window.__portableInjection = true</script>\n", encoding="utf-8")
            space = root / "space"
            manifest = export_hf_space(project, space)
            report["host_files_sha256"] = manifest["native_host_sha256"]
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            driver = """
import builtins, pathlib, sys
original_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name.split('.')[0] == 'streamlit':
        raise AssertionError('The portable host cannot import Streamlit')
    return original_import(name, *args, **kwargs)
builtins.__import__ = blocked
sys.path.insert(0, str(pathlib.Path.cwd()))
from agi_web import react_python_host, public_bind_guard
assert pathlib.Path(react_python_host.__file__).resolve().is_relative_to(pathlib.Path.cwd())
assert pathlib.Path(public_bind_guard.__file__).resolve().is_relative_to(pathlib.Path.cwd())
react_python_host.main(['app.py', '--address', '0.0.0.0', '--port', sys.argv[1], '--no-browser'])
"""
            environment = dict(os.environ, AGILAB_PUBLIC_BIND_OK="1", AGILAB_TLS_TERMINATED="1")
            with (output / "agilab_native_portable_export_host.log").open("w") as log:
                process = subprocess.Popen([sys.executable, "-I", "-S", "-c", driver, str(port)],
                                           cwd=space, env=environment, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 15
                url = f"http://127.0.0.1:{port}"
                while True:
                    try:
                        with urlopen(url + "/api/health", timeout=1):
                            break
                    except OSError:
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError("The bundled native host did not start.")
                        time.sleep(0.1)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    page.on("pageerror", lambda error: report["console_errors"].append(str(error)))
                    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)
                    page.on("request", lambda request: report["external_requests"].append(request.url)
                            if request.url.startswith(("http:", "https:")) and not request.url.startswith(url + "/") else None)
                    page.on("requestfailed", lambda request: report["failed_requests"].append(request.url))
                    page.on("response", lambda response: report["http_errors"].append({"url": response.url, "status": response.status})
                            if response.status >= 400 else None)
                    try:
                        page.goto(url, wait_until="networkidle")
                        page.get_by_role("heading", name="AGILAB evidence demo", exact=True).wait_for()
                        page.get_by_role("heading", name="Portable native evidence", exact=True).wait_for()
                        page.locator(".katex").first.wait_for()
                        assert page.title() == "AGILAB Space"
                        assert page.evaluate("window.__portableInjection === undefined")
                        page.screenshot(path=str(output / "agilab_native_portable_export_desktop.png"), full_page=True)
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2")
                        page.screenshot(path=str(output / "agilab_native_portable_export_mobile.png"), full_page=True)
                        assert not any(report[name] for name in ("console_errors", "failed_requests", "http_errors", "external_requests")), report
                        report.update(status="passed", streamlit_imports_blocked=True, server_site_packages=False,
                                      checks=["bundled_public_bind_guard", "explicit_public_consent", "stdlib_only_server",
                                              "portable_react_renderer", "local_markdown_math", "sanitized_html", "mobile_long_url"])
                    finally:
                        browser.close()
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        (output / "agilab_native_portable_export_browser_validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "host_files_sha256"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
