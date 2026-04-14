from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env.ui_docs_support import (
    detect_dev_version_suffix,
    detect_installed_version,
    focus_existing_docs_tab,
    read_version_from_pyproject,
    resolve_docs_path,
    read_theme_css,
)


def test_ui_docs_support_focus_existing_docs_tab_handles_platform_and_success():
    assert focus_existing_docs_tab("http://example/docs", platform="linux") is False

    calls: list[tuple[list[str], dict[str, object]]] = []

    def _run_cmd(*args, **kwargs):
        calls.append((args[0], dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout="true\n")

    assert focus_existing_docs_tab("http://example/docs", platform="darwin", run_cmd=_run_cmd) is True
    assert calls and calls[0][0] == ["osascript", "-"]
    assert "chrome_activate" in calls[0][1]["input"]


def test_ui_docs_support_focus_returns_false_when_runner_fails():
    assert focus_existing_docs_tab(
        "http://example/docs",
        platform="darwin",
        run_cmd=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    ) is False


def test_ui_docs_support_resolve_docs_path_falls_back_to_recursive_search(tmp_path):
    pkg_root = tmp_path / "pkg"
    nested = pkg_root.parent / "docs" / "nested"
    nested.mkdir(parents=True)
    target = nested / "guide.html"
    target.write_text("guide", encoding="utf-8")

    assert resolve_docs_path(pkg_root, "guide.html") == target


def test_ui_docs_support_resolve_docs_path_returns_none_when_missing(tmp_path):
    pkg_root = tmp_path / "pkg"
    pkg_root.mkdir()
    assert resolve_docs_path(pkg_root, "missing.html") is None


def test_ui_docs_support_resolve_docs_path_returns_none_for_empty_docs_root(tmp_path):
    pkg_root = tmp_path / "pkg"
    (pkg_root.parent / "docs").mkdir()

    assert resolve_docs_path(pkg_root, "missing.html") is None


def test_ui_docs_support_read_theme_css_uses_module_file_and_fallback(tmp_path):
    pkg_root = tmp_path / "pkg"
    resources = pkg_root / "resources"
    resources.mkdir(parents=True)
    theme_file = resources / "theme.css"
    theme_file.write_text("body { color: red; }", encoding="utf-8")

    assert read_theme_css(None, module_file=str(pkg_root / "nested" / "module.py")) == "body { color: red; }"

    theme_file.write_bytes(b"body {\xff color: blue; }")
    assert "body {" in read_theme_css(None, module_file=str(pkg_root / "nested" / "module.py"))
    assert "color: blue" in read_theme_css(None, module_file=str(pkg_root / "nested" / "module.py"))


def test_ui_docs_support_read_theme_css_uses_explicit_base_path(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    theme_file = resources / "theme.css"
    theme_file.write_text("body { color: purple; }", encoding="utf-8")

    assert read_theme_css(resources, module_file=str(tmp_path / "nested" / "module.py")) == "body { color: purple; }"


def test_ui_docs_support_read_theme_css_returns_none_when_missing(tmp_path):
    pkg_root = tmp_path / "pkg"

    assert read_theme_css(None, module_file=str(pkg_root / "nested" / "module.py")) is None


def test_ui_docs_support_read_theme_css_returns_none_when_binary_fallback_fails(tmp_path):
    class BrokenThemePath:
        def __init__(self, raw):
            self.raw = raw

        def __truediv__(self, _other):
            return self

        def exists(self):
            return True

        def read_text(self, encoding="utf-8"):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "boom")

        def open(self, *_args, **_kwargs):
            raise OSError("boom")

    assert read_theme_css(tmp_path / "resources", module_file=str(tmp_path / "nested" / "module.py"), path_cls=BrokenThemePath) is None


def test_ui_docs_support_reads_version_and_installed_fallback(tmp_path, monkeypatch):
    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    (foreign_root / "pyproject.toml").write_text(
        "[project]\nname='other-project'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    repo_root = tmp_path / "repo"
    nested = repo_root / "src" / "pkg"
    nested.mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname='agilab'\nversion='2026.4.11'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(nested)

    assert read_version_from_pyproject(SimpleNamespace(agilab_pck=foreign_root)) == "2026.4.11"

    metadata_module = importlib.import_module("importlib.metadata")
    assert detect_installed_version(SimpleNamespace(version=lambda _name: "9.9.9", PackageNotFoundError=metadata_module.PackageNotFoundError)) == "9.9.9"


def test_ui_docs_support_read_version_from_pyproject_returns_none_without_agilab_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    assert read_version_from_pyproject(SimpleNamespace(agilab_pck=empty_root)) is None


def test_ui_docs_support_read_version_from_pyproject_returns_none_without_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert read_version_from_pyproject(None) is None


def test_ui_docs_support_read_version_from_pyproject_stops_at_repo_root(tmp_path):
    class RootOnlyPath:
        def __init__(self, _value):
            pass

        @classmethod
        def cwd(cls):
            return cls("/")

        def resolve(self):
            return self

        def __truediv__(self, _other):
            return self

        def exists(self):
            return False

        @property
        def parent(self):
            return self

    assert read_version_from_pyproject(None, path_cls=RootOnlyPath) is None


def test_ui_docs_support_read_version_from_pyproject_handles_cwd_errors():
    class BrokenCwdPath:
        @classmethod
        def cwd(cls):
            raise OSError("boom")

    assert read_version_from_pyproject(None, path_cls=BrokenCwdPath) is None


def test_ui_docs_support_read_version_from_pyproject_ignores_empty_version(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='agilab'\nversion=''\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert read_version_from_pyproject(SimpleNamespace(agilab_pck=root)) is None


def test_ui_docs_support_read_version_from_pyproject_ignores_invalid_toml(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("not = [valid\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert read_version_from_pyproject(SimpleNamespace(agilab_pck=root)) is None


def test_ui_docs_support_detect_installed_version_handles_missing_metadata():
    assert detect_installed_version(None) == ""

    class _PackageMissing:
        PackageNotFoundError = RuntimeError

        def version(self, _name):
            raise RuntimeError("missing")

    assert detect_installed_version(_PackageMissing()) == ""


def test_ui_docs_support_detects_dev_suffix_and_falls_back():
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        if "rev-parse" in cmd:
            return SimpleNamespace(stdout="abc123\n")
        return SimpleNamespace(stdout="dirty\n")

    assert detect_dev_version_suffix(Path("/tmp/repo"), run_cmd=_run) == "+dev.abc123*"
    assert calls
    assert detect_dev_version_suffix(
        Path("/tmp/repo"),
        run_cmd=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("git boom")),
    ) == "+dev"
