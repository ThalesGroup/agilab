"""Native browser proof for PROJECT transfers, using owned workerless fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest


EXPORT_PHASES = (
    "Checking project and export settings",
    "Writing project archive",
)
IMPORT_PHASES = (
    "Checking archive and destination",
    "Checking archive contents",
    "Extracting project files",
    "Preparing imported project",
    "Checking imported project",
)


@pytest.fixture(scope="session")
def project_transfer_chromium_executable() -> str:
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="Native PROJECT transfer robot requires Playwright",
    )
    # Resolve the browser cache before each test replaces HOME with an owned root.
    with playwright.sync_playwright() as engine:
        return engine.chromium.executable_path


def _status_labels(value: object) -> list[str]:
    if isinstance(value, dict):
        labels = (
            [str(value.get("props", {}).get("label", ""))]
            if value.get("kind") == "status"
            else []
        )
        return labels + [
            label for child in value.values() for label in _status_labels(child)
        ]
    if isinstance(value, list):
        return [label for child in value for label in _status_labels(child)]
    return []


def _write_transfer_view(
    view: Path, root: Path, operation: str, invalid: bool, activate: bool = False
) -> None:
    """Use real transfer helpers; the rendezvous only holds their reported phases."""
    editor = Path(__file__).resolve().parents[1] / "src/agilab/pages/PROJECT_EDITOR.py"
    view.write_text(
        textwrap.dedent(
            f"""\
            import importlib.util
            import json
            import time
            from pathlib import Path
            from types import SimpleNamespace

            from agi_web import python_ui as ui
            from agilab.action_execution import ActionSpec, run_streamlit_action

            spec = importlib.util.spec_from_file_location("transfer_robot_project", {str(editor)!r})
            project = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(project)
            root = Path({str(root)!r})
            operation = {operation!r}
            invalid = {invalid!r}
            activate = {activate!r}
            name = operation.title() + " project"
            start = operation.title() + "ing project..."
            ui.set_page_config(page_title="PROJECT transfer progress robot", layout="wide")
            ui.title("PROJECT transfer progress robot")

            def rendezvous(index):
                release = root / "gates" / str(index)
                deadline = time.monotonic() + 20
                while not release.exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Browser did not acknowledge transfer phase " + str(index))
                    time.sleep(0.02)

            def transfer(report):
                rendezvous(0)
                index = 0

                def hold_phase(label):
                    nonlocal index
                    report(label)
                    index += 1
                    rendezvous(index)

                if operation == "export":
                    env = SimpleNamespace(
                        app="demo_project",
                        active_app=root / ("missing_project" if invalid else "source_project"),
                        export_apps=root / "exports",
                    )
                    return project._export_project_action(env, on_progress=hold_phase)
                env = SimpleNamespace(export_apps=root / "exports", apps_path=root / "apps")
                archive = "corrupt_project.zip" if invalid else "demo_project.zip"
                return project._import_project_action(
                    env, project_zip=archive, clean=False, overwrite=False,
                    on_progress=hold_phase,
                )

            if activate:
                class RobotEnv:
                    def __init__(self):
                        self.app = "source_project"
                        self.active_app = root / "source_project"
                        self.target = self.app
                        self.apps_path = root / "apps"
                        self.export_apps = root / "exports"
                        self.AGILAB_EXPORT_ABS = root / "data_exports"
                        self.st_resources = root / "editor_resources"
                        self.st_resources.mkdir()
                        for filename, content in (
                            ("custom_buttons.json", "[]"),
                            ("info_bar.json", "{{}}"),
                            ("code_editor.scss", ""),
                        ):
                            (self.st_resources / filename).write_text(content, encoding="utf-8")

                    def change_app(self, app):
                        self.app = Path(app).name
                        self.target = self.app
                        self.active_app = self.apps_path / self.app
                        with (root / "activation_history.jsonl").open("a", encoding="utf-8") as log:
                            log.write(json.dumps(dict(app=self.app, active_app=str(self.active_app))) + "\\n")

                env = ui.session_state.get("_robot_env")
                if env is None:
                    env = RobotEnv()
                    ui.session_state["_robot_env"] = env
                ui.session_state.setdefault("sidebar_selection", "Import")
                ui.session_state.setdefault("archive", "demo_project.zip")
                project.ensure_page_env = lambda *_args: env
                project.render_page_chrome = lambda *_args, **_kwargs: None
                project.background_services_enabled = lambda: False
                project.get_templates = lambda: []
                project.get_projects_zip = lambda: ["demo_project.zip"]
                project._load_project_editor_resources = lambda *_args: ([], "", "")
                project._render_active_project_sidebar = lambda _env: None
                project._render_pypi_app_install_action = lambda _env: None
                project.handle_project_selection = lambda: ui.caption("Local workerless editor")

                original_import = project._import_project_action

                def held_import(current_env, **kwargs):
                    report = kwargs.pop("on_progress")
                    rendezvous(0)
                    index = 0

                    def hold_phase(label):
                        nonlocal index
                        report(label)
                        index += 1
                        rendezvous(index)

                    return original_import(current_env, **kwargs, on_progress=hold_phase)

                project._import_project_action = held_import
                with (root / "activation_render_history.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps(dict(app=env.app, switch_to_edit=ui.session_state.get("switch_to_edit", False))) + "\\n")
                project.page()
                ui.caption("Activated project: " + env.app)
                (root / "activation_final.json").write_text(
                    json.dumps(dict(
                        app=env.app,
                        switch_to_edit=ui.session_state.get("switch_to_edit", False),
                        banner_pending=project.PROJECT_ACTION_BANNER_KEY in ui.session_state,
                    )),
                    encoding="utf-8",
                )
            elif ui.button(name, key="robot_transfer"):
                run_streamlit_action(
                    ui, ActionSpec(name=name, start_message=start),
                    action_with_progress=transfer,
                )
            """
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("operation", "invalid", "phases", "activate"),
    [
        pytest.param("export", False, EXPORT_PHASES, False, id="export-success"),
        pytest.param("export", True, EXPORT_PHASES[:1], False, id="export-error"),
        pytest.param("import", False, IMPORT_PHASES, False, id="import-success"),
        pytest.param("import", True, IMPORT_PHASES[:2], False, id="import-error"),
        pytest.param(
            "import", False, IMPORT_PHASES, True, id="import-activation-rerun"
        ),
    ],
)
def test_project_transfer_reports_live_phases_and_terminal_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    invalid: bool,
    phases: tuple[str, ...],
    activate: bool,
    project_transfer_chromium_executable: str,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    from tools.agilab_web_robot import (
        ReactPythonServer,
        _free_port,
        wait_for_react_health,
    )

    home = tmp_path / "agilab-project-transfer-robot-home"
    home.mkdir(mode=0o700)
    root = home / "transfer-fixture"
    for directory in ("source_project", "exports", "apps", "gates"):
        (root / directory).mkdir(parents=True)
    (root / "source_project/keep.txt").write_text(
        "owned robot payload\n", encoding="utf-8"
    )
    if operation == "import":
        with zipfile.ZipFile(root / "exports/demo_project.zip", "w") as archive:
            archive.writestr("keep.txt", "owned robot payload\n")
        (root / "exports/corrupt_project.zip").write_bytes(b"not a project archive")
    view = home / "agilab_project_transfer_progress_robot_view.py"
    _write_transfer_view(view, root, operation, invalid, activate)
    evidence = home / "agilab-project-transfer-progress-evidence"
    evidence.mkdir()
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(home))
    monkeypatch.setenv("HOMEDRIVE", home.drive)
    monkeypatch.setenv("HOMEPATH", str(home)[len(home.drive) :])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "127.0.0.1")

    url = f"http://127.0.0.1:{_free_port()}"
    command = [
        sys.executable,
        "-m",
        "agi_web.react_python_host",
        str(view),
        "--address",
        "127.0.0.1",
        "--port",
        url.rsplit(":", 1)[1],
        "--no-browser",
    ]
    issues: list[dict[str, object]] = []
    snapshots: list[dict[str, object]] = []
    observed: list[str] = []
    completed_events: list[str] = []
    validated = False
    with ReactPythonServer(command, env=dict(os.environ), url=url) as server:
        assert wait_for_react_health(url, timeout=30).success, server.output_tail()
        with playwright.sync_playwright() as engine:
            browser = engine.chromium.launch(
                executable_path=project_transfer_chromium_executable
            )
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            def observe_response(response) -> None:
                if response.status >= 400:
                    issues.append(
                        {"kind": "http", "status": response.status, "url": response.url}
                    )
                if response.url.endswith("/api/progress") and response.ok:
                    payload = response.json()
                    snapshots.append(
                        {
                            "running": payload.get("running"),
                            "labels": _status_labels(payload.get("nodes", [])),
                        }
                    )
                if response.url.endswith("/api/action"):
                    completed_events.append(response.url)

            page.on("response", observe_response)
            page.on(
                "pageerror",
                lambda error: issues.append(
                    {"kind": "pageerror", "detail": str(error)}
                ),
            )
            page.on(
                "console",
                lambda message: (
                    issues.append(
                        {
                            "kind": "console",
                            "level": message.type,
                            "detail": message.text,
                        }
                    )
                    if message.type in {"warning", "error"}
                    else None
                ),
            )
            page.on(
                "requestfailed",
                lambda request: issues.append(
                    {
                        "kind": "requestfailed",
                        "url": request.url,
                        "detail": request.failure,
                    }
                ),
            )
            try:
                page.goto(url)
                page.get_by_role(
                    "heading", name="PROJECT transfer progress robot", exact=True
                ).wait_for(state="visible")
                startup_errors = page.locator(
                    ".py-exception, .py-error"
                ).all_text_contents()
                assert not startup_errors, (
                    "Native fixture failed before the transfer action: "
                    + "\n".join(startup_errors)
                )
                if activate:
                    page.get_by_role("button", name="Tools", exact=True).click()
                completed_events.clear()
                name = operation.title() + " project"
                start = (
                    "Importing project 'demo_project'..."
                    if activate
                    else operation.title() + "ing project..."
                )
                status = page.locator('details[data-widget-kind="status"]')
                with page.expect_response(
                    lambda response: response.url.endswith("/api/action"),
                    timeout=45_000,
                ):
                    page.get_by_role(
                        "button", name="Import" if activate else name, exact=True
                    ).click()
                    for index, label in enumerate((start, *phases)):
                        playwright.expect(status.locator("summary")).to_have_text(
                            label, timeout=10_000
                        )
                        playwright.expect(status).to_have_attribute(
                            "data-state", "running"
                        )
                        assert status.get_attribute("open") is not None
                        assert not completed_events, (
                            "Progress must render before the action response finishes"
                        )
                        observed.append(label)
                        page.screenshot(
                            path=str(
                                evidence / f"agilab-project-transfer-phase-{index}.png"
                            )
                        )
                        (root / "gates" / str(index)).touch()

                if activate:
                    playwright.expect(status).to_have_count(0)
                    playwright.expect(
                        page.get_by_text("Activated project: demo_project", exact=True)
                    ).to_be_visible()
                    activation = json.loads(
                        (root / "activation_final.json").read_text()
                    )
                    assert activation == {
                        "app": "demo_project",
                        "switch_to_edit": False,
                        "banner_pending": False,
                    }
                    changes = [
                        json.loads(line)
                        for line in (root / "activation_history.jsonl")
                        .read_text()
                        .splitlines()
                    ]
                    assert len(changes) == 2
                    assert all(change["app"] == "demo_project" for change in changes)
                    renders = [
                        json.loads(line)
                        for line in (root / "activation_render_history.jsonl")
                        .read_text()
                        .splitlines()
                    ]
                    assert len(renders) >= 4
                    assert any(render["switch_to_edit"] for render in renders[:-1])
                    assert renders[-1] == {
                        "app": "demo_project",
                        "switch_to_edit": False,
                    }
                else:
                    playwright.expect(status.locator("summary")).to_have_text(name)
                    playwright.expect(status).to_have_attribute(
                        "data-state", "error" if invalid else "complete"
                    )
                    assert (status.get_attribute("open") is not None) is invalid
                    for phase in phases:
                        assert phase in status.text_content(), (
                            "The status must retain phase history"
                        )
                for phase in phases:
                    assert any(
                        snapshot["running"] and phase in snapshot["labels"]
                        for snapshot in snapshots
                    ), phase
                assert any(
                    snapshot["running"] and start in snapshot["labels"]
                    for snapshot in snapshots
                )
                result = page.locator(".py-error" if invalid else ".py-success")
                playwright.expect(result).to_be_visible()
                if activate:
                    playwright.expect(result).to_have_text(
                        "Project 'demo_project' successfully imported."
                    )
                if operation == "import":
                    destination = (
                        root
                        / "apps"
                        / ("corrupt_project" if invalid else "demo_project")
                    )
                    if invalid:
                        assert not destination.exists(), (
                            "A corrupt archive must not create a project"
                        )
                        assert not list((root / "apps").glob(".*.import-*")), (
                            "Failed import staging must be cleaned"
                        )
                    else:
                        assert (destination / "keep.txt").read_text(
                            encoding="utf-8"
                        ) == "owned robot payload\n"
                elif not invalid:
                    with zipfile.ZipFile(root / "exports/demo_project.zip") as archive:
                        assert archive.read("keep.txt") == b"owned robot payload\n"
                else:
                    assert not (root / "exports/demo_project.zip").exists()
                assert not issues, issues
                validated = True
            finally:
                try:
                    page.screenshot(
                        path=str(evidence / "agilab-project-transfer-terminal.png")
                    )
                except Exception as exc:
                    validated = False
                    issues.append({"kind": "screenshot", "detail": str(exc)})
                validated = validated and not issues
                repo = Path(__file__).resolve().parents[1]
                (evidence / "agilab-project-transfer-terminal-dom.html").write_text(
                    page.content(), encoding="utf-8"
                )
                (
                    evidence / "agilab-project-transfer-progress-browser-evidence.json"
                ).write_text(
                    json.dumps(
                        {
                            "scenario": f"project-transfer-native-{operation}-{'activation-rerun' if activate else 'error' if invalid else 'success'}",
                            "status": "passed" if validated else "failed",
                            "command": [sys.executable, "-m", "pytest", *sys.argv[1:]],
                            "source_sha256": {
                                str(path.relative_to(repo)): hashlib.sha256(
                                    path.read_bytes()
                                ).hexdigest()
                                for path in (
                                    repo / "src/agilab/pages/PROJECT_EDITOR.py",
                                    repo / "src/agilab/workflow/action_execution.py",
                                    Path(__file__).resolve(),
                                )
                            },
                            "operation": operation,
                            "invalid": invalid,
                            "activation_rerun": activate,
                            "observed": observed,
                            "progress_snapshots": snapshots,
                            "browser_issues": issues,
                            "view_errors": [
                                text[:1500]
                                for text in page.locator(
                                    ".py-exception, .py-error"
                                ).all_text_contents()[:4]
                            ],
                            "screenshots": sorted(
                                path.name for path in evidence.glob("*.png")
                            ),
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                browser.close()
            assert validated, f"Browser evidence failed: {evidence}"
