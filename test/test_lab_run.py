from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB_RUN_PATH = ROOT / "src" / "agilab" / "lab_run.py"
SPEC = importlib.util.spec_from_file_location("agilab.lab_run", LAB_RUN_PATH)
assert SPEC and SPEC.loader
lab_run = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("agilab.lab_run", lab_run)
SPEC.loader.exec_module(lab_run)


def test_main_prints_version_without_launching_streamlit(monkeypatch, capsys):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    monkeypatch.setattr(lab_run, "_detect_cli_version", lambda: "2026.4.9")
    monkeypatch.setattr(
        lab_run.stcli,
        "main",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["--version"])

    assert rc == 0
    assert capsys.readouterr().out.strip() == "agilab 2026.4.9"


def test_main_keeps_streamlit_launch_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    monkeypatch.setattr(lab_run, "_resolve_apps_path", lambda _value: str(tmp_path / "apps"))

    captured: list[list[str]] = []

    def fake_main():
        captured.append(list(lab_run.sys.argv))
        return 17

    monkeypatch.setattr(lab_run.stcli, "main", fake_main)

    rc = lab_run.main(["--server.headless", "true"])

    assert rc == 17
    assert captured == [[
        "streamlit",
        "run",
        str(Path(lab_run.__file__).resolve().parent / "About_agilab.py"),
        "--",
        "--apps-path",
        str(tmp_path / "apps"),
        "--server.headless",
        "true",
    ]]


def test_main_dispatches_doctor_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_doctor(argv: list[str]) -> int:
        captured.append(argv)
        return 23

    monkeypatch.setattr(lab_run, "_run_doctor", fake_doctor)
    monkeypatch.setattr(
        lab_run.stcli,
        "main",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["doctor", "--cluster", "--scheduler", "127.0.0.1"])

    assert rc == 23
    assert captured == [["--cluster", "--scheduler", "127.0.0.1"]]
