from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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
        lab_run,
        "_load_streamlit_cli",
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

    monkeypatch.setattr(lab_run, "_load_streamlit_cli", lambda: SimpleNamespace(main=fake_main))

    rc = lab_run.main(["--server.headless", "true"])

    assert rc == 17
    assert captured == [[
        "streamlit",
        "run",
        "--server.address",
        "127.0.0.1",
        str(Path(lab_run.__file__).resolve().parent / "main_page.py"),
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
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["doctor", "--cluster", "--scheduler", "127.0.0.1"])

    assert rc == 23
    assert captured == [["--cluster", "--scheduler", "127.0.0.1"]]


def test_main_dispatches_first_proof_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_first_proof(argv: list[str]) -> int:
        captured.append(argv)
        return 33

    monkeypatch.setattr(lab_run, "_run_first_proof", fake_first_proof)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["first-proof", "--json", "--with-ui"])

    assert rc == 33
    assert captured == [["--json", "--with-ui"]]


def test_main_dispatches_agent_run_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_agent_run(argv: list[str]) -> int:
        captured.append(argv)
        return 35

    monkeypatch.setattr(lab_run, "_run_agent_run", fake_agent_run)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["agent-run", "--agent", "codex", "--", "codex", "review"])

    assert rc == 35
    assert captured == [["--agent", "codex", "--", "codex", "review"]]


def test_main_dispatches_dry_run_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_first_proof(argv: list[str]) -> int:
        captured.append(argv)
        return 31

    monkeypatch.setattr(lab_run, "_run_first_proof", fake_first_proof)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["dry-run", "--json"])

    assert rc == 31
    assert captured == [["--dry-run", "--json"]]


def test_main_dispatches_dry_run_alias_as_first_proof(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_first_proof(argv: list[str]) -> int:
        captured.append(argv)
        return 41

    monkeypatch.setattr(lab_run, "_run_first_proof", fake_first_proof)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["dry-run", "--max-seconds", "45"])

    assert rc == 41
    assert captured == [["--dry-run", "--max-seconds", "45"]]


def test_main_dispatches_security_check_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_security_check(argv: list[str]) -> int:
        captured.append(argv)
        return 37

    monkeypatch.setattr(lab_run, "_run_security_check", fake_security_check)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["security-check", "--json", "--strict"])

    assert rc == 37
    assert captured == [["--json", "--strict"]]


def test_main_reports_missing_ui_dependencies(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    monkeypatch.setattr(lab_run, "_resolve_apps_path", lambda _value: None)
    monkeypatch.setattr(lab_run, "_missing_ui_dependencies", lambda: ["streamlit", "agi-gui"])

    with pytest.raises(SystemExit, match=r"streamlit, agi-gui.*agilab\[ui\]"):
        lab_run.main([])


def test_main_refuses_public_bind_without_auth_or_tls(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    monkeypatch.delenv("AGILAB_PUBLIC_BIND_OK", raising=False)
    monkeypatch.delenv("AGILAB_TLS_TERMINATED", raising=False)

    with pytest.raises(SystemExit, match="refuses to bind"):
        lab_run.main([])


def test_main_allows_explicit_public_bind_with_tls_indicator(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    monkeypatch.setattr(lab_run, "_resolve_apps_path", lambda _value: str(tmp_path / "apps"))
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    monkeypatch.setenv("AGILAB_PUBLIC_BIND_OK", "1")
    monkeypatch.setenv("AGILAB_TLS_TERMINATED", "1")
    captured: list[list[str]] = []

    def fake_main():
        captured.append(list(lab_run.sys.argv))
        return 0

    monkeypatch.setattr(lab_run, "_load_streamlit_cli", lambda: SimpleNamespace(main=fake_main))

    assert lab_run.main([]) == 0
    assert captured[0][2:4] == ["--server.address", "0.0.0.0"]
