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

    assert module.parse_patterns(" **/*.json ; **/*.json\n*.log ,, ") == ("**/*.json", "*.log")
    assert module.parse_patterns(("", " ", "a", "a", "b")) == ("a", "b")
    assert module.parse_patterns("") == module.DEFAULT_PATTERNS
    assert module.format_patterns(["a", "a", " b "]) == "a, b"
    assert module.format_bytes(None) == "0 B"
    assert module.format_bytes(1024) == "1.0 KB"
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
    text_preview = module.read_artifact_preview(text_path, max_bytes=4)
    assert text_preview.kind == "text"
    assert text_preview.value == "... 6789"
    assert text_preview.truncated is True
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
