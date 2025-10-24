from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from tools import apps_pages_launcher as launcher


def test_run_streamlit_builds_expected_command(monkeypatch, tmp_path: Path):
    page_script = tmp_path / "page.py"
    page_script.touch()
    active_app = tmp_path / "flight_project"
    active_app.mkdir()

    captured: List[List[str]] = []

    def fake_call(cmd, env=None):
        captured.append(cmd)
        assert env["PYTHONUNBUFFERED"] == "1"
        return 0

    monkeypatch.setattr(launcher.subprocess, "call", fake_call)

    rc = launcher.run_streamlit("view_maps", page_script, active_app, port=8501)

    assert rc == 0
    assert captured == [
        [
            "uv",
            "run",
            "streamlit",
            "run",
            str(page_script),
            "--server.port",
            "8501",
            "--",
            "--active-app",
            str(active_app),
        ]
    ]


def test_pick_from_menu_reading_choice(monkeypatch, tmp_path: Path):
    fake_page = tmp_path / "fake_page.py"
    fake_page.touch()

    monkeypatch.setattr(launcher, "PAGES", {"first": str(fake_page)})

    called = {}

    def fake_run_streamlit(page, script, active_app, *, port=None):
        called["page"] = page
        called["script"] = script
        called["active_app"] = active_app
        return 0

    monkeypatch.setattr(launcher, "run_streamlit", fake_run_streamlit)
    monkeypatch.setattr(launcher.sys, "stdin", io.StringIO("1\n"))

    rc = launcher.pick_from_menu(tmp_path)

    assert rc == 0
    assert called["page"] == "first"
    assert called["script"] == Path(fake_page)
    assert called["active_app"] == tmp_path


def test_pick_from_menu_invalid_selection(monkeypatch):
    monkeypatch.setattr(launcher, "PAGES", {"first": "missing"})
    monkeypatch.setattr(launcher.sys, "stdin", io.StringIO("99\n"))

    rc = launcher.pick_from_menu(Path("."))

    assert rc == 0
