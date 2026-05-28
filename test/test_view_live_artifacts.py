from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_live_artifacts/src/view_live_artifacts/view_live_artifacts.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("view_live_artifacts_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _set_mtime(path: Path, value: int) -> None:
    os.utime(path, ns=(value, value))


def test_live_artifacts_parse_patterns_and_format_helpers() -> None:
    module = _load_module()

    assert module.parse_patterns(None) == module.DEFAULT_PATTERNS
    assert module.parse_patterns(" **/*.json ; **/*.json\n*.log ,, ") == ("**/*.json", "*.log")
    assert module.parse_patterns(("", " ", "a", "a", "b")) == ("a", "b")
    assert module.parse_patterns("") == module.DEFAULT_PATTERNS
    assert module.format_patterns(["a", "a", " b "]) == "a, b"
    assert module.format_bytes(None) == "0 B"
    assert module.format_bytes("not-a-size") == "0 B"
    assert module.format_bytes(1024) == "1.0 KB"
    assert module.format_bytes(1024**4) == "1.0 TB"
    assert module.refresh_run_every(False, 1) is None
    assert module.refresh_run_every(True, "bad") == "5s"
    assert module.refresh_run_every(True, 0) == "1s"


def test_live_artifacts_discovery_deduplicates_sorts_and_summarizes(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "artifacts"
    nested = root / "nested"
    nested.mkdir(parents=True)
    manifest = root / "run_manifest.json"
    manifest.write_text('{"run": 1}', encoding="utf-8")
    metrics = nested / "metrics.json"
    metrics.write_text('{"accuracy": 0.9}', encoding="utf-8")
    log = nested / "worker.log"
    log.write_text("started\n", encoding="utf-8")
    ignored = root / "data.bin"
    ignored.write_bytes(b"\x00\x01")
    _set_mtime(manifest, 1_000_000_000)
    _set_mtime(metrics, 3_000_000_000)
    _set_mtime(log, 2_000_000_000)
    _set_mtime(ignored, 500_000_000)

    records = module.discover_artifacts(
        root,
        ("**/*.json", "**/*.json", "**/*.log", "[invalid"),
        limit=10,
    )

    assert [record.relative_path for record in records] == [
        "nested/metrics.json",
        "nested/worker.log",
        "run_manifest.json",
    ]
    assert [record.kind for record in records] == ["json", "text", "manifest"]
    limited_records = module.discover_artifacts(root, ("**/*",), limit=1)
    assert [record.relative_path for record in limited_records] == ["nested/metrics.json"]
    assert module.discover_artifacts(root / "missing", ("**/*",)) == ()
    assert module.discover_artifacts(root, ("**/*",), limit=0) == ()

    summary = module.summarize_artifacts(records)
    first_signature = summary["signature"]
    assert summary["count"] == 3
    assert summary["manifest_count"] == 1
    assert summary["latest_path"] == "nested/metrics.json"
    assert summary["total_size"] == sum(record.size for record in records)

    metrics.write_text('{"accuracy": 0.95}', encoding="utf-8")
    updated_records = module.discover_artifacts(root, ("**/*.json", "**/*.log"), limit=10)
    assert module.summarize_artifacts(updated_records)["signature"] != first_signature


def test_live_artifacts_preview_handles_json_text_images_metadata_and_errors(tmp_path: Path) -> None:
    module = _load_module()
    json_path = tmp_path / "state.json"
    json_path.write_text('{"status": "ok"}', encoding="utf-8")
    text_path = tmp_path / "worker.log"
    text_path.write_text("0123456789", encoding="utf-8")
    image_path = tmp_path / "plot.png"
    image_path.write_bytes(b"not a real image but path-based preview")
    binary_path = tmp_path / "payload.bin"
    binary_path.write_bytes(b"\x00\x01\x02")
    invalid_json = tmp_path / "broken.json"
    invalid_json.write_text("{", encoding="utf-8")

    assert module.read_artifact_preview(json_path).value == {"status": "ok"}
    module.MAX_JSON_PREVIEW_BYTES = 1
    large_json_preview = module.read_artifact_preview(json_path)
    assert large_json_preview.kind == "text"
    assert large_json_preview.value == '{"status": "ok"}'
    text_preview = module.read_artifact_preview(text_path, max_bytes=4)
    assert text_preview.kind == "text"
    assert text_preview.value == "... 6789"
    assert text_preview.truncated is True
    assert module._read_tail_text(text_path, max_bytes=20) == "0123456789"
    assert module.read_artifact_preview(image_path).kind == "image"
    metadata = module.read_artifact_preview(binary_path)
    assert metadata.kind == "metadata"
    assert metadata.value["size"] == "3 B"
    assert module.read_artifact_preview(invalid_json).kind == "error"
    assert module.read_artifact_preview(tmp_path / "missing.json").kind == "error"


def test_live_artifacts_root_candidates_use_export_target_and_runenv(tmp_path: Path) -> None:
    module = _load_module()
    env = SimpleNamespace(
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="target_name",
        app="app_name",
        runenv=tmp_path / "runenv",
    )
    app_path = tmp_path / "apps" / "demo_project"

    candidates = module.root_candidates(env, app_path)

    assert candidates == {
        "Export artifacts": tmp_path / "export" / "target_name",
        "Run environment": tmp_path / "runenv",
        "App project": app_path,
    }


def test_live_artifacts_root_candidates_fall_back_to_app_and_project_venv(tmp_path: Path) -> None:
    module = _load_module()
    env = SimpleNamespace(
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="",
        app="demo_project",
        runenv="",
    )
    app_path = tmp_path / "apps" / "demo_project"

    candidates = module.root_candidates(env, app_path)

    assert candidates["Export artifacts"] == tmp_path / "export" / "demo_project"
    assert candidates["Run environment"] == app_path / ".venv"
    assert candidates["App project"] == app_path


def test_live_artifacts_active_env_reuses_matching_session_env(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    active_app = tmp_path / "apps" / "demo_project"
    active_app.mkdir(parents=True)
    current_env = SimpleNamespace(app="demo_project", apps_path=active_app.parent)
    fake_streamlit = SimpleNamespace(session_state={"env": current_env})
    monkeypatch.setattr(module, "st", fake_streamlit)

    env = module._active_env(active_app)

    assert env is current_env


def test_live_artifacts_resolve_active_app_delegates_to_runtime(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    fake_streamlit = SimpleNamespace(error=object(), stop=object())
    monkeypatch.setattr(module, "st", fake_streamlit)

    def fake_resolve_active_app_path(*, error_fn, stop_fn):
        assert error_fn is fake_streamlit.error
        assert stop_fn is fake_streamlit.stop
        return tmp_path / "apps" / "demo_project"

    monkeypatch.setattr(module, "resolve_active_app_path", fake_resolve_active_app_path)

    assert module._resolve_active_app() == tmp_path / "apps" / "demo_project"


def test_live_artifacts_resets_path_scoped_state_on_active_app_change(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    first_app = tmp_path / "apps_a" / "demo_project"
    second_app = tmp_path / "apps_b" / "demo_project"
    first_app.mkdir(parents=True)
    second_app.mkdir(parents=True)
    state = {
        module.APP_SCOPE_KEY: str(first_app.resolve()),
        "env": object(),
        module._state_key("demo_project", "root_choice"): "Custom path",
        module._state_key("demo_project", "patterns"): "*.json",
        f"{module.PAGE_KEY}_preview_artifact": "old.json",
        "unrelated": "keep",
    }
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))

    assert module._reset_app_scoped_session_state(first_app) is False
    assert module._state_key("demo_project", "root_choice") in state

    assert module._reset_app_scoped_session_state(second_app) is True
    assert state[module.APP_SCOPE_KEY] == str(second_app.resolve())
    assert state["unrelated"] == "keep"
    for key in (
        "env",
        module._state_key("demo_project", "root_choice"),
        module._state_key("demo_project", "patterns"),
        f"{module.PAGE_KEY}_preview_artifact",
    ):
        assert key not in state


def test_live_artifacts_rebuilds_env_when_session_env_points_to_another_apps_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    active_app = tmp_path / "apps" / "demo_project"
    active_app.mkdir(parents=True)
    stale_env = SimpleNamespace(app="demo_project", apps_path=tmp_path / "other_apps")
    created: list[tuple[Path, str, int]] = []

    class FakeAgiEnv(SimpleNamespace):
        def __init__(self, *, apps_path: Path, app: str, verbose: int) -> None:
            created.append((apps_path, app, verbose))
            super().__init__(apps_path=apps_path, app=app, verbose=verbose)

    fake_streamlit = SimpleNamespace(session_state={"env": stale_env})
    monkeypatch.setattr(module, "st", fake_streamlit)
    monkeypatch.setattr(module, "AgiEnv", FakeAgiEnv)

    env = module._active_env(active_app)

    assert env is fake_streamlit.session_state["env"]
    assert created == [(active_app.parent, "demo_project", 0)]
    assert getattr(env, "init_done") is True


def test_live_artifacts_render_controls_initializes_state_and_refreshes(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    app_path = tmp_path / "apps" / "demo_project"
    app_path.mkdir(parents=True)
    env = SimpleNamespace(
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="",
        app="demo_project",
        runenv="",
    )
    app_name = app_path.name
    state = {
        module._state_key(app_name, "root_choice"): "Custom path",
        module._state_key(app_name, "custom_root"): str(tmp_path / "custom"),
        module._state_key(app_name, "patterns"): " **/*.json ; *.log ; **/*.json ",
        module._state_key(app_name, "limit"): 12,
        module._state_key(app_name, "live_refresh"): False,
        module._state_key(app_name, "interval"): "not-valid",
    }

    class FakeSidebar:
        def __init__(self, session_state: dict[str, object]) -> None:
            self.session_state = session_state

        def selectbox(self, _label: str, _options, *, key: str):
            return self.session_state[key]

        def text_input(self, _label: str, *, key: str):
            return self.session_state[key]

        def text_area(self, _label: str, *, key: str, height: int):
            assert height == 92
            return self.session_state[key]

        def number_input(self, _label: str, *, min_value: int, max_value: int, step: int, key: str):
            assert (min_value, max_value, step) == (1, module.MAX_DISCOVERED_FILES, 10)
            return self.session_state[key]

        def toggle(self, _label: str, *, key: str):
            return self.session_state[key]

        def button(self, _label: str, *, type: str, width: str) -> bool:
            assert (type, width) == ("secondary", "stretch")
            return True

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = state
            self.sidebar = FakeSidebar(self.session_state)
            self.rerun_called = False

        def rerun(self) -> None:
            self.rerun_called = True

    fake_streamlit = FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_streamlit)

    selected_root, patterns, max_files, live_refresh, interval_seconds = module._render_controls(env, app_path)

    assert selected_root == tmp_path / "custom"
    assert patterns == ("**/*.json", "*.log")
    assert max_files == 12
    assert live_refresh is False
    assert interval_seconds == 5
    assert fake_streamlit.rerun_called is True


def test_live_artifacts_render_preview_handles_all_preview_kinds(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    json_path = tmp_path / "state.json"
    json_path.write_text('{"status": "ok"}', encoding="utf-8")
    text_path = tmp_path / "worker.log"
    text_path.write_text("x" * (module.PREVIEW_BYTES + 1), encoding="utf-8")
    image_path = tmp_path / "plot.png"
    image_path.write_bytes(b"png")
    binary_path = tmp_path / "payload.bin"
    binary_path.write_bytes(b"\x00\x01")
    missing_path = tmp_path / "missing.json"

    class FakeStreamlit:
        def __init__(self) -> None:
            self.captions: list[str] = []
            self.errors: list[str] = []
            self.codes: list[str] = []
            self.json_values: list[object] = []
            self.images: list[tuple[str, str]] = []

        def selectbox(self, _label: str, *, options, key: str):
            assert key == f"{module.PAGE_KEY}_preview_artifact"
            return options[0]

        def caption(self, value: str) -> None:
            self.captions.append(value)

        def error(self, value: str) -> None:
            self.errors.append(value)

        def code(self, value: str, *, language: str) -> None:
            assert language == "text"
            self.codes.append(value)

        def json(self, value: object, *, expanded: bool) -> None:
            assert expanded is False
            self.json_values.append(value)

        def image(self, value: str, *, caption: str) -> None:
            self.images.append((value, caption))

    def record(path: Path, kind: str) -> object:
        size = path.stat().st_size if path.exists() else 0
        return module.ArtifactRecord(
            path=path,
            relative_path=path.name,
            size=size,
            mtime_ns=1,
            mtime_iso="1970-01-01T00:00:00+00:00",
            kind=kind,
        )

    fake_streamlit = FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_streamlit)

    module._render_preview(())
    module._render_preview((record(json_path, "json"),))
    module._render_preview((record(text_path, "text"),))
    module._render_preview((record(image_path, "image"),))
    module._render_preview((record(binary_path, "binary"),))
    module._render_preview((record(missing_path, "json"),))

    assert fake_streamlit.json_values[0] == {"status": "ok"}
    assert any("Showing the latest portion" in value for value in fake_streamlit.captions)
    assert fake_streamlit.images == [(str(image_path), "plot.png")]
    assert fake_streamlit.json_values[1]["size"] == "2 B"
    assert fake_streamlit.errors == ["Preview unavailable."]
    assert fake_streamlit.codes[-1]


def test_live_artifacts_render_artifacts_panel_handles_empty_missing_and_populated_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()

    class FakeColumn:
        def __init__(self, sink: list[tuple[str, str]]) -> None:
            self.sink = sink

        def metric(self, label: str, value: str) -> None:
            self.sink.append((label, value))

    class FakeStreamlit:
        def __init__(self) -> None:
            self.metrics: list[tuple[str, str]] = []
            self.warnings: list[str] = []
            self.infos: list[str] = []
            self.captions: list[str] = []
            self.subheaders: list[str] = []
            self.dataframes: list[list[dict[str, object]]] = []

        def columns(self, count: int):
            assert count == 4
            return [FakeColumn(self.metrics) for _ in range(count)]

        def warning(self, value: str) -> None:
            self.warnings.append(value)

        def info(self, value: str) -> None:
            self.infos.append(value)

        def caption(self, value: str) -> None:
            self.captions.append(value)

        def subheader(self, value: str) -> None:
            self.subheaders.append(value)

        def dataframe(self, rows, *, width: str, hide_index: bool) -> None:
            assert (width, hide_index) == ("stretch", True)
            self.dataframes.append(list(rows))

    fake_streamlit = FakeStreamlit()
    previewed: list[tuple[object, ...]] = []
    monkeypatch.setattr(module, "st", fake_streamlit)
    monkeypatch.setattr(module, "_render_preview", lambda records: previewed.append(tuple(records)))

    module._render_artifacts_panel(tmp_path / "missing", ("**/*.json",), 10)

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    module._render_artifacts_panel(empty_root, ("**/*.json",), 10)

    root = tmp_path / "artifacts"
    root.mkdir()
    manifest = root / "analysis_manifest.json"
    manifest.write_text('{"ok": true}', encoding="utf-8")
    log = root / "worker.log"
    log.write_text("started\n", encoding="utf-8")
    _set_mtime(manifest, 2_000_000_000)
    _set_mtime(log, 1_000_000_000)
    module._render_artifacts_panel(root, ("**/*.json", "**/*.log"), 10)

    assert fake_streamlit.warnings == [f"Artifact root does not exist yet: {tmp_path / 'missing'}"]
    assert fake_streamlit.infos == ["No matching artifacts found."]
    assert "Manifest candidates" in fake_streamlit.subheaders
    assert "Artifacts" in fake_streamlit.subheaders
    assert any(value.startswith("Latest update: analysis_manifest.json") for value in fake_streamlit.captions)
    assert any(value.startswith("Signature: ") for value in fake_streamlit.captions)
    assert len(fake_streamlit.dataframes) == 2
    assert [record.relative_path for record in previewed[0]] == ["analysis_manifest.json", "worker.log"]


def test_live_artifacts_main_wires_page_controls_and_panel(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    app_path = tmp_path / "apps" / "demo_project"
    env = SimpleNamespace()
    calls: list[tuple[str, object]] = []

    class FakeStreamlit:
        def set_page_config(self, *, layout: str) -> None:
            calls.append(("set_page_config", layout))

        def title(self, value: str) -> None:
            calls.append(("title", value))

        def caption(self, value: str) -> None:
            calls.append(("caption", value))

    monkeypatch.setattr(module, "st", FakeStreamlit())
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app_path)
    monkeypatch.setattr(module, "_active_env", lambda active_app_path: env)
    monkeypatch.setattr(module, "render_logo", lambda title: calls.append(("logo", title)))
    monkeypatch.setattr(
        module,
        "_render_controls",
        lambda control_env, active_app_path: (tmp_path / "artifacts", ("**/*.json",), 5, False, 10),
    )
    monkeypatch.setattr(
        module,
        "_render_live_or_static_panel",
        lambda root, patterns, max_files, live_refresh, interval_seconds: calls.append(
            ("panel", (root, patterns, max_files, live_refresh, interval_seconds))
        ),
    )

    module.main()

    assert calls == [
        ("set_page_config", "wide"),
        ("logo", "Live Artifacts"),
        ("title", "Live artifacts"),
        ("caption", "Monitor exported evidence, manifests, logs, and lightweight artifacts for the active app."),
        ("caption", f"Root: {tmp_path / 'artifacts'}"),
        ("panel", (tmp_path / "artifacts", ("**/*.json",), 5, False, 10)),
    ]


def test_live_artifacts_live_fragment_uses_streamlit_run_every(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    rendered: list[tuple[Path, tuple[str, ...], int]] = []

    class FakeStreamlit:
        def __init__(self) -> None:
            self.fragment_intervals: list[str] = []

        def fragment(self, *, run_every: str):
            self.fragment_intervals.append(run_every)

            def _decorator(func):
                def _wrapper():
                    return func()

                return _wrapper

            return _decorator

    fake_streamlit = FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_streamlit)
    monkeypatch.setattr(
        module,
        "_render_artifacts_panel",
        lambda root, patterns, max_files: rendered.append((root, patterns, max_files)),
    )

    module._render_live_or_static_panel(tmp_path, ("**/*.json",), 7, True, 2)
    module._render_live_or_static_panel(tmp_path, ("**/*.log",), 3, False, 2)

    assert fake_streamlit.fragment_intervals == ["2s"]
    assert rendered == [(tmp_path, ("**/*.json",), 7), (tmp_path, ("**/*.log",), 3)]
