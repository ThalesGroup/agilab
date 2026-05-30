from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


def _import_agilab_module(module_name: str):
    module_path = Path(__file__).resolve().parents[1] / "src" / "agilab" / f"{module_name.rsplit('.', 1)[-1]}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


workflow_ui = _import_agilab_module("agilab.workflow_ui")


class _FakeContainer:
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def caption(self, body: object):
        self._streamlit.events.append(("caption", str(body)))

    def button(self, label: str, key: str | None = None, **kwargs):
        return self._streamlit.button(label, key=key, **kwargs)

    def download_button(self, label: str, key: str | None = None, **kwargs):
        return self._streamlit.download_button(label, key=key, **kwargs)

    def code(self, body: object, language: str | None = None):
        self._streamlit.events.append(("code", f"{language}:{body}"))

    def json(self, body: object):
        self._streamlit.events.append(("json", str(body)))

    def image(self, body: object, **kwargs):
        self._streamlit.events.append(("image", str(body)))

    def markdown(self, body: object, **kwargs):
        self._streamlit.events.append(("markdown", str(body)))

    def link_button(self, label: str, url: str, key: str | None = None, **kwargs):
        self._streamlit.link_button(label, url, key=key, **kwargs)


class _FakeSidebar:
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def expander(self, title: str, expanded: bool = False):
        self._streamlit.events.append(("sidebar.expander", f"{title}:{expanded}"))
        return _FakeContainer(self._streamlit)


class _FakeStreamlit:
    def __init__(self, *, buttons: dict[str, bool] | None = None):
        self.events: list[tuple[str, str]] = []
        self.buttons = buttons or {}
        self.sidebar = _FakeSidebar(self)

    def expander(self, title: str, expanded: bool = False):
        self.events.append(("expander", f"{title}:{expanded}"))
        return _FakeContainer(self)

    def container(self, **kwargs):
        self.events.append(("container", str(bool(kwargs.get("border", False)))))
        return _FakeContainer(self)

    def columns(self, specs):
        count = len(specs) if isinstance(specs, (list, tuple)) else int(specs)
        return [_FakeContainer(self) for _ in range(count)]

    def markdown(self, body: object, **kwargs):
        self.events.append(("markdown", str(body)))

    def caption(self, body: object):
        self.events.append(("caption", str(body)))

    def button(self, label: str, key: str | None = None, **kwargs):
        self.events.append(("button", f"{key or label}:{kwargs.get('disabled', False)}"))
        if kwargs.get("disabled"):
            return False
        return bool(self.buttons.get(str(key or label), False))

    def download_button(self, label: str, key: str | None = None, **kwargs):
        self.events.append(("download", f"{key or label}:{kwargs.get('disabled', False)}"))
        return False

    def code(self, body: object, language: str | None = None):
        self.events.append(("code", f"{language}:{body}"))

    def json(self, body: object):
        self.events.append(("json", str(body)))

    def image(self, body: object, **kwargs):
        self.events.append(("image", str(body)))

    def link_button(self, label: str, url: str, key: str | None = None, **kwargs):
        self.events.append(("link_button", f"{label}:{url}:{key or ''}:{kwargs.get('type', '')}"))


def test_fake_streamlit_and_sidebar_helpers_are_exercised() -> None:
    streamlit = _FakeStreamlit()
    sidebar = _FakeSidebar(streamlit)

    container = sidebar.expander("Context", expanded=True)
    container.caption("ok")
    assert ("sidebar.expander", "Context:True") in streamlit.events

    streamlit.code("payload", language="text")
    streamlit.json({"state": "ready"})
    streamlit.image(b"PNG")
    assert ("code", "text:payload") in streamlit.events
    assert ("json", "{'state': 'ready'}") in streamlit.events
    assert ("image", "b'PNG'") in streamlit.events

    graph = type("_BadGraph", (), {"number_of_nodes": lambda self: "bad", "number_of_edges": lambda self: 1})
    assert graph().number_of_nodes() == "bad"
    assert graph().number_of_edges() == 1


