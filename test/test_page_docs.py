from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PAGE_DOCS_PATH = Path(__file__).resolve().parents[1] / "src/agilab/page_docs.py"
_PAGE_DOCS_SPEC = importlib.util.spec_from_file_location("test_page_docs_module", _PAGE_DOCS_PATH)
assert _PAGE_DOCS_SPEC is not None and _PAGE_DOCS_SPEC.loader is not None
page_docs = importlib.util.module_from_spec(_PAGE_DOCS_SPEC)
_PAGE_DOCS_SPEC.loader.exec_module(page_docs)


def test_remote_docs_url_supports_anchors():
    assert (
        page_docs._remote_docs_url("execute-help.html", "sidebar")
        == "https://thalesgroup.github.io/agilab/execute-help.html#sidebar"
    )
    assert (
        page_docs._remote_docs_url("execute-help.html", "#sidebar")
        == "https://thalesgroup.github.io/agilab/execute-help.html#sidebar"
    )


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
