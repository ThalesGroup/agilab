from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "first_proof_cli.py"
sys.path.insert(0, str(ROOT / "src"))


def _load_module():
    sys.modules.pop("agilab.first_proof_cli", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    sys.modules["agilab"] = package
    spec = importlib.util.spec_from_file_location("agilab.first_proof_cli", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_proof_commands_use_packaged_python_runner() -> None:
    module = _load_module()
    active_app = module.default_active_app()

    commands = module.build_proof_commands(active_app, with_install=False)

    assert [command.label for command in commands] == [
        "package preinit smoke",
        "package ui smoke",
    ]
    assert commands[0].argv[:2] == (sys.executable, "-c")
    assert commands[1].argv[:2] == (sys.executable, "-c")
    assert "tools/newcomer_first_proof.py" not in " ".join(commands[0].argv + commands[1].argv)
    assert str(active_app) in commands[1].argv[-1]


def test_build_proof_commands_with_install_adds_seed_checks() -> None:
    module = _load_module()

    commands = module.build_proof_commands(module.default_active_app(), with_install=True)

    assert [command.label for command in commands] == [
        "package preinit smoke",
        "package ui smoke",
        "flight install smoke",
        "seeded script check",
    ]
    assert "apps/install.py" in commands[2].argv[1]
    assert "AGI_install_flight.py" in commands[3].argv[-1]


def test_main_print_only_json_emits_first_proof_contract(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--print-only", "--json", "--with-install"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["with_install"] is True
    assert payload["kpi_target_seconds"] == module.DEFAULT_MAX_SECONDS
    assert payload["run_manifest_filename"] == "run_manifest.json"
    assert payload["run_manifest_path"].endswith("/log/execute/flight/run_manifest.json")
    assert payload["commands"][0]["label"] == "package preinit smoke"
    assert payload["commands"][-1]["label"] == "seeded script check"


def test_run_proof_stops_on_first_failure() -> None:
    module = _load_module()
    commands = module.build_proof_commands(module.default_active_app(), with_install=True)
    returncodes = iter([0, 7, 0, 0])

    def fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, next(returncodes), stdout="demo", stderr="")

    results = module.run_proof(commands, runner=fake_runner)

    assert [result.label for result in results] == ["package preinit smoke", "package ui smoke"]
    assert results[-1].returncode == 7


def test_run_command_records_timeout() -> None:
    module = _load_module()
    command = module.ProofCommand(
        label="demo",
        description="demo",
        argv=(sys.executable, "-V"),
        timeout_seconds=1.0,
    )

    def fake_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1.0, output="partial")

    result = module.run_command(command, runner=fake_runner)

    assert result.returncode == 124
    assert "Timed out after 1s" in result.stdout


def test_build_run_manifest_records_cli_command(tmp_path: Path) -> None:
    module = _load_module()
    active_app = module.default_active_app()
    commands = module.build_proof_commands(active_app, with_install=False)
    results = [
        module.ProofStepResult(
            label=command.label,
            description=command.description,
            argv=list(command.argv),
            returncode=0,
            duration_seconds=1.0,
            stdout="ok",
            env=command.env,
        )
        for command in commands
    ]
    summary = module.summarize_kpi(command_count=2, results=results, max_seconds=600.0)

    manifest = module.build_run_manifest(
        active_app=active_app,
        with_install=False,
        commands=commands,
        results=results,
        summary=summary,
        max_seconds=600.0,
        manifest_path=tmp_path / "run_manifest.json",
    )
    encoded = manifest.as_dict()

    assert encoded["path_id"] == "source-checkout-first-proof"
    assert encoded["status"] == "pass"
    assert encoded["command"]["argv"][:3] == ["agilab", "first-proof", "--json"]
    assert encoded["command"]["label"] == "agilab first-proof"
    assert encoded["environment"]["app_name"] == "flight_project"
    assert {item["label"]: item["status"] for item in encoded["validations"]} == {
        "proof_steps": "pass",
        "target_seconds": "pass",
        "recommended_project": "pass",
    }


def test_resolve_active_app_rejects_missing_pyproject(tmp_path: Path) -> None:
    module = _load_module()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()

    with pytest.raises(FileNotFoundError, match="pyproject.toml"):
        module.resolve_active_app(str(active_app))


def test_package_data_includes_app_installer_for_with_install() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = pyproject["tool"]["setuptools"]["package-data"]["agilab"]

    assert "apps/install.py" in package_data
    assert "examples/*/AGI_*.py" in package_data


def test_package_discovery_includes_about_page_helpers() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_includes = set(pyproject["tool"]["setuptools"]["packages"]["find"]["include"])

    assert "agilab.about_page*" in package_includes
    for helper in ("bootstrap.py", "env_editor.py", "layout.py", "onboarding.py"):
        assert (ROOT / "src" / "agilab" / "about_page" / helper).is_file()
