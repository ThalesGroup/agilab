from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_pages import runtime


def test_agi_pages_runtime_resolves_active_app_and_reports_missing(tmp_path: Path) -> None:
    app = tmp_path / "demo_project"
    app.mkdir()

    assert runtime.resolve_active_app_path(["--active-app", str(app)]) == app.resolve()

    errors: list[str] = []
    stops = 0

    def stop() -> None:
        nonlocal stops
        stops += 1

    with pytest.raises(FileNotFoundError, match="Provided --active-app path not found"):
        runtime.resolve_active_app_path(
            ["--active-app", str(tmp_path / "missing")],
            error_fn=errors.append,
            stop_fn=stop,
        )

    assert stops == 1
    assert errors and "Provided --active-app path not found" in errors[0]

    with pytest.raises(FileNotFoundError, match="Provided --active-app path not found"):
        runtime.resolve_active_app_path(["--active-app", str(tmp_path / "missing_without_callbacks")])


def test_agi_pages_runtime_file_helpers_are_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    (root / "b").mkdir(parents=True)
    (root / "a").mkdir()
    b_file = root / "b" / "metrics.json"
    a_file = root / "a" / "metrics.json"
    b_file.write_text('{"run": "b"}', encoding="utf-8")
    a_file.write_text('{"run": "a"}', encoding="utf-8")
    list_file = root / "list.json"
    malformed_file = root / "malformed.json"
    list_file.write_text("[1, 2]", encoding="utf-8")
    malformed_file.write_text("{", encoding="utf-8")

    class BrokenBase:
        def glob(self, _pattern: str):
            raise OSError("glob unavailable")

    assert runtime.artifact_root(
        SimpleNamespace(AGILAB_EXPORT_ABS=tmp_path / "export", target="demo"),
        "forecast",
    ) == tmp_path / "export" / "demo" / "forecast"
    assert runtime.discover_files(root, "**/metrics.json") == [a_file, b_file]
    assert runtime.discover_files(root / "missing", "[") == []
    assert runtime.discover_files(BrokenBase(), "*.json") == []
    assert runtime.load_json_object(a_file) == {"run": "a"}
    assert runtime.load_json_object(None) == {}
    assert runtime.load_json_object(tmp_path / "missing.json") == {}
    assert runtime.load_json_object(list_file) == {}
    assert runtime.load_json_object(malformed_file) == {}
    assert runtime.relative_label(a_file, root) == "a/metrics.json"
    assert runtime.relative_label(tmp_path / "outside.json", root) == "outside.json"
    assert runtime.safe_float("1.25") == 1.25
    assert runtime.safe_float(float("nan")) is None
    assert runtime.safe_float(float("inf")) is None
    assert runtime.safe_float(object()) is None
    assert runtime.safe_metric("bad") == "n/a"
    assert runtime.safe_metric(1.23456, digits=2) == "1.23"


def test_agi_pages_runtime_ensure_repo_on_path(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    page_file = src_root / "agilab" / "apps-pages" / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_file.parent.mkdir(parents=True)
    page_file.write_text("# page\n", encoding="utf-8")

    monkeypatch.setattr(sys, "path", [])
    runtime.ensure_repo_on_path(page_file)

    assert str(src_root) in sys.path
    assert str(repo_root) in sys.path
    first_path = list(sys.path)

    runtime.ensure_repo_on_path(page_file)

    assert sys.path == first_path


def test_agi_pages_runtime_ensure_repo_on_path_ignores_unmatched_anchor(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "path", [])

    runtime.ensure_repo_on_path(tmp_path / "outside.py")

    assert sys.path == []