def test_render_page_context_renders_project_cockpit(tmp_path) -> None:
    fake_st = _FakeStreamlit()
    runenv = tmp_path / "run"
    runenv.mkdir()
    (runenv / "run_001.log").write_text("ok\n", encoding="utf-8")
    (runenv / "run_manifest.json").write_text("{}", encoding="utf-8")
    env = SimpleNamespace(
        app="flight_telemetry_project",
        target="flight_telemetry_worker",
        active_app=tmp_path,
        runenv=runenv,
        app_data_rel=tmp_path / "data",
    )

    workflow_ui.render_page_context(fake_st, page_label="ORCHESTRATE", env=env)

    markdown = "\n".join(body for kind, body in fake_st.events if kind == "markdown")
    assert "Project cockpit" in markdown
    assert "flight_telemetry_project" in markdown
    assert "run_manifest.json" in markdown
    assert "agilab-header-card" in markdown
    assert (
        "link_button",
        "Review evidence:/ANALYSIS?active_app=flight_telemetry_project:project_cockpit:ORCHESTRATE:next:analysis:primary",
    ) in fake_st.events


def test_project_widget_key_is_scoped_by_page_and_project() -> None:
    env = SimpleNamespace(app="flight_telemetry_project", target="flight_telemetry_worker")

    assert (
        workflow_ui.project_widget_key("ORCHESTRATE", env, "cluster enabled")
        == "ORCHESTRATE::flight_telemetry_project::flight_telemetry_worker::cluster_enabled"
    )
    assert (
        workflow_ui.project_state_key("ORCHESTRATE", env, "drawer open")
        == "ORCHESTRATE::flight_telemetry_project::flight_telemetry_worker::state::drawer_open"
    )


