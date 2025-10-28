from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env import pagelib


def test_diagnose_data_directory_reports_missing_mount(tmp_path, monkeypatch):
    missing_mount = tmp_path / "missing_share"
    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (missing_mount,))
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {})

    message = pagelib.diagnose_data_directory(missing_mount / "payload")

    assert "not mounted" in message


def test_diagnose_data_directory_reports_empty_share(tmp_path, monkeypatch):
    mount_dir = tmp_path / "data_share"
    mount_dir.mkdir()
    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (mount_dir,))
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {mount_dir: "nfs"})

    message = pagelib.diagnose_data_directory(mount_dir / "payload")

    assert "appears empty" in message


def test_diagnose_data_directory_ok(tmp_path, monkeypatch):
    mount_dir = tmp_path / "ready_share"
    payload_dir = mount_dir / "payload"
    payload_dir.mkdir(parents=True)
    (payload_dir / "marker.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(pagelib, "_fstab_mount_points", lambda: (mount_dir,))
    monkeypatch.setattr(pagelib, "_current_mount_points", lambda: {mount_dir: "nfs"})

    message = pagelib.diagnose_data_directory(payload_dir)

    assert message is None


def test_run_success(monkeypatch):
    recorded = {}

    def fake_run(command, shell, check, cwd, stdout, stderr):
        recorded["command"] = command
        recorded["cwd"] = cwd

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)

    pagelib.run("echo 'ok'", cwd="/tmp")

    assert recorded == {"command": "echo 'ok'", "cwd": "/tmp"}


def test_run_failure_exits(monkeypatch):
    logs: list[str] = []

    def fake_log(message):
        logs.append(message)

    def fake_run(*_, **__):
        raise subprocess.CalledProcessError(
            2,
            "bad",
            output=b"stdout",
            stderr=b"stderr",
        )

    def fake_exit(code):
        raise RuntimeError(f"exit:{code}")

    monkeypatch.setattr(pagelib.subprocess, "run", fake_run)
    monkeypatch.setattr(pagelib, "log", fake_log)
    monkeypatch.setattr(pagelib.sys, "exit", fake_exit)

    with pytest.raises(RuntimeError, match="exit:2"):
        pagelib.run("bad")

    assert "Error executing command" in logs[0]


def test_with_anchor_appends_hash():
    assert pagelib._with_anchor("http://example", "section") == "http://example#section"
    assert pagelib._with_anchor("http://example", "#section") == "http://example#section"
    assert pagelib._with_anchor("http://example", "") == "http://example"


def test_open_docs_url_reuses_existing_tab(monkeypatch):
    opened = []

    def open_new_tab(url):
        opened.append(url)

    pagelib._DOCS_ALREADY_OPENED = False
    pagelib._LAST_DOCS_URL = None
    monkeypatch.setattr(pagelib.webbrowser, "open_new_tab", open_new_tab)
    monkeypatch.setattr(pagelib, "_focus_existing_docs_tab", lambda _: True)

    pagelib._open_docs_url("http://example/docs")
    pagelib._open_docs_url("http://example/docs")

    assert opened == ["http://example/docs"]


def test_resolve_docs_path_prefers_build(tmp_path):
    pkg_root = tmp_path / "pkg"
    docs_build = pkg_root / "docs" / "build"
    docs_build.mkdir(parents=True)
    target = docs_build / "index.html"
    target.write_text("hello", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    resolved = pagelib._resolve_docs_path(env, "index.html")

    assert resolved == target


def test_open_docs_falls_back_to_online(monkeypatch):
    captured = {}

    def fake_open(url):
        captured["url"] = url

    monkeypatch.setattr(pagelib, "_open_docs_url", fake_open)
    env = SimpleNamespace(agilab_pck=Path("/does/not/exist"))

    pagelib.open_docs(env, html_file="missing.html", anchor="anchor")

    assert captured["url"] == "https://thalesgroup.github.io/agilab/index.html#anchor"


def test_open_local_docs_requires_existing_file(tmp_path, monkeypatch):
    pkg_root = tmp_path / "pkg"
    docs_build = pkg_root / "docs" / "build"
    docs_build.mkdir(parents=True)
    html_path = docs_build / "page.html"
    html_path.write_text("doc", encoding="utf-8")
    env = SimpleNamespace(agilab_pck=pkg_root)

    opened = {}
    monkeypatch.setattr(pagelib, "_open_docs_url", lambda url: opened.setdefault("url", url))

    pagelib.open_local_docs(env, html_file="page.html", anchor="a")

    assert opened["url"].startswith(html_path.as_uri())

    with pytest.raises(FileNotFoundError):
        pagelib.open_local_docs(env, html_file="missing.html")
