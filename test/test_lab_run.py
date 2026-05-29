from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
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


def test_lab_run_uses_shared_import_guard_for_local_helpers():
    source = LAB_RUN_PATH.read_text(encoding="utf-8")

    assert "spec_from_file_location" not in source
    assert "import_agilab_module(" in source


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
    for env_key in [
        "STREAMLIT_CONFIG_FILE",
        "STREAMLIT_THEME_BASE",
        "STREAMLIT_THEME_PRIMARY_COLOR",
        "STREAMLIT_THEME_BACKGROUND_COLOR",
        "STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR",
        "STREAMLIT_THEME_TEXT_COLOR",
    ]:
        monkeypatch.delenv(env_key, raising=False)

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
    assert lab_run.os.environ["STREAMLIT_CONFIG_FILE"] == str(
        Path(lab_run.__file__).resolve().parent / "resources" / "config.toml"
    )
    assert lab_run.os.environ["STREAMLIT_THEME_BASE"] == "dark"
    assert lab_run.os.environ["STREAMLIT_THEME_PRIMARY_COLOR"] == "#4A90E2"
    assert lab_run.os.environ["STREAMLIT_THEME_BACKGROUND_COLOR"] == "#08111F"
    assert lab_run.os.environ["STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR"] == "#102334"
    assert lab_run.os.environ["STREAMLIT_THEME_TEXT_COLOR"] == "#F7F2E8"


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


def test_main_dispatches_app_management_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_app(argv: list[str]) -> int:
        captured.append(argv)
        return 43

    monkeypatch.setattr(lab_run, "_run_app", fake_app)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["app", "list", "--json"])

    assert rc == 43
    assert captured == [["list", "--json"]]


def test_main_dispatches_kubernetes_job_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_kubernetes_job(argv: list[str]) -> int:
        captured.append(argv)
        return 47

    monkeypatch.setattr(lab_run, "_run_kubernetes_job", fake_kubernetes_job)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["k8s-job", "--app", "demo_project", "--image", "agilab:local"])

    assert rc == 47
    assert captured == [["--app", "demo_project", "--image", "agilab:local"]]


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


def test_main_dispatches_adoption_report_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_adoption_report(argv: list[str]) -> int:
        captured.append(argv)
        return 39

    monkeypatch.setattr(lab_run, "_run_adoption_report", fake_adoption_report)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["adoption-report", "--json", "--strict"])

    assert rc == 39
    assert captured == [["--json", "--strict"]]


def test_public_headless_cli_imports_and_help_do_not_require_streamlit() -> None:
    script = """
        import builtins
        import contextlib
        import importlib
        import io

        real_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "streamlit" or name.startswith("streamlit."):
                raise ModuleNotFoundError("blocked streamlit", name="streamlit")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import

        for module_name in (
            "agilab",
            "agilab.lab_run",
            "agilab.first_proof_cli",
            "agilab.adoption_report",
            "agilab.bridge_cli",
            "agilab_mcp.server",
        ):
            importlib.import_module(module_name)

        from agilab import lab_run

        lab_run._guard_against_uvx_in_source_tree = lambda: None

        for argv in (
            ["--help"],
            ["first-proof", "--help"],
            ["adoption-report", "--help"],
        ):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                try:
                    code = lab_run.main(list(argv))
                except SystemExit as exc:
                    code = exc.code
            if code not in (0, None):
                raise SystemExit(f"help path failed for {argv}: {code}")
    """
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else os.pathsep.join([src_path, env["PYTHONPATH"]])
    )

    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_main_dispatches_evidence_contract_commands_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_evidence_contract(argv: list[str]) -> int:
        captured.append(argv)
        return 45

    monkeypatch.setattr(lab_run, "_run_evidence_contract", fake_evidence_contract)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["export_lineage", "run_manifest.json", "--format", "openlineage"])

    assert rc == 45
    assert captured == [["export-lineage", "run_manifest.json", "--format", "openlineage"]]

    rc = lab_run.main(["export_traces", "run_manifest.json", "--output", "otel.json"])

    assert rc == 45
    assert captured[-1] == ["export-traces", "run_manifest.json", "--output", "otel.json"]

    rc = lab_run.main(["sign", "proof.agipack", "--key", "signer.pem"])

    assert rc == 45
    assert captured[-1] == ["sign", "proof.agipack", "--key", "signer.pem"]


def test_main_dispatches_env_footprint_without_launching_streamlit(monkeypatch):
    monkeypatch.setattr(lab_run, "_guard_against_uvx_in_source_tree", lambda: None)
    captured: list[list[str]] = []

    def fake_env(argv: list[str]) -> int:
        captured.append(argv)
        return 43

    monkeypatch.setattr(lab_run, "_run_env", fake_env)
    monkeypatch.setattr(
        lab_run,
        "_load_streamlit_cli",
        lambda: (_ for _ in ()).throw(AssertionError("streamlit should not be launched")),
    )

    rc = lab_run.main(["env", "footprint", "--json"])

    assert rc == 43
    assert captured == [["footprint", "--json"]]


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
