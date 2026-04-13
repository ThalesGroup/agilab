from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

import pytest


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


page_docs = _import_agilab_module("agilab.page_docs")


def test_remote_docs_url_supports_anchors():
    assert (
        page_docs._remote_docs_url("execute-help.html")
        == "https://thalesgroup.github.io/agilab/execute-help.html"
    )
    assert (
        page_docs._remote_docs_url("execute-help.html", "sidebar")
        == "https://thalesgroup.github.io/agilab/execute-help.html#sidebar"
    )
    assert (
        page_docs._remote_docs_url("execute-help.html", "#sidebar")
        == "https://thalesgroup.github.io/agilab/execute-help.html#sidebar"
    )


def test_docs_candidates_and_open_remote_docs(monkeypatch):
    opened: list[str] = []

    monkeypatch.setattr(page_docs.webbrowser, "open_new_tab", lambda url: opened.append(url))

    assert page_docs._docs_candidates("execute-help.html") == ("execute-help.html", "execute_help.html")

    page_docs._open_remote_docs("execute-help.html", "#cluster")

    assert opened == ["https://thalesgroup.github.io/agilab/execute-help.html#cluster"]


def test_open_local_page_docs_tries_legacy_aliases(monkeypatch):
    opened: list[str] = []

    def fake_open_local_docs(_env, html_file="index.html", anchor=""):
        opened.append(html_file)
        if html_file != "views_help.html":
            raise FileNotFoundError(html_file)

    monkeypatch.setattr(page_docs, "open_local_docs", fake_open_local_docs)

    resolved = page_docs._open_local_page_docs(object(), "explore-help.html")

    assert resolved == "views_help.html"
    assert opened == ["explore-help.html", "views_help.html"]


def test_open_local_page_docs_raises_when_no_candidate_exists(monkeypatch):
    monkeypatch.setattr(
        page_docs,
        "open_local_docs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    with pytest.raises(FileNotFoundError):
        page_docs._open_local_page_docs(object(), "edit-help.html")


def test_open_local_page_docs_raises_explicit_missing_when_no_candidates(monkeypatch):
    monkeypatch.setattr(page_docs, "_docs_candidates", lambda _html_file: ())

    with pytest.raises(FileNotFoundError, match="Local documentation file 'edit-help.html' was not found."):
        page_docs._open_local_page_docs(object(), "edit-help.html")


def test_render_page_docs_access_uses_main_container_and_remote_button(monkeypatch):
    events: list[tuple[str, str]] = []

    class FakeContainer:
        def divider(self):
            events.append(("divider", ""))

        def subheader(self, title):
            events.append(("subheader", title))

        def caption(self, text):
            events.append(("caption", text))

        def button(self, label, **kwargs):
            events.append(("button", f"{label}:{kwargs['key']}"))
            return label == "Read Documentation"

        def error(self, message):
            events.append(("error", message))

    fake_container = FakeContainer()
    fake_st = types.SimpleNamespace(
        sidebar=types.SimpleNamespace(),
        divider=fake_container.divider,
        subheader=fake_container.subheader,
        caption=fake_container.caption,
        button=fake_container.button,
        error=fake_container.error,
    )
    monkeypatch.setattr(page_docs, "st", fake_st)
    monkeypatch.setattr(page_docs, "_open_remote_docs", lambda html_file, anchor="": events.append(("remote", f"{html_file}#{anchor}")))
    monkeypatch.setattr(page_docs, "_open_local_page_docs", lambda *_args, **_kwargs: events.append(("local", "opened")))

    page_docs.render_page_docs_access(
        object(),
        html_file="agilab-help.html",
        anchor="intro",
        key_prefix="help",
        sidebar=False,
    )

    assert ("subheader", "Documentation") in events
    assert ("remote", "agilab-help.html#intro") in events
    assert not any(kind == "caption" for kind, _ in events)
    assert not any(kind == "error" for kind, _ in events)


def test_render_page_docs_access_reports_local_docs_error_in_sidebar(monkeypatch):
    events: list[tuple[str, str]] = []

    class FakeContainer:
        def divider(self):
            events.append(("divider", ""))

        def subheader(self, title):
            events.append(("subheader", title))

        def caption(self, text):
            events.append(("caption", text))

        def button(self, label, **kwargs):
            events.append(("button", f"{label}:{kwargs['key']}"))
            return label == "Open Local Documentation"

        def error(self, message):
            events.append(("error", message))

    fake_sidebar = FakeContainer()
    monkeypatch.setattr(page_docs, "st", types.SimpleNamespace(sidebar=fake_sidebar))
    monkeypatch.setattr(
        page_docs,
        "_open_local_page_docs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    monkeypatch.setattr(page_docs, "_open_remote_docs", lambda *_args, **_kwargs: events.append(("remote", "opened")))

    page_docs.render_page_docs_access(
        object(),
        html_file="execute-help.html",
        anchor="cluster",
        key_prefix="execute",
        title="Execute docs",
        caption="Local help is optional.",
    )

    assert ("subheader", "Execute docs") in events
    assert ("caption", "Local help is optional.") in events
    assert ("error", "Local documentation not found. Regenerate via docs/gen-docs.sh.") in events
    assert not any(kind == "remote" for kind, _ in events)
