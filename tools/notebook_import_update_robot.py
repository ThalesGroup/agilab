#!/usr/bin/env python3
"""Exercise notebook import, reviewed updates, cancellation and conflict refusal.

Run with the intended worktree on PYTHONPATH and a prepared environment containing
agi-web and Playwright. This robot owns only its server, browser and output tree.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
import time
import tomllib
from typing import Any
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from agilab_web_robot import ReactPythonServer
from agilab.notebooks.notebook_import_update import verify_update_backup


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tools/testing/agilab_notebook_import_update_fixture.py"
STEM = "agilab-notebook-import-reviewed-update"
MANUAL_STAGE_ID = "handwritten_report"
SOURCE_PATHS = (
    Path(__file__).resolve(),
    FIXTURE,
    REPO_ROOT / "src/agilab/pipeline/pipeline_editor.py",
    REPO_ROOT / "src/agilab/notebooks/notebook_import_update.py",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _snapshot(project: Path) -> dict[str, str]:
    return {
        str(path.relative_to(project)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


def _notebook(revised: bool) -> dict[str, Any]:
    sources = [
        ("values", "values = [1, 2]"),
        ("mutate", "values.extend([3, 4])" if revised else "values.append(3)"),
        ("total", "total = sum(values)\nprint(total)"),
        ("answer", "answer = total * 2") if revised else ("legacy", "legacy = total"),
    ]
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        },
        "cells": [
            {
                "cell_type": "code",
                "id": cell_id,
                "metadata": {},
                "source": source,
                "execution_count": None,
                "outputs": [],
            }
            for cell_id, source in sources
        ],
    }


def _stages(project: Path) -> list[dict[str, Any]]:
    with (project / "lab_stages.toml").open("rb") as handle:
        return tomllib.load(handle)[project.name]


def _assert_import(project: Path, *, revised: bool) -> dict[str, Any]:
    stages = _stages(project)
    assert len(stages) == 2, (
        f"Expected handwritten + one shared stage, got {len(stages)}"
    )
    manual = [stage for stage in stages if stage.get("id") == MANUAL_STAGE_ID]
    assert len(manual) == 1 and manual[0]["C"] == "print('Keep this project edit')"
    imported = [stage for stage in stages if stage.get("id") != MANUAL_STAGE_ID]
    code = imported[0]["C"]
    expected = "values.extend([3, 4])" if revised else "values.append(3)"
    assert expected in code
    assert ("answer = total * 2" in code) is revised
    assert ("legacy = total" in code) is not revised
    return {
        "stage_count": len(stages),
        "manual_stage_preserved": True,
        "shared_stage_count": len(imported),
        "shared_stage_sha256": sha256(code.encode()).hexdigest(),
    }


def _wait_ready(server: ReactPythonServer, url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.process is not None and server.process.poll() is not None:
            raise RuntimeError(f"Native fixture exited: {server.output_tail()}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"Native fixture did not start: {server.output_tail()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = output / "reviewed_notebook_project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "reviewed-notebook-project"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (project / "lab_stages.toml").write_text(
        f'[[{project.name}]]\nid = "{MANUAL_STAGE_ID}"\n'
        'D = "Independent project report"\nR = "runpy"\n'
        "C = \"print('Keep this project edit')\"\n",
        encoding="utf-8",
    )
    originals = output / "source-uploads"
    originals.mkdir()
    uploads = []
    for label, revised in (("initial", False), ("revised", True)):
        path = originals / f"{STEM}-{label}.ipynb"
        path.write_text(
            json.dumps(_notebook(revised), indent=2) + "\n", encoding="utf-8"
        )
        uploads.append(path)
    # Both uploads deliberately keep the same browser-visible source name.
    source_name = "experiment.ipynb"
    port = args.port or _free_port()
    url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, AGILAB_NOTEBOOK_UPDATE_ROBOT_PROJECT=str(project))
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")])
    )
    argv = [
        sys.executable,
        "-m",
        "agi_web.react_python_host",
        str(FIXTURE),
        "--address",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-browser",
    ]
    report: dict[str, Any] = {
        "schema": "agilab.notebook_import_update_robot.v1",
        "status": "running",
        "scope": "Native notebook import renderer with real upload; deterministic local project, no execution/provider.",
        "command": argv,
        "repo_root": str(REPO_ROOT),
        "fixture_sha256": sha256(FIXTURE.read_bytes()).hexdigest(),
        "robot_command": [sys.executable, *sys.argv],
        "input_sha256": {
            str(path.relative_to(REPO_ROOT)): sha256(path.read_bytes()).hexdigest()
            for path in SOURCE_PATHS
        },
        "console_errors": [],
        "console_warnings": [],
        "page_errors": [],
        "failed_requests": [],
        "http_errors": [],
        "checks": [],
        "screenshots": [],
    }
    report_path = output / f"{STEM}-browser-validation.json"
    page = None
    try:
        with ReactPythonServer(argv, env=env, url=url) as server:
            try:
                _wait_ready(server, url, args.timeout)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    context = browser.new_context(
                        viewport={"width": 1440, "height": 1200}, accept_downloads=True
                    )
                    context.tracing.start(
                        screenshots=True, snapshots=True, sources=True
                    )
                    page = context.new_page()
                    page.set_default_timeout(args.timeout * 1000)
                    expect.set_options(timeout=args.timeout * 1000)
                    page.on(
                        "console",
                        lambda message: (
                            report[
                                "console_errors"
                                if message.type == "error"
                                else "console_warnings"
                            ].append(message.text)
                            if message.type in {"error", "warning"}
                            else None
                        ),
                    )
                    page.on(
                        "pageerror",
                        lambda error: report["page_errors"].append(str(error)),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: report["failed_requests"].append(
                            {"url": request.url, "failure": request.failure}
                        ),
                    )
                    page.on(
                        "response",
                        lambda response: (
                            report["http_errors"].append(
                                {"url": response.url, "status": response.status}
                            )
                            if response.status >= 400
                            else None
                        ),
                    )
                    page.goto(url, wait_until="networkidle")
                    expect(
                        page.get_by_role(
                            "heading",
                            name="Review changes to a notebook import",
                            exact=True,
                        )
                    ).to_be_visible()

                    def upload(path: Path) -> None:
                        page.locator('input[type="file"]').set_input_files(
                            {
                                "name": source_name,
                                "mimeType": "application/x-ipynb+json",
                                "buffer": path.read_bytes(),
                            }
                        )
                        expect(
                            page.get_by_label("Preserve notebook state", exact=True)
                        ).to_be_visible()
                        if not page.get_by_label(
                            "Cell 1 runtime", exact=True
                        ).is_visible():
                            page.get_by_text(
                                "Runtime role per cell", exact=True
                            ).click()
                        for cell_index in range(1, 5):
                            role = page.get_by_label(
                                f"Cell {cell_index} runtime", exact=True
                            )
                            expect(role).to_be_visible()
                            role.select_option(label="Manager (local runpy)")
                        page.get_by_label("Preserve notebook state", exact=True).check()

                    def choose_update() -> None:
                        page.get_by_label(
                            "Notebook import action", exact=True
                        ).select_option(label="Update existing notebook stage")

                    def confirm(*, update: bool = False) -> None:
                        button = page.get_by_role(
                            "button",
                            name="Update notebook stage"
                            if update
                            else "Import all runnable cells",
                            exact=True,
                        )
                        try:
                            expect(button).to_be_enabled()
                        except AssertionError:
                            (output / f"{STEM}-failed-control.txt").write_text(
                                page.locator("body").inner_text(), encoding="utf-8"
                            )
                            page.screenshot(
                                path=str(output / f"{STEM}-failed-control.png"),
                                full_page=True,
                            )
                            raise
                        button.click()

                    upload(uploads[0])
                    confirm()
                    expect(
                        page.get_by_text(
                            "Imported 4 notebook code cell(s).", exact=True
                        )
                    ).to_be_visible()
                    initial = _assert_import(project, revised=False)
                    report["checks"].append(
                        {"id": "initial_import", "passed": True, **initial}
                    )

                    # Preview cancellation must not write any project file.
                    before_cancel = _snapshot(project)
                    upload(uploads[1])
                    choose_update()
                    page.get_by_role("button", name="Cancel import", exact=True).click()
                    expect(
                        page.get_by_text("Notebook preview cancelled.", exact=True)
                    ).to_be_visible()
                    assert _snapshot(project) == before_cancel, (
                        "Cancellation changed project files"
                    )
                    report["checks"].append(
                        {"id": "cancel_is_read_only", "passed": True}
                    )

                    upload(uploads[1])
                    choose_update()
                    expect(
                        page.get_by_text(
                            "Notebook update: 1 added, 1 changed, 1 removed, 0 moved. "
                            "Review What will be written before confirming. No code runs during import.",
                            exact=True,
                        )
                    ).to_be_visible()
                    page.get_by_text("What will be written", exact=True).click()
                    diff = page.locator("pre").filter(has_text="Added cells:").first
                    expect(diff).to_contain_text("Added cells: answer")
                    expect(diff).to_contain_text("Changed cells: mutate")
                    expect(diff).to_contain_text("Removed cells: legacy")
                    screenshot = output / f"{STEM}-review.png"
                    page.screenshot(path=str(screenshot), full_page=True)
                    report["screenshots"].append(str(screenshot))
                    confirm(update=True)
                    expect(
                        page.get_by_text(
                            "Updated notebook stage from 4 code cell(s).", exact=True
                        )
                    ).to_be_visible()
                    recovery = page.get_by_role(
                        "link", name="Download previous notebook import", exact=True
                    )
                    expect(recovery).to_be_visible()
                    with page.expect_download() as download_info:
                        recovery.click()
                    recovery_path = output / f"{STEM}-previous-import.json"
                    download_info.value.save_as(str(recovery_path))
                    recovered = verify_update_backup(recovery_path)
                    for name, data in recovered.items():
                        assert (
                            sha256(data).hexdigest() if data is not None else None
                        ) == before_cancel.get(name)
                    report["checks"].append(
                        {
                            "id": "reviewed_update",
                            "passed": True,
                            "recovery_sha256": sha256(
                                recovery_path.read_bytes()
                            ).hexdigest(),
                            **_assert_import(project, revised=True),
                        }
                    )

                    # A repeated confirmation preserves the single shared stage.
                    before_repeat = _assert_import(project, revised=True)
                    upload(uploads[1])
                    choose_update()
                    confirm(update=True)
                    expect(
                        page.get_by_text(
                            "Updated notebook stage from 4 code cell(s).", exact=True
                        )
                    ).to_be_visible()
                    assert _assert_import(project, revised=True) == before_repeat
                    report["checks"].append(
                        {
                            "id": "repeat_update_without_duplicates",
                            "passed": True,
                            **_assert_import(project, revised=True),
                        }
                    )

                    # Change the target after review; confirmation must refuse it.
                    upload(uploads[0])
                    choose_update()
                    target = project / "lab_stages.toml"
                    target.write_text(
                        target.read_text(encoding="utf-8")
                        + "\n# concurrent project edit\n",
                        encoding="utf-8",
                    )
                    before_conflict = _snapshot(project)
                    update_button = page.get_by_role(
                        "button", name="Update notebook stage", exact=True
                    )
                    # Rerendering can reject stale reviews before confirmation.
                    # Both surfaces must preserve the concurrent author's bytes.
                    if update_button.is_enabled():
                        confirm(update=True)
                    expect(
                        page.get_by_text(
                            "Notebook import files changed after the preview was built; "
                            "upload again and review a fresh update.",
                            exact=False,
                        ).first
                    ).to_be_visible()
                    expect(update_button).to_be_disabled()
                    assert _snapshot(project) == before_conflict, (
                        "Refused conflict changed project files"
                    )
                    report["checks"].append(
                        {"id": "stale_review_refused", "passed": True}
                    )
                    for key in (
                        "console_errors",
                        "console_warnings",
                        "page_errors",
                        "failed_requests",
                        "http_errors",
                    ):
                        assert not report[key], (
                            f"Browser issues in {key}: {report[key]}"
                        )
                    assert report["input_sha256"] == {
                        str(path.relative_to(REPO_ROOT)): sha256(
                            path.read_bytes()
                        ).hexdigest()
                        for path in SOURCE_PATHS
                    }, "Source changed during browser validation"
                    context.tracing.stop(path=str(output / f"{STEM}-browser-trace.zip"))
                    browser.close()
                    report["status"] = "passed"
            finally:
                (output / f"{STEM}-server.log").write_text(
                    server.output_tail(limit=100000), encoding="utf-8"
                )
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["project_files"] = _snapshot(project)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "checks": len(report["checks"]),
                "report": str(report_path),
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
