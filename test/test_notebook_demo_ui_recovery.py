"""The local notebook builder recovers its current run without regeneration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty
import shutil
import sys
from threading import Event, Thread

import pytest

from agilab.agent_runtime import notebook_agent as agent
from test import test_notebook_build_recovery as recovery_fixtures


PAGE = Path(agent.__file__).parents[1] / "demos" / "notebook_demo_ui.py"
RETRY = "Retry verification"
_SYSTEM_WHICH = shutil.which
builder = recovery_fixtures.builder


def _failed_report(root, *, eligible=True, reason=""):
    project = root / "notebook_app_project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "solution.ipynb").write_text('{"nbformat":4,"cells":[]}')
    report = {
        "status": "failed",
        "error": "Original acceptance failed",
        "failed_phase": "verify",
        "project": str(project),
        "seconds": 1.0,
        "verification_scope": "execution_and_interface",
        "recovery": {"eligible": eligible, "reason": reason},
    }
    (root / "result.json").write_text(json.dumps(report))
    return report


def _passed_report(root):
    return {
        "status": "passed",
        "project": str(root / "notebook_app_project"),
        "seconds": 2.0,
        "workflow_stages": 1,
        "files": {},
        "verification_scope": "execution_and_interface",
        "verification": {"checks": ["fresh_notebook_execution"]},
        "recovery": {"eligible": True},
    }


def _forbid_regeneration(monkeypatch):
    calls = []

    def forbidden(name):
        def call(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"Recovery must not call {name}")

        return call

    for name in ("create_run", "build", "run_agent_command", "fetch_source"):
        monkeypatch.setattr(agent, name, forbidden(name))
    return calls


@pytest.fixture
def controlled_threads(monkeypatch):
    instances = []

    class ControlledThread:
        def __init__(self, *, target, args=(), kwargs=None, daemon=None, **_options):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.alive = False
            instances.append(self)

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

        def finish(self):
            try:
                self.target(*self.args, **self.kwargs)
            finally:
                self.alive = False

    monkeypatch.setattr("threading.Thread", ControlledThread)
    return instances


def _open_run(root, monkeypatch):
    from agi_web.testing import AppTest

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "notebook-demo-ui",
            "--output",
            str(root.parent),
            "--resume",
            str(root),
        ],
    )
    app = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not app.exception
    return app


def _buttons(app, label):
    return [button for button in app.button if button.label == label]


def _button(app, label):
    found = _buttons(app, label)
    assert len(found) == 1, (label, [button.label for button in app.button])
    return found[0]


def _visible_messages(app):
    return "\n".join(
        str(element.value)
        for kind in ("error", "info", "warning", "caption", "markdown")
        for element in app.get(kind)
    )


def test_open_only_resume_exposes_retry_without_starting_work(
    tmp_path, monkeypatch, controlled_threads
):
    root = tmp_path / "20261015T120000Z-1234abcd"
    _failed_report(root)
    forbidden = _forbid_regeneration(monkeypatch)
    monkeypatch.setattr(
        agent, "recover_build", lambda *_a, **_k: pytest.fail("open executed recovery")
    )
    app = _open_run(root, monkeypatch)
    assert app.session_state.run_root == str(root)
    assert not _button(app, RETRY).disabled
    assert not controlled_threads
    assert not forbidden


def test_retry_uses_current_root_and_keeps_stale_failed_result_busy(
    tmp_path, monkeypatch, controlled_threads
):
    root = tmp_path / "20261015T120000Z-1234abcd"
    _failed_report(root)
    previous = (root / "result.json").read_bytes()
    forbidden = _forbid_regeneration(monkeypatch)
    recovered = []

    def recover(path):
        recovered.append(Path(path))
        report = _passed_report(root)
        (root / "result.json").write_text(json.dumps(report))
        return report

    monkeypatch.setattr(agent, "recover_build", recover)
    app = _open_run(root, monkeypatch)
    _button(app, RETRY).click().run()
    assert not app.exception
    assert app.session_state.run_root == str(root)
    assert len(controlled_threads) == 1
    assert controlled_threads[0].is_alive()
    assert (root / "result.json").read_bytes() == previous
    assert _button(app, "Build my app").disabled
    assert not any(not button.disabled for button in _buttons(app, RETRY))
    assert app.status and app.status[0].node["props"]["state"] == "running"
    app.run()
    assert len(controlled_threads) == 1
    controlled_threads[0].finish()
    app.run()
    assert not app.exception
    assert recovered == [root]
    assert not _button(app, "Build my app").disabled
    assert _button(app, "Try the app")
    assert not any(not button.disabled for button in _buttons(app, RETRY))
    assert not forbidden


def test_refused_recovery_return_is_visible_without_replacing_previous_report(
    tmp_path, monkeypatch, controlled_threads
):
    root = tmp_path / "20261015T120000Z-1234abcd"
    _failed_report(root)
    previous = (root / "result.json").read_bytes()
    forbidden = _forbid_regeneration(monkeypatch)
    refusal = {
        "status": "failed",
        "failed_phase": "recovery_preflight",
        "error": "Checkpoint changed before retry; start a new build",
        "project": str(root / "notebook_app_project"),
        "recovery": {"eligible": False, "reason": "Checkpoint changed before retry"},
    }
    monkeypatch.setattr(agent, "recover_build", lambda path: refusal)
    app = _open_run(root, monkeypatch)
    _button(app, RETRY).click().run()
    controlled_threads[0].finish()
    app.run()
    assert not app.exception
    assert refusal["error"] in _visible_messages(app)
    assert (root / "result.json").read_bytes() == previous
    assert app.session_state.run_root == str(root)
    assert not _button(app, RETRY).disabled
    assert not forbidden


def test_published_result_replaces_a_cached_recovery_refusal(
    tmp_path, monkeypatch, controlled_threads
):
    root = tmp_path / "20261015T120000Z-1234abcd"
    _failed_report(root)
    _forbid_regeneration(monkeypatch)
    refusal = {
        "status": "failed",
        "failed_phase": "recovery_preflight",
        "error": "Another verification currently owns this run",
        "project": str(root / "notebook_app_project"),
        "recovery": {"eligible": False, "reason": "Current owner is active"},
    }
    monkeypatch.setattr(agent, "recover_build", lambda path: refusal)
    app = _open_run(root, monkeypatch)
    _button(app, RETRY).click().run()
    controlled_threads[0].finish()
    app.run()
    assert refusal["error"] in _visible_messages(app)
    (root / "result.json").write_text(json.dumps(_passed_report(root)))
    app.run()
    assert not app.exception
    assert _button(app, "Try the app")
    assert refusal["error"] not in _visible_messages(app)
    assert not _buttons(app, RETRY)


def test_worker_completion_between_queue_read_and_dead_thread_check_is_preserved(
    tmp_path, monkeypatch, controlled_threads
):
    root = tmp_path / "20261015T120000Z-1234abcd"
    _failed_report(root)
    _forbid_regeneration(monkeypatch)
    completed = _passed_report(root)
    monkeypatch.setattr(agent, "recover_build", lambda path: completed)
    app = _open_run(root, monkeypatch)
    _button(app, RETRY).click().run()
    queue = app.session_state.run_result_queue
    worker = controlled_threads[0]

    class CompleteDuringFirstRead:
        first = True

        def get_nowait(self):
            if self.first:
                self.first = False
                worker.finish()
                raise Empty
            return queue.get_nowait()

    app.session_state.run_result_queue = CompleteDuringFirstRead()
    app.run()
    assert not app.exception
    assert app.session_state.run_operation_result == completed
    assert _button(app, "Try the app")
    assert "without a result" not in _visible_messages(app)


@pytest.mark.parametrize(
    "failure", ["exception", "invalid_return", "stopped_without_result"]
)
def test_failed_worker_surfaces_outcome_and_releases_busy_controls(
    tmp_path, monkeypatch, controlled_threads, failure
):
    root = tmp_path / "20261015T120000Z-1234abcd"
    _failed_report(root)
    _forbid_regeneration(monkeypatch)

    def recover(path):
        if failure == "exception":
            raise RuntimeError("Owned recovery fixture raised an exception")
        return None

    monkeypatch.setattr(agent, "recover_build", recover)
    app = _open_run(root, monkeypatch)
    _button(app, RETRY).click().run()
    if failure == "stopped_without_result":
        controlled_threads[0].alive = False
    else:
        controlled_threads[0].finish()
    app.run()
    assert not app.exception
    report = app.session_state.run_operation_result
    assert report["status"] == "failed" and report["failed_phase"] == "ui_worker"
    assert report["error"] in _visible_messages(app)
    assert not _button(app, "Build my app").disabled


def _wait_for_ui_operation(app):
    for _ in range(100):
        worker = app.session_state.get("build_thread")
        if worker is not None:
            worker.join(timeout=0.3)
        app.run()
        assert not app.exception
        if app.session_state.get("build_thread") is None:
            return
    pytest.fail("Owned notebook UI operation did not finish")


def test_same_ui_can_retry_real_recovery_after_temporary_lock_is_released(
    builder, monkeypatch
):
    from agilab.agent_runtime.notebook_build_checkpoint import build_lock

    root, original, deliveries = builder
    monkeypatch.setenv("AGILAB_RECOVERY_FIXTURE_FAIL", "1")
    previous = agent.build(root, notebook=original)
    assert previous["status"] == "failed" and previous["recovery"]["eligible"], previous
    previous_bytes = (root / "result.json").read_bytes()
    monkeypatch.delenv("AGILAB_RECOVERY_FIXTURE_FAIL")
    forbidden = _forbid_regeneration(monkeypatch)
    with build_lock(root):
        app = _open_run(root, monkeypatch)
        _button(app, RETRY).click().run()
        _wait_for_ui_operation(app)
        assert "already running" in _visible_messages(app)
        assert (root / "result.json").read_bytes() == previous_bytes
        assert not _button(app, RETRY).disabled
    _button(app, RETRY).click().run()
    _wait_for_ui_operation(app)
    completed = json.loads((root / "result.json").read_text())
    assert completed["status"] == "passed", completed
    assert app.session_state.run_root == str(root)
    assert _button(app, "Try the app")
    assert not _buttons(app, RETRY)
    assert len(deliveries) == 1
    assert not forbidden


def test_ineligible_failed_run_explains_why_retry_is_unavailable(
    tmp_path, monkeypatch, controlled_threads
):
    root = tmp_path / "20261015T120000Z-1234abcd"
    reason = "No verified provider checkpoint is available"
    _failed_report(root, eligible=False, reason=reason)
    forbidden = _forbid_regeneration(monkeypatch)
    app = _open_run(root, monkeypatch)
    assert reason in _visible_messages(app)
    assert not any(not button.disabled for button in _buttons(app, RETRY))
    assert not controlled_threads
    assert not forbidden


def test_completed_run_never_offers_retry(tmp_path, monkeypatch, controlled_threads):
    root = tmp_path / "20261015T120000Z-1234abcd"
    _failed_report(root)
    (root / "result.json").write_text(json.dumps(_passed_report(root)))
    forbidden = _forbid_regeneration(monkeypatch)
    app = _open_run(root, monkeypatch)
    assert _button(app, "Try the app")
    assert not _buttons(app, RETRY)
    assert not controlled_threads
    assert not forbidden


@pytest.mark.ui_robot
@pytest.mark.skipif(
    os.environ.get("AGILAB_RUN_NOTEBOOK_RECOVERY_UI_ROBOT") != "1",
    reason="set AGILAB_RUN_NOTEBOOK_RECOVERY_UI_ROBOT=1 for the real Chromium recovery journey",
)
def test_browser_retries_real_verification_without_new_run_or_provider(
    builder, monkeypatch, tmp_path
):
    from agi_web.react_python_host import ReactPythonServer
    from playwright.sync_api import expect, sync_playwright
    from test.conftest import REAL_HOME
    from tools.agilab_widget_robot import _attach_browser_issue_capture

    # Keep application HOME isolated while exposing only installed browser binaries.
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        for cache in (
            REAL_HOME / "Library/Caches/ms-playwright",
            REAL_HOME / ".cache/ms-playwright",
            REAL_HOME / "AppData/Local/ms-playwright",
        ):
            if cache.is_dir():
                monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(cache))
                break

    root, original, deliveries = builder
    monkeypatch.setenv("AGILAB_RECOVERY_FIXTURE_FAIL", "1")
    previous = agent.build(root, notebook=original)
    assert previous["status"] == "failed" and previous["recovery"]["eligible"], previous
    previous_bytes = (root / "result.json").read_bytes()
    previous_log = (root / "verification.log").read_bytes()
    run_entries_before = {path.name for path in root.parent.iterdir()}
    monkeypatch.delenv("AGILAB_RECOVERY_FIXTURE_FAIL")
    monkeypatch.setattr(agent.shutil, "which", _SYSTEM_WHICH)
    recover = agent.recover_build
    started, release = Event(), Event()
    recovery_calls = []

    def wait_then_recover(path):
        recovery_calls.append(Path(path))
        started.set()
        if not release.wait(timeout=30):
            raise TimeoutError("Browser did not release its owned recovery fixture")
        return recover(path)

    forbidden = _forbid_regeneration(monkeypatch)
    monkeypatch.setattr(agent, "recover_build", wait_then_recover)
    server = ReactPythonServer(
        ("127.0.0.1", 0),
        PAGE,
        argv=["--output", str(root.parent), "--resume", str(root)],
    )
    host = Thread(target=server.serve_forever, daemon=True)
    host.start()
    evidence = tmp_path / "notebook-builder-ui-recovery-browser-evidence"
    evidence.mkdir()
    report = {
        "schema": "agilab.notebook_demo_ui_recovery_browser.v1",
        "status": "failed",
        "run_root": str(root),
        "checks": [],
        "browser_issues": [],
    }
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            issues = _attach_browser_issue_capture(page)
            report["browser_issues"] = issues
            try:
                page.goto(f"{base}/?run={root.name}", wait_until="networkidle")
                retry = page.get_by_role("button", name=RETRY, exact=True)
                expect(retry).to_be_visible()
                assert not recovery_calls and not forbidden
                page.screenshot(
                    path=str(evidence / "notebook-builder-recovery-ready.png"),
                    full_page=True,
                )
                page.evaluate(
                    """replacements => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while ((node = walker.nextNode())) {
                        for (const [source, replacement] of replacements) {
                            node.data = node.data.split(source).join(replacement);
                        }
                    }
                    for (const element of document.querySelectorAll('input, textarea')) {
                        for (const [source, replacement] of replacements) {
                            element.value = element.value.split(source).join(replacement);
                        }
                    }
                }""",
                    [[str(root.parent), "/tmp/agilab-notebook-demo-runs"]],
                )
                retry.scroll_into_view_if_needed()
                page.screenshot(
                    path=str(
                        evidence
                        / "notebook-builder-recovery-controls-public-preview.png"
                    )
                )
                report["docs_preview_path_normalization"] = {
                    "scope": "Display text and input values only; browser reloaded before action",
                    "replacement": "/tmp/agilab-notebook-demo-runs",
                    "screenshot": "notebook-builder-recovery-controls-public-preview.png",
                }
                page.reload(wait_until="networkidle")
                expect(retry).to_be_visible()
                retry.click()
                assert started.wait(timeout=10), (
                    "Recovery click never reached the backend"
                )
                expect(
                    page.get_by_role("button", name="Build my app", exact=True)
                ).to_be_disabled()
                expect(retry).to_be_disabled()
                assert (root / "result.json").read_bytes() == previous_bytes
                assert recovery_calls == [root]
                release.set()
                expect(
                    page.get_by_role("button", name="Try the app", exact=True)
                ).to_be_visible(timeout=45000)
                expect(
                    page.get_by_role("button", name="Build my app", exact=True)
                ).to_be_enabled()
                expect(
                    page.get_by_role("button", name=RETRY, exact=True)
                ).to_have_count(0)
                completed = json.loads((root / "result.json").read_text())
                assert completed["status"] == "passed", completed
                assert completed["project"] == str(root / "notebook_app_project")
                assert len(deliveries) == 1
                assert {
                    path.name for path in root.parent.iterdir()
                } == run_entries_before
                assert len(list((root / "notebook_recovery_attempts").iterdir())) == 1
                assert (root / "verification.log").read_bytes() == previous_log
                attempt = root / completed["recovery"]["attempt"]
                assert (
                    attempt / "notebook_recovery_previous_result.json"
                ).read_bytes() == previous_bytes
                assert (
                    completed["verification"]["result_sha256"]
                    == completed["verification"]["workflow"]["result_sha256"]
                )
                page.reload(wait_until="networkidle")
                expect(
                    page.get_by_role("button", name="Try the app", exact=True)
                ).to_be_visible()
                assert recovery_calls == [root]
                assert root.name in page.url
                assert not forbidden
                assert not issues, issues
                report["browser_issues"] = list(issues)
                page.screenshot(
                    path=str(evidence / "notebook-builder-recovery-passed.png"),
                    full_page=True,
                )
                report["checks"] = [
                    "existing_run_opened_without_work",
                    "retry_dispatched_once",
                    "stale_failed_report_kept_busy",
                    "fresh_notebook_and_workflow_verified",
                    "previous_evidence_preserved",
                    "no_regeneration_or_provider",
                    "reload_preserves_completed_run",
                    "browser_development_log_clean",
                ]
                report["status"] = "passed"
            finally:
                if report["status"] != "passed":
                    page.screenshot(
                        path=str(evidence / "notebook-builder-recovery-failed.png"),
                        full_page=True,
                    )
                context.close()
                browser.close()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        host.join(timeout=10)
        (evidence / "notebook-builder-ui-recovery-browser-validation.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
