from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "headless_cli_smoke.py"
SPEC = importlib.util.spec_from_file_location("headless_cli_smoke_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
headless_cli_smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = headless_cli_smoke
SPEC.loader.exec_module(headless_cli_smoke)


def test_streamlit_blocked_probe_covers_public_headless_modules() -> None:
    script = headless_cli_smoke.streamlit_blocked_probe_script()

    for module_name in (
        "agilab.lab_run",
        "agilab.first_proof_cli",
        "agilab.adoption_report",
        "agilab.bridge_cli",
        "agilab_mcp.server",
    ):
        assert module_name in script
    assert 'name == "streamlit" or name.startswith("streamlit.")' in script
    assert '["first-proof", "--help"]' in script
    assert '["adoption-report", "--help"]' in script


def test_package_import_probe_requires_minimal_no_streamlit_environment() -> None:
    script = headless_cli_smoke.package_import_probe_script()

    assert 'find_spec("streamlit") is not None' in script
    assert "streamlit should not be installed" in script
    assert "agilab_mcp.server" in script


def test_source_smoke_runs_blocked_streamlit_probe(monkeypatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run(command, *, label, timeout, env=None):
        calls.append((list(command), label))
        return headless_cli_smoke.SmokeResult(
            label=label,
            command=list(command),
            returncode=0,
            stdout_tail="ok",
            stderr_tail="",
        )

    monkeypatch.setattr(headless_cli_smoke, "_run", fake_run)

    results = headless_cli_smoke.run_source_smoke(python="/tmp/python", timeout=12.0)

    assert [result.label for result in results] == ["source blocked-streamlit import/help"]
    assert calls[0][0][0:2] == ["/tmp/python", "-c"]
    assert "blocked streamlit" in calls[0][0][2]


def test_package_smoke_prefers_uv_venv_and_uv_pip(monkeypatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run(command, *, label, timeout, env=None):
        calls.append((list(command), label))
        return headless_cli_smoke.SmokeResult(
            label=label,
            command=list(command),
            returncode=0,
            stdout_tail="ok",
            stderr_tail="",
        )

    monkeypatch.setattr(
        headless_cli_smoke.shutil,
        "which",
        lambda name: "/usr/bin/uv" if name == "uv" else None,
    )
    monkeypatch.setattr(headless_cli_smoke, "_run", fake_run)

    results = headless_cli_smoke.run_package_smoke(package_spec=".", timeout=12.0)

    labels = [result.label for result in results]
    assert labels[:3] == ["create uv venv", "install .", "package no-streamlit import"]
    assert calls[0][0][:3] == ["/usr/bin/uv", "venv", "--python"]
    expected_python, _ = headless_cli_smoke._venv_paths(Path(calls[0][0][-1]))
    assert calls[1][0][:5] == [
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        str(expected_python),
    ]


def test_emit_results_returns_failing_status(capsys) -> None:
    result = headless_cli_smoke.SmokeResult(
        label="bad",
        command=["agilab", "--help"],
        returncode=1,
        stdout_tail="out",
        stderr_tail="err",
    )

    headless_cli_smoke._emit_results([result], json_output=False)

    captured = capsys.readouterr()
    assert "FAIL bad" in captured.out
    assert "out" in captured.out
    assert "err" in captured.err
