from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/newcomer_first_proof.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("newcomer_first_proof_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_proof_commands_defaults_to_preinit_and_ui_smoke() -> None:
    module = _load_module()

    commands = module.build_proof_commands(module.DEFAULT_ACTIVE_APP, with_install=False)

    assert [command.label for command in commands] == [
        "preinit smoke",
        "source ui smoke",
    ]
    assert "tools/smoke_preinit.py" in " ".join(commands[0].argv)
    assert "AppTest.from_file" in commands[1].argv[-1]
    assert str(module.DEFAULT_ACTIVE_APP) in commands[1].argv[-1]


def test_build_proof_commands_with_install_adds_install_and_seed_checks() -> None:
    module = _load_module()

    commands = module.build_proof_commands(module.DEFAULT_ACTIVE_APP, with_install=True)

    assert [command.label for command in commands] == [
        "preinit smoke",
        "source ui smoke",
        "flight install smoke",
        "seeded script check",
    ]
    assert "src/agilab/apps/install.py" in " ".join(commands[2].argv)
    assert "AGI_install_flight.py" in commands[3].argv[-1]


def test_resolve_active_app_rejects_missing_pyproject(tmp_path: Path) -> None:
    module = _load_module()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()

    with pytest.raises(FileNotFoundError, match="pyproject.toml"):
        module.resolve_active_app(str(active_app))


def test_render_human_print_only_lists_commands() -> None:
    module = _load_module()
    commands = module.build_proof_commands(module.DEFAULT_ACTIVE_APP, with_install=False)

    rendered = module.render_human(
        active_app=module.DEFAULT_ACTIVE_APP,
        with_install=False,
        commands=commands,
        print_only=True,
    )

    assert "mode: print-only" in rendered
    assert "kpi target: <=" in rendered
    assert "preinit smoke" in rendered
    assert "source ui smoke" in rendered


def test_main_print_only_json_emits_selected_commands(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--print-only", "--json", "--with-install"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["with_install"] is True
    assert payload["kpi_target_seconds"] == module.DEFAULT_MAX_SECONDS
    assert payload["commands"][0]["label"] == "preinit smoke"
    assert payload["commands"][-1]["label"] == "seeded script check"


def test_summarize_kpi_tracks_duration_target_and_failed_step() -> None:
    module = _load_module()

    passing = [
        module.ProofStepResult(
            label="preinit smoke",
            description="demo",
            argv=["python", "-V"],
            returncode=0,
            duration_seconds=2.5,
            stdout="",
            env={},
        ),
        module.ProofStepResult(
            label="source ui smoke",
            description="demo",
            argv=["python", "-V"],
            returncode=0,
            duration_seconds=3.0,
            stdout="",
            env={},
        ),
    ]

    summary = module.summarize_kpi(command_count=2, results=passing, max_seconds=10.0)

    assert summary["success"] is True
    assert summary["passed_steps"] == 2
    assert summary["expected_steps"] == 2
    assert summary["failed_step"] is None
    assert summary["total_duration_seconds"] == 5.5
    assert summary["target_seconds"] == 10.0
    assert summary["within_target"] is True

    failing = [passing[0], passing[1].__class__(**{**passing[1].__dict__, "returncode": 7})]

    failed_summary = module.summarize_kpi(command_count=2, results=failing, max_seconds=10.0)

    assert failed_summary["success"] is False
    assert failed_summary["failed_step"] == "source ui smoke"
    assert failed_summary["within_target"] is False


def test_run_proof_stops_on_first_failure() -> None:
    module = _load_module()
    commands = module.build_proof_commands(module.DEFAULT_ACTIVE_APP, with_install=True)
    returncodes = iter([0, 7, 0, 0])

    def _fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, next(returncodes), stdout="demo", stderr="")

    results = module.run_proof(commands, runner=_fake_runner)

    assert [result.label for result in results] == ["preinit smoke", "source ui smoke"]
    assert results[-1].returncode == 7


def test_run_command_filters_known_bare_mode_streamlit_noise() -> None:
    module = _load_module()
    command = module.ProofCommand(
        label="demo",
        description="demo",
        argv=("python", "-V"),
    )

    def _fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "ok line\n"
                "Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.\n"
                "second line\n"
            ),
            stderr="",
        )

    result = module.run_command(command, runner=_fake_runner)

    assert result.stdout == "ok line\nsecond line"
