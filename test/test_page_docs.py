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


def test_docs_menu_items_merge_about_content_and_page_help():
    menu_items = page_docs.docs_menu_items(
        html_file="execute-help.html",
        anchor="cluster",
        base_items={"About": "AGILAB"},
    )

    assert menu_items["About"] == "AGILAB"
    assert menu_items["Get help"] == "https://thalesgroup.github.io/agilab/execute-help.html#cluster"


def test_docs_candidates_and_open_remote_docs(monkeypatch):
    opened: list[str] = []

    def fake_open_new_tab(url):
        opened.append(url)
        return True

    monkeypatch.setattr(page_docs.webbrowser, "open_new_tab", fake_open_new_tab)

    assert page_docs._docs_candidates("execute-help.html") == ("execute-help.html", "execute_help.html")

    assert page_docs._open_remote_docs("execute-help.html", "#cluster") is True

    assert opened == ["https://thalesgroup.github.io/agilab/execute-help.html#cluster"]


def test_open_remote_docs_reports_unavailable_browser(monkeypatch):
    monkeypatch.setattr(page_docs.webbrowser, "open_new_tab", lambda _url: False)

    assert page_docs._open_remote_docs("execute-help.html", "#cluster") is False


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


def test_open_local_page_docs_falls_back_to_source_checkout_docs(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "docs" / "html"
    docs_root.mkdir(parents=True)
    local_doc = docs_root / "execute-help.html"
    local_doc.write_text("<html>ok</html>", encoding="utf-8")

    env = types.SimpleNamespace(agilab_pck=repo_root / "src" / "agilab")
    opened: list[str] = []

    monkeypatch.setattr(
        page_docs,
        "open_local_docs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    monkeypatch.setattr(page_docs, "open_docs_url", lambda url: opened.append(url))
    monkeypatch.setattr(page_docs, "__file__", str(repo_root / "src" / "agilab" / "page_docs.py"))

    resolved = page_docs._open_local_page_docs(env, "execute-help.html", "cluster")

    assert resolved == "execute-help.html"
    assert opened == [f"{local_doc.as_uri()}#cluster"]


def test_resolve_local_page_docs_path_returns_none_for_invalid_package_root():
    env = types.SimpleNamespace(agilab_pck=object())

    assert page_docs._resolve_local_page_docs_path(env, "execute-help.html") is None


def test_resolve_local_page_docs_path_skips_duplicate_roots_without_docs(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    package_root = repo_root / "src"
    module_file = package_root / "agilab" / "page_docs.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("pass\n", encoding="utf-8")

    env = types.SimpleNamespace(agilab_pck=package_root)
    monkeypatch.setattr(page_docs, "__file__", str(module_file))

    assert page_docs._resolve_local_page_docs_path(env, "execute-help.html") is None


def test_resolve_local_page_docs_path_supports_recursive_docs_matches(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    package_root = repo_root / "src"
    module_file = package_root / "agilab" / "page_docs.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("pass\n", encoding="utf-8")
    nested_doc = module_file.parent / "docs" / "nested" / "execute-help.html"
    nested_doc.parent.mkdir(parents=True)
    nested_doc.write_text("<html>ok</html>", encoding="utf-8")

    env = types.SimpleNamespace(agilab_pck=package_root)
    monkeypatch.setattr(page_docs, "__file__", str(module_file))

    assert page_docs._resolve_local_page_docs_path(env, "execute-help.html") == nested_doc


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
    def fake_open_remote_docs(html_file, anchor=""):
        events.append(("remote", f"{html_file}#{anchor}"))
        return True

    monkeypatch.setattr(page_docs, "_open_remote_docs", fake_open_remote_docs)
    monkeypatch.setattr(page_docs, "_open_local_page_docs", lambda *_args, **_kwargs: events.append(("local", "opened")))

    page_docs.render_page_docs_access(
        object(),
        html_file="agilab-help.html",
        anchor="intro",
        key_prefix="help",
        sidebar=False,
    )

    assert ("subheader", "Documentation") in events
    assert ("button", "Read Documentation:help_docs_read") in events
    assert ("remote", "agilab-help.html#intro") in events
    assert not any(kind == "local" for kind, _ in events)
    assert not any(kind == "caption" for kind, _ in events)
    assert not any(kind == "error" for kind, _ in events)


def test_render_page_docs_access_falls_back_to_local_docs_when_remote_unavailable(monkeypatch):
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

    fake_sidebar = FakeContainer()
    monkeypatch.setattr(page_docs, "st", types.SimpleNamespace(sidebar=fake_sidebar))
    monkeypatch.setattr(page_docs, "_open_remote_docs", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(page_docs, "_open_local_page_docs", lambda *_args, **_kwargs: "execute-help.html")

    page_docs.render_page_docs_access(
        object(),
        html_file="execute-help.html",
        anchor="cluster",
        key_prefix="execute",
        title="Execute docs",
    )

    assert ("button", "Read Documentation:execute_docs_read") in events
    assert not any(kind == "error" for kind, _ in events)


def test_render_page_docs_access_skips_divider_when_disabled(monkeypatch):
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
            return False

        def error(self, message):
            events.append(("error", message))

    fake_sidebar = FakeContainer()
    monkeypatch.setattr(page_docs, "st", types.SimpleNamespace(sidebar=fake_sidebar))

    page_docs.render_page_docs_access(
        object(),
        html_file="agilab-help.html",
        key_prefix="about",
        divider=False,
    )

    assert not any(kind == "subheader" for kind, _ in events)
    assert not any(kind == "divider" for kind, _ in events)


def test_render_page_docs_access_reports_docs_error_in_sidebar(monkeypatch):
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

    fake_sidebar = FakeContainer()
    monkeypatch.setattr(page_docs, "st", types.SimpleNamespace(sidebar=fake_sidebar))
    monkeypatch.setattr(
        page_docs,
        "_open_local_page_docs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    monkeypatch.setattr(page_docs, "_open_remote_docs", lambda *_args, **_kwargs: False)

    page_docs.render_page_docs_access(
        object(),
        html_file="execute-help.html",
        anchor="cluster",
        key_prefix="execute",
        title="Execute docs",
        caption="Local help is optional.",
    )

    assert ("caption", "Local help is optional.") in events
    assert ("button", "Read Documentation:execute_docs_read") in events
    assert ("error", "Documentation not found online or locally. Regenerate via docs/gen-docs.sh.") in events