def test_next_best_action_guides_install_execute_and_analysis(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    env = SimpleNamespace(app="demo_project", target="demo", active_app=project)

    monkeypatch.setattr(
        workflow_ui,
        "_project_install_status",
        lambda _env: ("Not installed", "run ORCHESTRATE -> INSTALL", "incomplete"),
    )
    assert workflow_ui.project_next_action(env)["id"] == "install"

    monkeypatch.setattr(
        workflow_ui,
        "_project_install_status",
        lambda _env: ("Ready", "manager and worker ready", "ready"),
    )
    assert workflow_ui.project_next_action(env)["id"] == "execute"

    runenv = tmp_path / "run"
    runenv.mkdir()
    (runenv / "run_001.log").write_text("ok\n", encoding="utf-8")
    (runenv / "run_manifest.json").write_text("{}", encoding="utf-8")
    env.runenv = runenv

    assert workflow_ui.project_next_action(env)["id"] == "analysis"


def test_project_evidence_drawer_lists_latest_artifacts(tmp_path) -> None:
    runenv = tmp_path / "run"
    runenv.mkdir()
    (runenv / "run_manifest.json").write_text("{}", encoding="utf-8")
    (runenv / "metrics.csv").write_text("x\n1\n", encoding="utf-8")
    env = SimpleNamespace(app="demo_project", target="demo", active_app=tmp_path, runenv=runenv)
    fake_st = _FakeStreamlit()

    workflow_ui.render_project_evidence_drawer(
        fake_st,
        env=env,
        key_prefix="demo:evidence",
        expanded=True,
    )

    assert ("expander", "Evidence drawer:True") in fake_st.events
    assert ("caption", "Run manifest: Ready (manifest)") in fake_st.events
    assert ("caption", "Table: Ready (csv)") in fake_st.events


def test_is_dag_based_app_uses_env_worker_base_and_identity_fallback() -> None:
    assert workflow_ui.is_dag_based_app(
        SimpleNamespace(app="workflow_project", target="workflow", base_worker_cls="DagWorker"),
        "workflow_project",
    )
    assert workflow_ui.is_dag_based_app(
        SimpleNamespace(app="sb3_trainer_project", target="sb3_trainer", base_worker_cls="Sb3TrainerWorker"),
        "sb3_trainer_project",
    )
    assert workflow_ui.is_dag_based_app(
        SimpleNamespace(app="custom_project", target="custom", base_worker_cls="CustomDagWorker"),
        "custom_project",
    )
    assert workflow_ui.is_dag_based_app(
        SimpleNamespace(app="multi_app_dag_project", target="multi_app_dag", base_worker_cls="PolarsWorker"),
        "multi_app_dag_project",
    )
    assert not workflow_ui.is_dag_based_app(
        SimpleNamespace(app="flight_telemetry_project", target="flight_telemetry", base_worker_cls="PolarsWorker"),
        "flight_telemetry_project",
    )


def test_workflow_state_scope_target_variants() -> None:
    assert workflow_ui.workflow_state_scope(
        "WORKFLOW",
        SimpleNamespace(app="flight_telemetry_project", target="flight_telemetry_worker"),
    ) == "WORKFLOW::flight_telemetry_project::flight_telemetry_worker"
    assert workflow_ui.workflow_state_scope(
        "WORKFLOW",
        SimpleNamespace(app="flight_telemetry_project", target="flight_telemetry_project"),
    ) == "WORKFLOW::flight_telemetry_project"
    assert workflow_ui.workflow_state_scope("WORKFLOW", SimpleNamespace(app="flight_telemetry_project")) == "WORKFLOW::flight_telemetry_project"


def test_is_dag_based_app_identity_fallback_without_worker_class() -> None:
    assert workflow_ui.is_dag_based_app(SimpleNamespace(app="pipeline_dag_project", target="worker")) is True
    assert workflow_ui.is_dag_based_app(
        SimpleNamespace(app="global", active_app="simple"),
        "global",
    ) is False


def test_render_log_actions_can_download_and_clear() -> None:
    fake_st = _FakeStreamlit(buttons={"clear": True})

    assert workflow_ui.render_log_actions(
        fake_st,
        body="line 1",
        download_key="download",
        file_name="run.log",
        clear_key="clear",
    )

    assert ("download", "download:False") in fake_st.events
    assert ("button", "clear:False") in fake_st.events


def test_render_log_actions_disables_empty_actions() -> None:
    fake_st = _FakeStreamlit(buttons={"clear": True})

    assert not workflow_ui.render_log_actions(
        fake_st,
        body="",
        download_key="download",
        file_name="run.log",
        clear_key="clear",
    )

    assert ("download", "download:True") in fake_st.events
    assert ("button", "clear:True") in fake_st.events


def test_render_latest_outputs_summarizes_dataframe_and_downloads(tmp_path) -> None:
    fake_st = _FakeStreamlit()
    output = tmp_path / "output.csv"
    output.write_text("a\n1\n", encoding="utf-8")

    workflow_ui.render_latest_outputs(
        fake_st,
        source_path=output,
        dataframe=pd.DataFrame({"a": [1]}),
        key_prefix="demo",
    )

    assert ("expander", "Latest outputs:False") in fake_st.events
    assert ("caption", "Dataframe: 1 row(s), 1 column(s)") in fake_st.events
    assert ("caption", f"Source: {output}") in fake_st.events
    assert ("download", "demo:download_output:False") in fake_st.events


def test_project_ui_state_is_scoped_by_page_and_project() -> None:
    session_state = {}
    env = SimpleNamespace(app="flight_telemetry_project", target="flight_telemetry_worker")

    workflow_ui.remember_project_ui_state(
        session_state,
        page_label="WORKFLOW",
        env=env,
        values={"artifact_drawer_open": True},
    )

    assert workflow_ui.restore_project_ui_state(
        session_state,
        page_label="WORKFLOW",
        env=env,
    ) == {"artifact_drawer_open": True}
    assert workflow_ui.restore_project_ui_state(
        session_state,
        page_label="ORCHESTRATE",
        env=env,
    ) == {}


def test_render_workflow_timeline_latest_run_and_artifacts(tmp_path) -> None:
    fake_st = _FakeStreamlit()
    artifact = tmp_path / "contract.json"
    artifact.write_text('{"ok": true}', encoding="utf-8")
    log_file = tmp_path / "run.log"
    log_file.write_text("done\n", encoding="utf-8")

    workflow_ui.render_workflow_timeline(
        fake_st,
        items=[
            {"label": "Configure", "state": "done", "detail": "project ready"},
            ("Run", "active", "executing"),
        ],
    )
    workflow_ui.render_latest_run_card(
        fake_st,
        status="complete",
        output_path=artifact,
        log_path=log_file,
        key_prefix="demo",
    )
    workflow_ui.render_artifact_drawer(
        fake_st,
        artifacts=[
            {"label": "Contract", "path": artifact, "kind": "json"},
            {"label": "Run log", "path": log_file, "kind": "log"},
        ],
        key_prefix="demo",
    )

    assert ("expander", "Workflow:False") in fake_st.events
    assert ("caption", "1. Configure - Done: project ready") in fake_st.events
    assert ("caption", "2. Run - Active: executing") in fake_st.events
    assert ("expander", "Latest run:False") in fake_st.events
    assert ("caption", "Status: Done") in fake_st.events
    assert ("download", "demo:latest_output:False") in fake_st.events
    assert ("download", "demo:latest_log:False") in fake_st.events
    assert ("expander", "Artifacts:False") in fake_st.events
    assert ("caption", "Contract: Ready (json)") in fake_st.events
    assert ("json", "{'ok': True}") in fake_st.events
    assert any(event == ("code", "text:done\n") for event in fake_st.events)


def test_render_workflow_timeline_filters_blank_items_and_keeps_valid_rows() -> None:
    fake_st = _FakeStreamlit()

    workflow_ui.render_workflow_timeline(
        fake_st,
        items=[
            {"label": "", "state": "done", "detail": "ignored"},
            {"name": "Prepare", "state": "running", "detail": "ok"},
            ("",),
            "Execute",
            {"label": "Upload", "path": "/tmp"},
        ],
    )

    assert ("expander", "Workflow:False") in fake_st.events
    assert ("caption", "1. Prepare - Running: ok") in fake_st.events
    assert ("caption", "2. Execute - Waiting") in fake_st.events
    assert ("caption", "3. Upload - Waiting: /tmp") in fake_st.events
    assert not any("ignored" in value for event, value in fake_st.events if event == "caption")


def test_render_command_bar_returns_clicked_command() -> None:
    fake_st = _FakeStreamlit(buttons={"demo:command:run": True, "demo:command:delete": True})

    selected = workflow_ui.render_command_bar(
        fake_st,
        commands=[
            {"id": "run", "label": "Run", "enabled": True, "type": "primary"},
            {"id": "delete", "label": "Delete", "enabled": False, "reason": "No output"},
        ],
        key_prefix="demo",
    )

    assert selected == "run"
    assert ("caption", "Quick actions") in fake_st.events
    assert ("button", "demo:command:run:False") in fake_st.events
    assert ("button", "demo:command:delete:True") in fake_st.events


def test_action_history_records_and_renders_project_scope() -> None:
    fake_st = _FakeStreamlit()
    env = SimpleNamespace(app="flight_telemetry_project")

    workflow_ui.record_action_history(
        fake_st.__dict__.setdefault("session_state", {}),
        page_label="ORCHESTRATE",
        env=env,
        title="Dataframe exported",
        status="done",
        detail="2 row(s)",
        artifact="/tmp/export.csv",
    )
    workflow_ui.render_action_history(
        fake_st,
        session_state=fake_st.session_state,
        page_label="ORCHESTRATE",
        env=env,
    )

    assert ("expander", "Recent activity:False") in fake_st.events
    assert any("Dataframe exported: Done" in value for event, value in fake_st.events if event == "caption")
    assert ("caption", "2 row(s)") in fake_st.events
    assert ("caption", "Artifact: /tmp/export.csv") in fake_st.events


def test_project_state_and_basic_render_edge_cases(monkeypatch, tmp_path) -> None:
    env = SimpleNamespace(app="", target="", mode="Serve")
    scope = workflow_ui.workflow_state_scope("MAIN_PAGE", env)
    state = {workflow_ui.PROJECT_UI_STATE_KEY: "stale"}

    assert workflow_ui.remember_project_ui_state(
        state,
        page_label="MAIN_PAGE",
        env=env,
        values={"drawer": False},
    ) == {"drawer": False}
    assert state[workflow_ui.PROJECT_UI_STATE_KEY][scope] == {"drawer": False}

    state[workflow_ui.PROJECT_UI_STATE_KEY][scope] = "stale"
    assert workflow_ui.remember_project_ui_state(
        state,
        page_label="MAIN_PAGE",
        env=env,
        values={"drawer": True},
    ) == {"drawer": True}
    assert workflow_ui.restore_project_ui_state(
        {workflow_ui.PROJECT_UI_STATE_KEY: "stale"},
        page_label="MAIN_PAGE",
        env=env,
    ) == {}
    assert workflow_ui.restore_project_ui_state(
        {workflow_ui.PROJECT_UI_STATE_KEY: {scope: "stale"}},
        page_label="MAIN_PAGE",
        env=env,
    ) == {}

    events: list[tuple[str, str]] = []

    class _CaptionOnly:
        def caption(self, body):
            events.append(("caption", str(body)))

    caption_widget = _CaptionOnly()
    caption_widget.caption("context banner")
    workflow_ui.render_page_context(SimpleNamespace(sidebar=_CaptionOnly()), page_label="MAIN_PAGE", env=env)
    assert ("caption", "context banner") in events
    assert events == [("caption", "context banner")]

    fake_st = _FakeStreamlit()
    workflow_ui.render_log_actions(fake_st, body="only download", download_key="dl", file_name="run.log")
    workflow_ui.render_action_readiness(fake_st, actions=())
    workflow_ui.render_workflow_timeline(fake_st, items=("",))
    workflow_ui.render_command_bar(fake_st, commands=(), key_prefix="demo")
    workflow_ui.render_latest_run_card(fake_st, key_prefix="demo")
    assert ("download", "dl:False") in fake_st.events

    class _BadShape:
        empty = False
        shape = ("bad", 1)

    class _BadGraph:
        def number_of_nodes(self):
            return "bad"

        def number_of_edges(self):
            return 1

    class _BadGraphEdges:
        def number_of_nodes(self):
            return 2

        def number_of_edges(self):
            return "bad"

    assert workflow_ui._dataframe_shape(_BadShape()) is None
    assert _BadGraph().number_of_edges() == 1
    assert workflow_ui._graph_shape(_BadGraph()) is None
    assert workflow_ui._graph_shape(_BadGraphEdges()) is None

    class _GoodGraph:
        def number_of_nodes(self):
            return 2

        def number_of_edges(self):
            return 1

    output = tmp_path / "large.csv"
    output.write_text("a\n1\n", encoding="utf-8")
    monkeypatch.setattr(workflow_ui, "MAX_INLINE_DOWNLOAD_BYTES", 2)
    workflow_ui.render_latest_outputs(fake_st, source_path=output, graph=_GoodGraph(), key_prefix="big")
    assert ("caption", "Graph: 2 node(s), 1 edge(s)") in fake_st.events
    assert ("caption", "Output file is too large for inline download: large.csv") in fake_st.events


def test_workflow_ui_project_context_remaining_edges(monkeypatch, tmp_path) -> None:
    assert workflow_ui._project_display_name(None) == "No project"
    assert workflow_ui._project_display_name(SimpleNamespace()) == "No project"
    assert workflow_ui._project_path(None) is None
    assert workflow_ui._project_path(SimpleNamespace(app="demo_project")) is None
    assert workflow_ui._runtime_roots(None) == []
    assert workflow_ui._artifact_label(tmp_path / "figure.svg") == "Figure"
    assert workflow_ui._artifact_label(tmp_path / "notebook.ipynb") == "Notebook"
    assert workflow_ui._artifact_description(tmp_path / "outside.log", tmp_path / "root") == "outside.log"

    app_root = tmp_path / "apps" / "demo_project"
    app_root.mkdir(parents=True)
    env = SimpleNamespace(app="demo_project", apps_path=tmp_path / "apps", runenv=tmp_path / "missing-run")
    assert workflow_ui._project_path(env) == app_root

    artifacts_root = app_root / "artifacts"
    artifacts_root.mkdir()
    manifest = artifacts_root / "run_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    table = artifacts_root / "metrics.csv"
    table.write_text("x\n1\n", encoding="utf-8")
    ignored = artifacts_root / ".git" / "ignored.csv"
    ignored.parent.mkdir()
    ignored.write_text("x\n", encoding="utf-8")
    scanned = workflow_ui._scan_project_evidence(env)
    assert scanned["count"] == 2
    assert scanned["manifest"] == manifest
    assert [artifact["label"] for artifact in scanned["artifacts"]][:2] == ["Table", "Run manifest"]

    with monkeypatch.context() as scoped_monkeypatch:
        scoped_monkeypatch.setattr(
            workflow_ui.os,
            "walk",
            lambda _root: (_ for _ in ()).throw(OSError("walk failed")),
        )
        assert workflow_ui._scan_project_evidence(env)["count"] == 0

    assert workflow_ui._project_install_status(None) == ("Unknown", "environment not loaded", "incomplete")
    assert workflow_ui._run_history(None) == ("0", "environment not loaded", "incomplete")

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agilab.environment_health":
            raise RuntimeError("blocked")
        return original_import(name, globals, locals, fromlist, level)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", _blocked_import)
    assert workflow_ui._project_install_status(SimpleNamespace()) == (
        "Check",
        "install status unavailable",
        "incomplete",
    )
    assert workflow_ui._run_history(SimpleNamespace()) == (
        "0",
        "run log status unavailable",
        "incomplete",
    )

    fake_st = _FakeStreamlit()
    workflow_ui.render_project_evidence_drawer(
        fake_st,
        env=SimpleNamespace(app="missing", active_app=tmp_path / "missing"),
        key_prefix="missing",
    )
    assert (
        "caption",
        "No evidence files found yet. Run ORCHESTRATE -> EXECUTE first.",
    ) in fake_st.events
    assert workflow_ui._normalize_artifact({"description": "Description only"}) == {
        "label": "Artifact",
        "path": None,
        "kind": "artifact",
        "description": "Description only",
        "preview": True,
    }

    file_root = tmp_path / "standalone.csv"
    file_root.write_text("x\n1\n", encoding="utf-8")
    file_scan = workflow_ui._scan_project_evidence(SimpleNamespace(app_data_rel=file_root))
    assert file_scan["count"] == 1
    assert file_scan["examples"] == ["standalone.csv"]

    limited_root = tmp_path / "limited"
    limited_root.mkdir()
    for index in range(4):
        (limited_root / f"artifact_{index}.csv").write_text("x\n1\n", encoding="utf-8")
    monkeypatch.setattr(workflow_ui, "_COCKPIT_SCAN_LIMIT", 2)
    limited_scan = workflow_ui._scan_project_evidence(SimpleNamespace(app_data_rel=limited_root))
    assert limited_scan["truncated"] is True
    assert limited_scan["count"] == 2

    assert workflow_ui._project_next_action(
        SimpleNamespace(app="demo_project"),
        project_ready=True,
        install_value="Ready",
        run_value="3",
        artifact_count=0,
    )["label"] == "Create evidence"

    class _NoLinkButtonStreamlit(_FakeStreamlit):
        link_button = None

    fallback_st = _NoLinkButtonStreamlit()
    workflow_ui.render_next_action(
        fallback_st,
        env=SimpleNamespace(app="demo_project"),
        key_prefix="demo",
        action={
            "id": "analysis",
            "label": "Review evidence",
            "url": "/ANALYSIS",
            "type": "primary",
        },
    )
    assert ("markdown", "[Review evidence](/ANALYSIS)") in fallback_st.events


def test_artifact_drawer_covers_generic_preview_edges(monkeypatch, tmp_path) -> None:
    fake_st = _FakeStreamlit()
    folder = tmp_path / "folder"
    folder.mkdir()
    image = tmp_path / "plot.png"
    image.write_bytes(b"png")
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{bad", encoding="utf-8")
    binary = tmp_path / "model.bin"
    binary.write_bytes(b"1234")
    large_text = tmp_path / "large.txt"
    large_text.write_text("abcdef", encoding="utf-8")

    monkeypatch.setattr(workflow_ui, "MAX_INLINE_DOWNLOAD_BYTES", 2)
    monkeypatch.setattr(workflow_ui, "MAX_INLINE_PREVIEW_BYTES", 2)
    workflow_ui.render_artifact_drawer(
        fake_st,
        artifacts=[
            {"label": "Folder", "path": folder},
            {"label": "Missing", "path": tmp_path / "missing.csv"},
            {"label": "Description only", "description": "No file yet"},
            {"label": "Image", "path": image},
            {"label": "Bad JSON", "path": bad_json, "kind": "json"},
            {"label": "Binary", "path": binary},
            {"label": "Large text", "path": large_text, "kind": "txt"},
            {"label": "Skipped"},
            object(),
        ],
        key_prefix="edge",
    )

    assert ("caption", "Folder: Folder (folder)") in fake_st.events
    assert ("caption", "Missing: Missing (csv)") in fake_st.events
    assert ("caption", "Description only: No path (artifact)") in fake_st.events
    assert ("caption", "No file yet") in fake_st.events
    assert ("image", str(image)) in fake_st.events
    assert ("caption", "bad.json is too large for inline download.") in fake_st.events
    assert ("code", "json:{b") in fake_st.events
    assert not any("Binary" in value and event == "code" for event, value in fake_st.events)
    assert ("code", "text:ab") in fake_st.events
    assert workflow_ui._read_text_preview(large_text, max_bytes=2) == "large.txt is too large for inline preview."
    assert workflow_ui._artifact_mime(tmp_path / "data.csv") == "text/csv"
    assert workflow_ui._artifact_mime(tmp_path / "page.html") == "text/html"
    assert workflow_ui._artifact_mime(tmp_path / "photo.jpg") == "image/jpeg"
    assert workflow_ui._artifact_mime(tmp_path / "readme.md") == "text/plain"


def test_normalize_command_mapping_defaults_and_button_type_fallback() -> None:
    assert workflow_ui._normalize_command({"label": "Run", "type": "invalid"}) == {
        "id": "Run",
        "label": "Run",
        "enabled": True,
        "reason": "",
        "type": "secondary",
    }
    assert workflow_ui._normalize_command({"id": "", "label": "", "enabled": False}) is None
    assert workflow_ui._normalize_command(("Tuple", "tuple command", False, "needs data")) == {
        "id": "tuple_command",
        "label": "Tuple",
        "enabled": False,
        "reason": "needs data",
        "type": "secondary",
    }


def test_command_and_history_edge_cases() -> None:
    fake_st = _FakeStreamlit(buttons={"demo:command:tuple_id": True, "demo:command:plain": True})
    selected = workflow_ui.render_command_bar(
        fake_st,
        commands=[
            {"id": "", "label": ""},
            ("Tuple", "tuple id", True, "tuple help", "invalid"),
            "plain",
        ],
        key_prefix="demo",
        max_columns=10,
    )
    assert selected == "plain"
    assert ("button", "demo:command:tuple_id:False") in fake_st.events
    assert ("button", "demo:command:plain:False") in fake_st.events

    session_state = {workflow_ui.ACTION_HISTORY_KEY: "stale"}
    workflow_ui.record_action_history(
        session_state,
        page_label="WORKFLOW",
        title="First",
        status=False,
        limit=1,
    )
    workflow_ui.record_action_history(
        session_state,
        page_label="WORKFLOW",
        title="Second",
        status=True,
        limit=1,
    )
    history = session_state[workflow_ui.ACTION_HISTORY_KEY][workflow_ui.workflow_state_scope("WORKFLOW")]
    assert [item["title"] for item in history] == ["Second"]

    scope = workflow_ui.workflow_state_scope("WORKFLOW")
    render_state = {workflow_ui.ACTION_HISTORY_KEY: {scope: ["bad", {"title": "", "status": ""}]}}
    workflow_ui.render_action_history(fake_st, session_state=render_state, page_label="WORKFLOW")
    workflow_ui.render_action_history(fake_st, session_state={workflow_ui.ACTION_HISTORY_KEY: "bad"}, page_label="WORKFLOW")
    workflow_ui.render_action_history(fake_st, session_state={}, page_label="WORKFLOW")
    assert any("Action: Info" in value for event, value in fake_st.events if event == "caption")


def test_workflow_ui_direct_helper_error_edges(tmp_path) -> None:
    fake_st = _FakeStreamlit()

    class _NoTupleShape:
        empty = False
        shape = "bad"

    assert workflow_ui._dataframe_shape(_NoTupleShape()) is None

    class _StatErrorPath:
        name = "stat-error.csv"
        suffix = ".csv"

        def is_file(self):
            return True

        def is_dir(self):
            return False

        def stat(self):
            raise OSError("stat blocked")

        def __str__(self):
            return "stat-error.csv"

    class _ReadErrorPath(_StatErrorPath):
        name = "read-error.csv"

        def stat(self):
            return SimpleNamespace(st_size=1)

        def read_bytes(self):
            raise OSError("read blocked")

        def read_text(self, **_kwargs):
            raise OSError("read blocked")

        def __str__(self):
            return "read-error.csv"

    stat_error = _StatErrorPath()
    read_error = _ReadErrorPath()
    class _StatusErrorPath(_StatErrorPath):
        def is_file(self):
            raise OSError("status blocked")

    status_error = _StatusErrorPath()
    workflow_ui._render_output_download(fake_st, path=stat_error, key="stat")
    workflow_ui._render_output_download(fake_st, path=read_error, key="read")
    workflow_ui._render_artifact_download(fake_st, path=stat_error, key="artifact-stat")
    workflow_ui._render_artifact_download(fake_st, path=read_error, key="artifact-read")
    assert not [event for event in fake_st.events if event[0] == "download"]
    assert workflow_ui._artifact_status(status_error) == "Unavailable"
    assert workflow_ui._read_text_preview(stat_error) == ""
    assert workflow_ui._read_text_preview(read_error) == ""

    nameless = tmp_path / "artifact"
    nameless.write_text("payload", encoding="utf-8")
    normalized_path = workflow_ui._normalize_artifact(nameless)
    assert normalized_path is not None
    assert normalized_path["label"] == "artifact"
    assert normalized_path["kind"] == "file"

    assert workflow_ui._normalize_artifact({"path": "", "description": ""}) is None

    empty_json = tmp_path / "empty.json"
    empty_json.write_text("", encoding="utf-8")
    workflow_ui._render_artifact_preview(fake_st, path=empty_json, kind="json")

    json_without_container_view = tmp_path / "payload.json"
    json_without_container_view.write_text('{"ok": true}', encoding="utf-8")

    class _CodeOnly:
        def __init__(self):
            self.events: list[tuple[str, str]] = []

        def code(self, body, language=None):
            self.events.append(("code", f"{language}:{body}"))

    code_only = _CodeOnly()
    workflow_ui._render_artifact_preview(code_only, path=json_without_container_view, kind="json")
    assert any(event[0] == "code" and event[1].startswith("json:{") for event in code_only.events)

    state = {workflow_ui.ACTION_HISTORY_KEY: {workflow_ui.workflow_state_scope("WORKFLOW"): "stale"}}
    workflow_ui.record_action_history(state, page_label="WORKFLOW", title="Recovered")
    assert state[workflow_ui.ACTION_HISTORY_KEY][workflow_ui.workflow_state_scope("WORKFLOW")][0]["title"] == "Recovered"


def test_workflow_ui_remaining_render_branches(tmp_path) -> None:
    fake_st = _FakeStreamlit()
    workflow_ui._download_log_button(SimpleNamespace(), body="logs", key="missing", file_name="run.log")
    workflow_ui.render_action_readiness(
        fake_st,
        actions=[("Install", True, ""), ("Run", False, "blocked")],
    )
    workflow_ui.render_latest_outputs(fake_st, key_prefix="empty")
    workflow_ui.render_artifact_drawer(fake_st, artifacts=[], key_prefix="empty")

    missing = tmp_path / "missing.csv"
    workflow_ui._render_output_download(fake_st, path=missing, key="missing-output")
    assert workflow_ui._normalize_artifact({"path": object()}) is None

    image = tmp_path / "plot.png"
    image.write_bytes(b"png")
    workflow_ui._render_artifact_preview(fake_st, path=image, kind="png")
    assert ("image", str(image)) in fake_st.events

    empty_text = tmp_path / "empty.txt"
    empty_text.write_text("", encoding="utf-8")
    workflow_ui._render_artifact_preview(fake_st, path=empty_text, kind="txt")

    output = tmp_path / "output.txt"
    output.write_text("out", encoding="utf-8")
    log = tmp_path / "run.log"
    log.write_text("log", encoding="utf-8")
    workflow_ui.render_latest_run_card(
        fake_st,
        status="running",
        output_path=output,
        log_path=log,
        started_at="2026-05-17T10:00:00",
        duration="2s",
        key_prefix="latest",
    )
    assert ("caption", "Install: Ready") in fake_st.events
    assert ("caption", "Run: blocked") in fake_st.events
    assert ("caption", "Started: 2026-05-17T10:00:00") in fake_st.events
    assert ("caption", "Duration: 2s") in fake_st.events
    assert ("download", "latest:latest_output:False") in fake_st.events
    assert ("download", "latest:latest_log:False") in fake_st.events
