from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_widget_robot(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    browsers_path = _playwright_browsers_path()
    if browsers_path:
        env["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _assert_widget_robot_success(completed: subprocess.CompletedProcess[str]) -> dict:
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
    return payload


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
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    cd "$REPO_ROOT"
    AGILAB_RUN_FULL_UI_ROBOT=1 uv --preview-features extra-build-dependencies run --with playwright pytest -q -o addopts='' -m ui_robot "$REPO_ROOT/test/test_agilab_widget_robot_full.py"

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
        "--quiet-progress",
    ]
    if url:
        command.extend(["--url", url])
    if active_app:
        command.extend(["--active-app", active_app])
    if remote_app_root:
        command.extend(["--remote-app-root", remote_app_root])

    _assert_widget_robot_success(_run_widget_robot(command))


@pytest.mark.ui_robot
def test_full_public_orchestrate_widget_robot_sweep() -> None:
    """Opt-in ORCHESTRATE sweep across every built-in app.

    Run with:
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    cd "$REPO_ROOT"
    AGILAB_RUN_ORCHESTRATE_UI_ROBOT=1 uv --preview-features extra-build-dependencies run --with playwright pytest -q -o addopts='' -m ui_robot "$REPO_ROOT/test/test_agilab_widget_robot_full.py"
    """

    if os.environ.get("AGILAB_RUN_ORCHESTRATE_UI_ROBOT") != "1":
        pytest.skip("set AGILAB_RUN_ORCHESTRATE_UI_ROBOT=1 to run the ORCHESTRATE Playwright widget sweep")

    apps = os.environ.get("AGILAB_WIDGET_ROBOT_APPS", "all")
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
        "ORCHESTRATE",
        "--apps-pages",
        "none",
        "--json",
        "--timeout",
        timeout,
        "--widget-timeout",
        widget_timeout,
        "--target-seconds",
        target_seconds,
        "--quiet-progress",
    ]
    if url:
        command.extend(["--url", url])
    if active_app:
        command.extend(["--active-app", active_app])
    if remote_app_root:
        command.extend(["--remote-app-root", remote_app_root])

    payload = _assert_widget_robot_success(_run_widget_robot(command))
    assert all(page["page"] == "ORCHESTRATE" for page in payload["pages"])
    if apps == "all" and not url:
        expected_apps = {
            path.name
            for path in (REPO_ROOT / "src/agilab/apps/builtin").glob("*_project")
            if path.is_dir()
        }
        actual_apps = {page["app"] for page in payload["pages"]}
        assert expected_apps <= actual_apps
