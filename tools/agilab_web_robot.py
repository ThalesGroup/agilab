#!/usr/bin/env python3
"""Browser-level AGILAB UI robot.

This is intentionally separate from the default pytest suite because it drives a
real browser through Playwright and may require browser binaries to be installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

def _load_screenshot_manifest_helpers():
    try:
        from agilab.screenshot_manifest import (  # noqa: E402
            build_page_shots_manifest,
            screenshot_manifest_path,
            write_screenshot_manifest,
        )

        return build_page_shots_manifest, screenshot_manifest_path, write_screenshot_manifest
    except ModuleNotFoundError as exc:
        manifest_path = REPO_ROOT / "src" / "agilab" / "screenshot_manifest.py"
        if not manifest_path.exists():
            raise RuntimeError(
                "Could not import agilab.screenshot_manifest and fallback file is missing."
            ) from exc

        spec = importlib.util.spec_from_file_location("_agilab_local_screenshot_manifest", manifest_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Could not build import spec for {manifest_path}"
            ) from exc
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return (
            module.build_page_shots_manifest,
            module.screenshot_manifest_path,
            module.write_screenshot_manifest,
        )


build_page_shots_manifest, screenshot_manifest_path, write_screenshot_manifest = _load_screenshot_manifest_helpers()

DEFAULT_ACTIVE_APP = REPO_ROOT / "src/agilab/apps/builtin/flight_telemetry_project"
DEFAULT_APPS_PATH = REPO_ROOT / "src/agilab/apps"
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_TARGET_SECONDS = 120.0
DEFAULT_REJECT_PATTERNS = (
    "uncaught app exception",
    "traceback",
    "valueerror:",
    "attributeerror:",
    "typeerror:",
    "modulenotfounderror:",
    "object of type 'nonetype' is not toml serializable",
    "refused to connect to 127.0.0.1",
    "127.0.0.1 refused to connect",
    "this site can't be reached",
    "this site cannot be reached",
    "could not determine the active app",
    "provided active app path does not exist",
    "failed to render view:",
)
ANALYSIS_VIEW_RELATIVE_PATHS = {
    "view_maps": "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py",
    "view_maps_network": "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py",
}
ANALYSIS_VIEW_PATHS = {
    name: REPO_ROOT / relative_path
    for name, relative_path in ANALYSIS_VIEW_RELATIVE_PATHS.items()
}
UV_RUN_STREAMLIT = (
    "uv",
    "--preview-features",
    "extra-build-dependencies",
    "run",
    "--extra",
    "ui",
    "streamlit",
)


@dataclass(frozen=True)
class RobotStep:
    label: str
    success: bool
    duration_seconds: float
    detail: str
    url: str | None = None


@dataclass(frozen=True)
class RobotSummary:
    success: bool
    total_duration_seconds: float
    target_seconds: float
    within_target: bool
    steps: list[RobotStep]


class StreamlitServer:
    def __init__(self, argv: Sequence[str], *, env: dict[str, str], url: str) -> None:
        self.argv = list(argv)
        self.env = dict(env)
        self.url = url
        self.process: subprocess.Popen[str] | None = None
        self._output_file: Any | None = None
        self._output_path: Path | None = None

    def __enter__(self) -> "StreamlitServer":
        self._output_file = tempfile.NamedTemporaryFile(
            mode="w+",
            encoding="utf-8",
            prefix="agilab-streamlit-server-",
            suffix=".log",
            delete=False,
        )
        self._output_path = Path(self._output_file.name)
        self.process = subprocess.Popen(
            self.argv,
            cwd=str(REPO_ROOT),
            env=self.env,
            text=True,
            stdout=self._output_file,
            stderr=subprocess.STDOUT,
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        try:
            if self.process is None:
                return
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
        finally:
            if self._output_file is not None:
                self._output_file.close()

    def output_tail(self, *, limit: int = 4000) -> str:
        if self._output_file is not None:
            self._output_file.flush()
        if self._output_path is None or not self._output_path.exists():
            return ""
        try:
            output = self._output_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        return output[-limit:]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch AGILAB or attach to an existing URL, then validate the web UI "
            "through a real Playwright browser."
        )
    )
    parser.add_argument(
        "--url",
        help="Existing AGILAB base URL to test. If omitted, a local Streamlit server is launched.",
    )
    parser.add_argument(
        "--active-app",
        default=str(DEFAULT_ACTIVE_APP),
        help=(
            "Active app path/name used for the local launch and active_app query. "
            "Defaults to the built-in flight_telemetry_project path."
        ),
    )
    parser.add_argument(
        "--apps-path",
        default=str(DEFAULT_APPS_PATH),
        help="Apps root passed to the local Streamlit launch.",
    )
    parser.add_argument("--port", type=int, help="Local Streamlit port. Defaults to a free port.")
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Playwright browser engine to use.",
    )
    parser.add_argument("--headful", action="store_true", help="Show the browser window.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-step timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS:.0f}.",
    )
    parser.add_argument(
        "--target-seconds",
        type=float,
        default=DEFAULT_TARGET_SECONDS,
        help=f"Total KPI target in seconds. Default: {DEFAULT_TARGET_SECONDS:.0f}.",
    )
    parser.add_argument(
        "--analysis-view",
        choices=sorted(ANALYSIS_VIEW_PATHS),
        default=None,
        help="Optional analysis sidecar view to open after reaching ANALYSIS.",
    )
    parser.add_argument(
        "--remote-app-root",
        default="/app",
        help="Root directory used to build current_page paths when --url targets a remote deployment.",
    )
    parser.add_argument(
        "--screenshot-dir",
        help="Optional directory where failure screenshots are written.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the resolved launch command and robot route without executing.",
    )
    return parser


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_streamlit_command(
    *,
    active_app: Path | str,
    apps_path: Path | str,
    port: int,
) -> list[str]:
    about_page = REPO_ROOT / "src/agilab/main_page.py"
    return [
        *UV_RUN_STREAMLIT,
        "run",
        str(about_page),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--server.runOnSave",
        "false",
        "--browser.gatherUsageStats",
        "false",
        "--",
        "--active-app",
        str(active_app),
        "--apps-path",
        str(apps_path),
    ]


def build_server_env() -> dict[str, str]:
    env = os.environ.copy()
    # The robot itself can run in a temporary `uv --with playwright` env.
    # The Streamlit child must resolve AGILAB from the repo project instead.
    env.pop("UV_RUN_RECURSION_DEPTH", None)
    env.pop("VIRTUAL_ENV", None)
    env.setdefault("AGILAB_DISABLE_BACKGROUND_SERVICES", "1")
    env.setdefault("OPENAI_API_KEY", "sk-test-agilab-web-robot-000000000000")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def resolve_local_active_app(active_app: str, apps_path: str) -> Path | str:
    candidate = Path(active_app).expanduser()
    if candidate.exists():
        return candidate.resolve()
    apps_candidate = Path(apps_path).expanduser() / active_app
    if apps_candidate.exists():
        return apps_candidate.resolve()
    builtin_candidate = Path(apps_path).expanduser() / "builtin" / active_app
    if builtin_candidate.exists():
        return builtin_candidate.resolve()
    if not active_app.endswith("_project"):
        project_name = f"{active_app}_project"
        apps_project_candidate = Path(apps_path).expanduser() / project_name
        if apps_project_candidate.exists():
            return apps_project_candidate.resolve()
        builtin_project_candidate = Path(apps_path).expanduser() / "builtin" / project_name
        if builtin_project_candidate.exists():
            return builtin_project_candidate.resolve()
    return active_app


def resolve_analysis_view_path(
    analysis_view: str,
    *,
    remote: bool,
    remote_app_root: str = "/app",
) -> str:
    relative_path = ANALYSIS_VIEW_RELATIVE_PATHS[analysis_view]
    if remote:
        return str(Path(remote_app_root) / relative_path)
    return str((REPO_ROOT / relative_path).resolve())


def build_url(base_url: str, *, active_app: str | None = None, current_page: str | None = None) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    if active_app:
        query["active_app"] = active_app
    if current_page:
        query["current_page"] = current_page
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            urllib.parse.urlencode(query),
            parsed.fragment,
        )
    )


def build_page_url(
    base_url: str,
    page_name: str,
    *,
    active_app: str | None = None,
    current_page: str | None = None,
) -> str:
    return build_url(
        base_url.rstrip("/") + "/" + page_name.strip("/"),
        active_app=active_app,
        current_page=current_page,
    )


def wait_for_streamlit_health(
    base_url: str,
    *,
    timeout: float,
    opener: Callable[[str], Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.perf_counter,
    sleeper: Callable[[float], None] = time.sleep,
) -> RobotStep:
    start = clock()
    health_url = base_url.rstrip("/") + "/_stcore/health"
    last_error = ""
    deadline = start + timeout
    while True:
        try:
            with opener(health_url) as response:
                status = int(getattr(response, "status", response.getcode()))
                if status < 400:
                    return RobotStep("streamlit health", True, clock() - start, f"HTTP {status}", health_url)
                last_error = f"HTTP {status}"
        except Exception as exc:
            last_error = str(exc)
        if clock() >= deadline:
            break
        sleeper(0.5)
    return RobotStep("streamlit health", False, clock() - start, f"not ready: {last_error}", health_url)


def _load_playwright() -> Any:
    try:
        from playwright.sync_api import Error, TimeoutError, sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: "
            "uv --preview-features extra-build-dependencies run --with playwright "
            "python tools/agilab_web_robot.py"
        ) from exc
    return Error, TimeoutError, sync_playwright


def _body_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""


def _find_rejected_pattern(text: str, reject_patterns: Sequence[str] = DEFAULT_REJECT_PATTERNS) -> str | None:
    normalized = text.lower()
    for pattern in reject_patterns:
        if pattern in normalized:
            return pattern
    return None


def _screenshot(page: Any, screenshot_dir: Path | None, label: str) -> str | None:
    if screenshot_dir is None:
        return None
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "step"
    path = screenshot_dir / f"{safe_label}.png"
    page.screenshot(path=str(path), full_page=True)
    _refresh_screenshot_manifest(screenshot_dir)
    return str(path)


def _refresh_screenshot_manifest(screenshot_dir: Path) -> None:
    try:
        source_command = tuple(sys.argv) if sys.argv else ("tools/agilab_web_robot.py",)
        manifest = build_page_shots_manifest(
            screenshot_dir,
            source_command=source_command,
        )
        write_screenshot_manifest(manifest, screenshot_manifest_path(screenshot_dir))
    except Exception:
        # Screenshot capture is diagnostic. Do not hide the original UI failure
        # behind a secondary manifest-write error.
        return


def assert_page_healthy(
    page: Any,
    *,
    label: str,
    expect_any: Sequence[str] = (),
    timeout_ms: float,
    screenshot_dir: Path | None = None,
) -> RobotStep:
    start = time.perf_counter()
    try:
        page.wait_for_selector("[data-testid='stApp']", timeout=timeout_ms)
        deadline = start + (timeout_ms / 1000.0)
        while True:
            exception_count = page.locator("[data-testid='stException']").count()
            text = _body_text(page)
            rejected = _find_rejected_pattern(text)
            if exception_count:
                screenshot = _screenshot(page, screenshot_dir, label)
                detail = f"Streamlit exception block found ({exception_count})"
                if screenshot:
                    detail += f"; screenshot={screenshot}"
                return RobotStep(label, False, time.perf_counter() - start, detail, page.url)
            if rejected:
                screenshot = _screenshot(page, screenshot_dir, label)
                detail = f"page text contains rejected pattern {rejected!r}"
                if screenshot:
                    detail += f"; screenshot={screenshot}"
                return RobotStep(label, False, time.perf_counter() - start, detail, page.url)
            if not expect_any or any(expected.lower() in text.lower() for expected in expect_any):
                return RobotStep(label, True, time.perf_counter() - start, "page healthy", page.url)
            if time.perf_counter() >= deadline:
                break
            page.wait_for_timeout(250)

        if expect_any:
            screenshot = _screenshot(page, screenshot_dir, label)
            detail = "missing expected text: " + " | ".join(expect_any)
            if screenshot:
                detail += f"; screenshot={screenshot}"
            return RobotStep(label, False, time.perf_counter() - start, detail, page.url)
        return RobotStep(label, True, time.perf_counter() - start, "page healthy", page.url)
    except Exception as exc:
        screenshot = _screenshot(page, screenshot_dir, label)
        detail = f"health assertion failed: {exc}"
        if screenshot:
            detail += f"; screenshot={screenshot}"
        return RobotStep(label, False, time.perf_counter() - start, detail, getattr(page, "url", None))


def _append_step(steps: list[RobotStep], step: RobotStep) -> bool:
    steps.append(step)
    return step.success


def run_browser_robot(
    *,
    base_url: str,
    active_app_query: str,
    browser_name: str,
    headless: bool,
    timeout: float,
    analysis_view: str | None = None,
    analysis_view_path: str | None = None,
    screenshot_dir: Path | None = None,
) -> list[RobotStep]:
    Error, TimeoutError, sync_playwright = _load_playwright()
    timeout_ms = timeout * 1000.0
    steps: list[RobotStep] = []

    try:
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            try:
                page = context.new_page()

                landing_url = build_url(base_url, active_app=active_app_query)
                start = time.perf_counter()
                page.goto(landing_url, wait_until="domcontentloaded", timeout=timeout_ms)
                if not _append_step(
                    steps,
                    RobotStep("landing navigation", True, time.perf_counter() - start, "loaded", page.url),
                ):
                    return steps
                if not _append_step(
                    steps,
                    assert_page_healthy(
                        page,
                        label="landing page",
                        expect_any=("First proof", "Upload"),
                        timeout_ms=timeout_ms,
                        screenshot_dir=screenshot_dir,
                    ),
                ):
                    return steps

                robot_notebook_path = Path(tempfile.gettempdir()) / "agilab-web-robot-upload.ipynb"
                robot_notebook_path.write_text(
                    json.dumps(
                        {
                            "cells": [
                                {
                                    "cell_type": "code",
                                    "execution_count": None,
                                    "metadata": {},
                                    "outputs": [],
                                    "source": ["print('hello from AGILAB web robot')"],
                                }
                            ],
                            "metadata": {},
                            "nbformat": 4,
                            "nbformat_minor": 5,
                        }
                    ),
                    encoding="utf-8",
                )
                start = time.perf_counter()
                try:
                    with page.expect_file_chooser(timeout=timeout_ms) as file_chooser_info:
                        page.locator("[data-testid='stFileUploaderDropzone'] button").click(
                            timeout=timeout_ms
                        )
                    file_chooser_info.value.set_files(str(robot_notebook_path))
                    steps.append(
                        RobotStep(
                            "about upload button",
                            True,
                            time.perf_counter() - start,
                            "file chooser opened and notebook selected",
                            page.url,
                        )
                    )
                except (Error, TimeoutError) as exc:
                    screenshot = _screenshot(page, screenshot_dir, "about upload button")
                    detail = f"could not open file chooser from ABOUT Upload button: {exc}"
                    if screenshot:
                        detail += f"; screenshot={screenshot}"
                    steps.append(
                        RobotStep(
                            "about upload button",
                            False,
                            time.perf_counter() - start,
                            detail,
                            page.url,
                        )
                    )
                    return steps

                start = time.perf_counter()
                try:
                    page.wait_for_url(re.compile(r".*/PROJECT(?:\?.*)?$"), timeout=timeout_ms)
                    steps.append(
                        RobotStep(
                            "notebook upload handoff",
                            True,
                            time.perf_counter() - start,
                            "PROJECT opened",
                            page.url,
                        )
                    )
                except (Error, TimeoutError) as exc:
                    screenshot = _screenshot(page, screenshot_dir, "notebook upload handoff")
                    detail = f"PROJECT did not open after notebook upload: {exc}"
                    if screenshot:
                        detail += f"; screenshot={screenshot}"
                    steps.append(
                        RobotStep(
                            "notebook upload handoff",
                            False,
                            time.perf_counter() - start,
                            detail,
                            page.url,
                        )
                    )
                    return steps

                start = time.perf_counter()
                try:
                    page.wait_for_selector(
                        "[data-testid='stFileUploader'], [data-testid='stFileUploaderDropzone']",
                        timeout=timeout_ms,
                    )
                    steps.append(
                        RobotStep(
                            "project notebook uploader",
                            True,
                            time.perf_counter() - start,
                            "visible",
                            page.url,
                        )
                    )
                except (Error, TimeoutError) as exc:
                    screenshot = _screenshot(page, screenshot_dir, "project notebook uploader")
                    detail = f"PROJECT notebook uploader not visible after upload handoff: {exc}"
                    if screenshot:
                        detail += f"; screenshot={screenshot}"
                    steps.append(
                        RobotStep(
                            "project notebook uploader",
                            False,
                            time.perf_counter() - start,
                            detail,
                            page.url,
                        )
                    )
                    return steps

                start = time.perf_counter()
                page.goto(
                    build_page_url(base_url, "ORCHESTRATE", active_app=active_app_query),
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                if not _append_step(
                    steps,
                    RobotStep("orchestrate navigation", True, time.perf_counter() - start, "loaded", page.url),
                ):
                    return steps
                if not _append_step(
                    steps,
                    assert_page_healthy(
                        page,
                        label="orchestrate page",
                        expect_any=("ORCHESTRATE", "INSTALL", "EXECUTE"),
                        timeout_ms=timeout_ms,
                        screenshot_dir=screenshot_dir,
                    ),
                ):
                    return steps

                start = time.perf_counter()
                page.goto(
                    build_page_url(base_url, "ANALYSIS", active_app=active_app_query),
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                if not _append_step(
                    steps,
                    RobotStep("analysis navigation", True, time.perf_counter() - start, "loaded", page.url),
                ):
                    return steps
                if not _append_step(
                    steps,
                    assert_page_healthy(
                        page,
                        label="analysis page",
                        expect_any=("ANALYSIS", "Choose pages", "View:"),
                        timeout_ms=timeout_ms,
                        screenshot_dir=screenshot_dir,
                    ),
                ):
                    return steps

                if analysis_view and analysis_view_path:
                    start = time.perf_counter()
                    page.goto(
                        build_url(page.url, active_app=active_app_query, current_page=analysis_view_path),
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    if not _append_step(
                        steps,
                        RobotStep(
                            f"{analysis_view} navigation",
                            True,
                            time.perf_counter() - start,
                            "loaded",
                            page.url,
                        ),
                    ):
                        return steps
                    _append_step(
                        steps,
                        assert_page_healthy(
                            page,
                            label=f"{analysis_view} analysis view",
                            expect_any=("View:",),
                            timeout_ms=timeout_ms,
                            screenshot_dir=screenshot_dir,
                        ),
                    )
            finally:
                context.close()
                browser.close()
    except RuntimeError:
        raise
    except (Error, TimeoutError) as exc:
        steps.append(RobotStep("browser robot", False, 0.0, f"playwright failed: {exc}", base_url))
    return steps


def summarize_steps(steps: Sequence[RobotStep], *, target_seconds: float) -> RobotSummary:
    total = sum(step.duration_seconds for step in steps)
    success = bool(steps) and all(step.success for step in steps)
    return RobotSummary(
        success=success,
        total_duration_seconds=total,
        target_seconds=target_seconds,
        within_target=success and total <= target_seconds,
        steps=list(steps),
    )


def render_human(
    *,
    summary: RobotSummary | None,
    launch_command: Sequence[str] | None,
    base_url: str,
    print_only: bool = False,
) -> str:
    lines = ["AGILAB web UI robot", f"base url: {base_url}"]
    if launch_command:
        lines.append("$ " + " ".join(shlex.quote(part) for part in launch_command))
    if print_only:
        lines.append("mode: print-only")
        lines.append("route: landing Upload chooser -> PROJECT notebook handoff -> ORCHESTRATE -> ANALYSIS")
        return "\n".join(lines)

    assert summary is not None
    lines.append(f"verdict: {'PASS' if summary.success else 'FAIL'}")
    lines.append(
        "kpi: "
        f"total={summary.total_duration_seconds:.2f}s "
        f"target<={summary.target_seconds:.2f}s "
        f"within_target={'yes' if summary.within_target else 'no'}"
    )
    for step in summary.steps:
        status = "OK" if step.success else "FAIL"
        lines.append(f"- {step.label}: {status} in {step.duration_seconds:.2f}s - {step.detail}")
    return "\n".join(lines)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.target_seconds <= 0:
        parser.error("--target-seconds must be greater than 0")

    port = args.port or _free_port()
    local_url = f"http://127.0.0.1:{port}"
    base_url = args.url or local_url
    local_active_app = resolve_local_active_app(args.active_app, args.apps_path)
    launch_command = None if args.url else build_streamlit_command(
        active_app=local_active_app,
        apps_path=args.apps_path,
        port=port,
    )

    if args.print_only:
        payload = {
            "base_url": base_url,
            "launch_command": launch_command,
            "route": [
                "landing Upload chooser",
                "PROJECT notebook handoff",
                "ORCHESTRATE",
                "ANALYSIS",
            ],
            "analysis_view": args.analysis_view,
            "analysis_view_path": (
                resolve_analysis_view_path(
                    args.analysis_view,
                    remote=bool(args.url),
                    remote_app_root=args.remote_app_root,
                )
                if args.analysis_view
                else None
            ),
        }
        if args.json:
            _print_json(payload)
        else:
            print(
                render_human(
                    summary=None,
                    launch_command=launch_command,
                    base_url=base_url,
                    print_only=True,
                )
            )
        return 0

    screenshot_dir = Path(args.screenshot_dir).expanduser().resolve() if args.screenshot_dir else None
    active_app_query = str(args.active_app if args.url else local_active_app)
    analysis_view_path = (
        resolve_analysis_view_path(
            args.analysis_view,
            remote=bool(args.url),
            remote_app_root=args.remote_app_root,
        )
        if args.analysis_view
        else None
    )

    steps: list[RobotStep] = []
    try:
        if launch_command:
            with StreamlitServer(launch_command, env=build_server_env(), url=base_url) as server:
                health = wait_for_streamlit_health(base_url, timeout=args.timeout)
                steps.append(health)
                if health.success:
                    steps.extend(
                        run_browser_robot(
                            base_url=base_url,
                            active_app_query=active_app_query,
                            browser_name=args.browser,
                            headless=not args.headful,
                            timeout=args.timeout,
                            analysis_view=args.analysis_view,
                            analysis_view_path=analysis_view_path,
                            screenshot_dir=screenshot_dir,
                        )
                    )
                elif server.process and server.process.poll() is not None:
                    steps.append(
                        RobotStep(
                            "streamlit process",
                            False,
                            0.0,
                            f"process exited with {server.process.returncode}; output={server.output_tail()}",
                            base_url,
                        )
                    )
        else:
            steps.extend(
                run_browser_robot(
                    base_url=base_url,
                    active_app_query=active_app_query,
                    browser_name=args.browser,
                    headless=not args.headful,
                    timeout=args.timeout,
                    analysis_view=args.analysis_view,
                    analysis_view_path=analysis_view_path,
                    screenshot_dir=screenshot_dir,
                )
            )
    except RuntimeError as exc:
        steps.append(RobotStep("browser setup", False, 0.0, str(exc), base_url))

    summary = summarize_steps(steps, target_seconds=args.target_seconds)
    if args.json:
        _print_json(asdict(summary))
    else:
        print(render_human(summary=summary, launch_command=launch_command, base_url=base_url))
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
