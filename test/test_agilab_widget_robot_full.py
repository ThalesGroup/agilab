from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _playwright_browsers_path() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        return configured
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    candidates = [
        real_home / "Library" / "Caches" / "ms-playwright",
        real_home / ".cache" / "ms-playwright",
        real_home / "AppData" / "Local" / "ms-playwright",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


@pytest.mark.ui_robot
def test_full_public_widget_robot_sweep() -> None:
    """Opt-in pytest entrypoint for the browser widget robot.

    Run with:
    AGILAB_RUN_FULL_UI_ROBOT=1 uv --preview-features extra-build-dependencies run --with playwright pytest -q -o addopts='' -m ui_robot test/test_agilab_widget_robot_full.py

    Set AGILAB_WIDGET_ROBOT_URL=https://huggingface.co/spaces/jpmorard/agilab to run the same robot against the public HF Space.
    """

    if os.environ.get("AGILAB_RUN_FULL_UI_ROBOT") != "1":
        pytest.skip("set AGILAB_RUN_FULL_UI_ROBOT=1 to run the full Playwright widget sweep")

    apps = os.environ.get("AGILAB_WIDGET_ROBOT_APPS", "all")
    pages = os.environ.get("AGILAB_WIDGET_ROBOT_PAGES", "all")
    apps_pages = os.environ.get("AGILAB_WIDGET_ROBOT_APPS_PAGES", "configured")
    target_seconds = os.environ.get("AGILAB_WIDGET_ROBOT_TARGET_SECONDS", "1800")
    timeout = os.environ.get("AGILAB_WIDGET_ROBOT_TIMEOUT", "90")
    widget_timeout = os.environ.get("AGILAB_WIDGET_ROBOT_WIDGET_TIMEOUT", "3")
    url = os.environ.get("AGILAB_WIDGET_ROBOT_URL")
    active_app = os.environ.get("AGILAB_WIDGET_ROBOT_ACTIVE_APP")
    remote_app_root = os.environ.get("AGILAB_WIDGET_ROBOT_REMOTE_APP_ROOT")

    command = [
        sys.executable,
        str(REPO_ROOT / "tools/agilab_widget_robot.py"),
        "--apps",
        apps,
        "--pages",
        pages,
        "--apps-pages",
        apps_pages,
        "--json",
        "--timeout",
        timeout,
        "--widget-timeout",
        widget_timeout,
        "--target-seconds",
        target_seconds,
    ]
    if url:
        command.extend(["--url", url])
    if active_app:
        command.extend(["--active-app", active_app])
    if remote_app_root:
        command.extend(["--remote-app-root", remote_app_root])
    env = os.environ.copy()
    browsers_path = _playwright_browsers_path()
    if browsers_path:
        env["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    if "playwright install" in completed.stdout.lower():
        pytest.skip("Playwright browser binaries are not installed; run `uv run --with playwright playwright install chromium`")
    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["success"] is True
    assert payload["failed_count"] == 0
    assert payload["skipped_count"] == 0
    assert payload["app_count"] >= 1
    assert payload["page_count"] >= 1
    assert payload["widget_count"] >= payload["interacted_count"]
    assert payload["interacted_count"] > 0
