from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "first_proof_cli.py"
AGI_APPS_PYPROJECT = ROOT / "src/agilab/lib/agi-apps/pyproject.toml"
sys.path.insert(0, str(ROOT / "src"))


def _project_dependency_pin(project_name: str) -> str:
    pyproject = ROOT / f"src/agilab/lib/{project_name}/pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    return f"{metadata['name']}=={metadata['version']}"


def _load_module():
    previous_package = sys.modules.get("agilab")
    sys.modules.pop("agilab.first_proof_cli", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    package.__spec__ = importlib.util.spec_from_file_location(
        "agilab",
        ROOT / "src" / "agilab" / "__init__.py",
        submodule_search_locations=[str(ROOT / "src" / "agilab")],
    )
    sys.modules["agilab"] = package
    spec = importlib.util.spec_from_file_location("agilab.first_proof_cli", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_package is None:
            sys.modules.pop("agilab", None)
        else:
            sys.modules["agilab"] = previous_package
    return module


def test_build_proof_commands_default_to_core_smoke() -> None:
    module = _load_module()
    active_app = module.default_active_app()

    commands = module.build_proof_commands(active_app, with_install=False)

    assert [command.label for command in commands] == ["package preinit smoke"]
    assert commands[0].argv[:2] == (sys.executable, "-c")
    assert "tools/newcomer_first_proof.py" not in " ".join(commands[0].argv)
    assert "RunRequest" in commands[0].argv[-1]
    assert "StageRequest" in commands[0].argv[-1]
    assert str(active_app) in commands[0].argv[-1]


def test_build_proof_commands_with_ui_adds_packaged_page_smoke() -> None:
    module = _load_module()
    active_app = module.default_active_app()

    commands = module.build_proof_commands(active_app, with_install=False, with_ui=True)

    assert [command.label for command in commands] == [
        "package preinit smoke",
        "package ui smoke",
    ]
    assert commands[1].argv[:2] == (sys.executable, "-c")
    assert str(active_app) in commands[1].argv[-1]


def test_build_proof_commands_with_install_adds_seed_checks() -> None:
    module = _load_module()

    commands = module.build_proof_commands(module.default_active_app(), with_install=True)

    assert [command.label for command in commands] == [
        "package preinit smoke",
        "flight install smoke",
        "seeded script check",
    ]
    assert "apps/install.py" in commands[1].argv[1]
    assert "AGI_install_flight_telemetry.py" in commands[2].argv[-1]


def test_main_print_only_json_emits_first_proof_contract(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--print-only", "--json", "--with-install", "--with-ui"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["with_install"] is True
    assert payload["with_ui"] is True
    assert payload["kpi_target_seconds"] == module.DEFAULT_MAX_SECONDS
    assert "agilab_version" in payload
    assert payload["runtime_identity"]["python_executable"] == sys.executable
    assert "agilab" in payload["runtime_identity"]["distributions"]
    assert payload["run_manifest_filename"] == "run_manifest.json"
    assert payload["run_manifest_path"].endswith("/log/execute/flight_telemetry/run_manifest.json")
    assert payload["commands"][0]["label"] == "package preinit smoke"
    assert payload["commands"][-1]["label"] == "seeded script check"
    serialized = json.dumps(payload)
    assert "argv" not in serialized
    assert '"env":' not in serialized
    assert "sk-test-first-proof" not in serialized
    assert "orchestrate_errors" not in serialized


def test_main_print_only_human_emits_commands(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--print-only", "--max-seconds", "42"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "AGILAB first proof" in output
    assert "agilab version:" in output
    assert f"python: {sys.executable}" in output
    assert "mode: print-only" in output
    assert "kpi target: <= 42.00s" in output
    assert "$" in output


def test_runtime_identity_records_launcher_and_distribution_versions(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/tmp/bin/agilab" if name == "agilab" else None)
    monkeypatch.setattr(
        module.importlib_metadata,
        "version",
        lambda name: {"agilab": "2026.5.8", "agi-node": "2026.5.8"}.get(name, "missing"),
    )

    identity = module.runtime_identity()

    assert identity["python_executable"] == sys.executable
    assert identity["launcher_path"] == "/tmp/bin/agilab"
    assert identity["distributions"]["agilab"] == "2026.5.8"
    assert identity["distributions"]["agi-node"] == "2026.5.8"


def test_runtime_identity_handles_missing_launcher_and_distributions(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    def missing_version(name):
        raise module.importlib_metadata.PackageNotFoundError(name)

    monkeypatch.setattr(module.importlib_metadata, "version", missing_version)

    identity = module.runtime_identity()

    assert identity["launcher_path"] is None
    assert set(identity["distributions"]) == set(module.RUNTIME_DISTRIBUTIONS)
    assert all(version is None for version in identity["distributions"].values())


def test_runtime_identity_tracks_public_app_payload_distribution() -> None:
    module = _load_module()

    assert "agi-apps" in module.RUNTIME_DISTRIBUTIONS
    assert "agi-pages" in module.RUNTIME_DISTRIBUTIONS


def test_repo_root_and_marker_root_fall_back_outside_source_checkout(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    assert module._detect_repo_root(tmp_path) is None

    monkeypatch.setattr(module, "_detect_repo_root", lambda start=module.PACKAGE_ROOT: None)

    assert module._agilab_package_marker_root() == module.PACKAGE_ROOT.resolve()


def test_default_active_app_falls_back_to_packaged_path(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    package_root = tmp_path / "package" / "agilab"
    monkeypatch.setattr(module, "PACKAGE_ROOT", package_root)
    monkeypatch.setattr(module, "_detect_repo_root", lambda start=package_root: None)

    active_app = module.default_active_app()

    assert active_app == (package_root / "apps" / "builtin" / module.FIRST_PROOF_PROJECT).resolve()


def test_main_rejects_non_positive_kpi_target() -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.main(["--max-seconds", "0"])


def test_main_rejects_dry_run_with_extended_profiles() -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.main(["--dry-run", "--with-ui"])


def test_main_json_no_manifest_reports_success(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    active_app = tmp_path / "custom_project"
    active_app.mkdir()
    (active_app / "pyproject.toml").write_text("[project]\nname = 'custom'\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def fake_run_proof(commands):
        return [
            module.ProofStepResult(
                label=command.label,
                description=command.description,
                argv=list(command.argv),
                returncode=0,
                duration_seconds=0.5,
                stdout="\x1b[32mok\x1b[0m",
                env=command.env,
            )
            for command in commands
        ]

    monkeypatch.setattr(module, "run_proof", fake_run_proof)

    exit_code = module.main(
        ["--active-app", str(active_app), "--json", "--no-manifest", "--with-ui", "--max-seconds", "5"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["within_target"] is True
    assert "runtime_identity" in payload
    assert "agilab_version" in payload
    assert "run_manifest" not in payload
    assert payload["steps"][0]["status"] == "pass"
    assert "stdout" not in payload["steps"][0]
    assert "diagnostic_tail" not in payload["steps"][0]
    assert payload["steps"][1]["command"][-1] == "<inline first-proof smoke>"
    serialized = json.dumps(payload)
    assert "results" not in payload
    assert "argv" not in serialized
    assert '"env":' not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "sk-test-first-proof" not in serialized
    assert "orchestrate_errors" not in serialized
    marker = tmp_path / "home" / ".local" / "share" / "agilab" / ".agilab-path"
    assert payload["agilab_path_marker"] == str(marker)
    assert marker.read_text(encoding="utf-8").strip() == str(ROOT / "src" / "agilab")


def test_main_json_reports_failure_diagnostic_tail_without_full_stdout(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    active_app = tmp_path / "custom_project"
    active_app.mkdir()
    (active_app / "pyproject.toml").write_text("[project]\nname = 'custom'\n", encoding="utf-8")

    def fake_run_proof(commands):
        command = commands[0]
        return [
            module.ProofStepResult(
                label=command.label,
                description=command.description,
                argv=list(command.argv),
                returncode=7,
                duration_seconds=0.5,
                stdout="\x1b[31mfirst line\x1b[0m\nboom",
                env=command.env,
            )
        ]

    monkeypatch.setattr(module, "run_proof", fake_run_proof)

    exit_code = module.main(["--active-app", str(active_app), "--json", "--no-manifest"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"][0]["status"] == "fail"
    assert payload["steps"][0]["diagnostic_tail"] == ["first line", "boom"]
    assert "stdout" not in payload["steps"][0]


def test_main_json_with_manifest_embeds_only_manifest_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    active_app = tmp_path / "custom_project"
    active_app.mkdir()
    (active_app / "pyproject.toml").write_text("[project]\nname = 'custom'\n", encoding="utf-8")
    manifest_path = tmp_path / "run_manifest.json"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def fake_run_proof(commands):
        return [
            module.ProofStepResult(
                label=command.label,
                description=command.description,
                argv=list(command.argv),
                returncode=0,
                duration_seconds=0.5,
                stdout="ok",
                env=command.env,
            )
            for command in commands
        ]

    monkeypatch.setattr(module, "run_proof", fake_run_proof)

    exit_code = module.main(
        [
            "--active-app",
            str(active_app),
            "--json",
            "--with-ui",
            "--manifest-out",
            str(manifest_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "run_manifest" not in payload
    assert payload["run_manifest_path"] == str(manifest_path)
    assert payload["run_manifest_summary"]["path"] == str(manifest_path)
    assert payload["run_manifest_summary"]["status"] == "fail"
    assert manifest_path.is_file()
    serialized = json.dumps(payload)
    assert "orchestrate_errors" not in serialized
    assert "sk-test-first-proof" not in serialized
    assert "OPENAI_API_KEY" not in serialized


def test_main_human_no_manifest_reports_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    active_app = tmp_path / "custom_project"
    active_app.mkdir()
    (active_app / "pyproject.toml").write_text("[project]\nname = 'custom'\n", encoding="utf-8")

    def fake_run_proof(commands):
        command = commands[0]
        return [
            module.ProofStepResult(
                label=command.label,
                description=command.description,
                argv=list(command.argv),
                returncode=9,
                duration_seconds=0.5,
                stdout="boom",
                env=command.env,
            )
        ]

    monkeypatch.setattr(module, "run_proof", fake_run_proof)

    exit_code = module.main(["--active-app", str(active_app), "--no-manifest"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "verdict: FAIL" in output
    assert "recovery:" in output
    assert "[package preinit smoke output]" in output
    assert "boom" in output


def test_main_human_success_reports_manifest_and_next_steps(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    active_app = tmp_path / "custom_project"
    active_app.mkdir()
    (active_app / "pyproject.toml").write_text("[project]\nname = 'custom'\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest" / "run_manifest.json"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def fake_run_proof(commands):
        command = commands[0]
        return [
            module.ProofStepResult(
                label=command.label,
                description=command.description,
                argv=list(command.argv),
                returncode=0,
                duration_seconds=0.5,
                stdout="",
                env=command.env,
            )
        ]

    monkeypatch.setattr(module, "run_proof", fake_run_proof)

    exit_code = module.main(["--active-app", str(active_app), "--manifest-out", str(manifest_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "verdict: PASS" in output
    assert "run `agilab`" in output
    assert f"run manifest: {manifest_path}" in output
    assert manifest_path.is_file()


def test_run_proof_stops_on_first_failure() -> None:
    module = _load_module()
    commands = module.build_proof_commands(module.default_active_app(), with_install=True, with_ui=True)
    returncodes = iter([0, 7, 0, 0])

    def fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, next(returncodes), stdout="demo", stderr="")

    results = module.run_proof(commands, runner=fake_runner)

    assert [result.label for result in results] == ["package preinit smoke", "package ui smoke"]
    assert results[-1].returncode == 7


def test_run_proof_returns_all_results_when_every_step_passes() -> None:
    module = _load_module()
    commands = module.build_proof_commands(module.default_active_app(), with_install=True)

    def fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    results = module.run_proof(commands, runner=fake_runner)

    assert [result.label for result in results] == [
        "package preinit smoke",
        "flight install smoke",
        "seeded script check",
    ]
    assert all(result.returncode == 0 for result in results)


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


def test_run_command_records_empty_stdout() -> None:
    module = _load_module()
    command = module.ProofCommand(label="demo", description="demo", argv=(sys.executable, "-V"))

    def fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=None, stderr="")

    result = module.run_command(command, runner=fake_runner)

    assert result.returncode == 0
    assert result.stdout == ""


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
    summary = module.summarize_kpi(command_count=len(commands), results=results, max_seconds=600.0)

    manifest = module.build_run_manifest(
        active_app=active_app,
        dry_run=False,
        with_install=False,
        with_ui=False,
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
    assert "OPENAI_API_KEY" not in encoded["command"]["env_overrides"]
    assert encoded["environment"]["app_name"] == "flight_telemetry_project"
    proof_details = encoded["validations"][0]["details"]
    assert "runtime_identity" in proof_details
    assert proof_details["runtime_identity"]["python_executable"] == sys.executable
    assert {item["label"]: item["status"] for item in encoded["validations"]} == {
        "proof_steps": "pass",
        "target_seconds": "pass",
        "recommended_project": "pass",
    }


def test_collect_existing_artifacts_skips_internal_helpers(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    (tmp_path / "AGI_install_flight_telemetry.py").write_text("helper", encoding="utf-8")
    artifact = tmp_path / "metrics.json"
    artifact.write_text("{}", encoding="utf-8")

    artifacts = module._collect_existing_artifacts(tmp_path, manifest_path)

    artifact_names = {item.name for item in artifacts}
    assert {"run_manifest", "metrics.json"} <= artifact_names
    assert ".hidden" not in artifact_names
    assert "AGI_install_flight_telemetry.py" not in artifact_names


def test_collect_existing_artifacts_handles_missing_output_dir(tmp_path: Path) -> None:
    module = _load_module()
    output_dir = tmp_path / "missing-output"
    manifest_path = output_dir / "run_manifest.json"

    artifacts = module._collect_existing_artifacts(output_dir, manifest_path)

    assert [artifact.name for artifact in artifacts] == ["run_manifest"]
    assert artifacts[0].path == str(manifest_path)


def test_executed_argv_records_non_default_options(tmp_path: Path) -> None:
    module = _load_module()
    active_app = tmp_path / "custom_project"
    active_app.mkdir()
    (active_app / "pyproject.toml").write_text("[project]\nname = 'custom'\n", encoding="utf-8")
    manifest_path = tmp_path / "custom-manifest.json"

    argv = module._executed_argv(
        active_app=active_app,
        dry_run=False,
        with_install=True,
        with_ui=True,
        max_seconds=42,
        manifest_path=manifest_path,
    )

    assert argv[:3] == ("agilab", "first-proof", "--json")
    assert "--active-app" in argv
    assert "--with-install" in argv
    assert "--with-ui" in argv
    assert ("--max-seconds", "42") == argv[argv.index("--max-seconds") : argv.index("--max-seconds") + 2]
    assert ("--manifest-out", str(manifest_path)) == argv[
        argv.index("--manifest-out") : argv.index("--manifest-out") + 2
    ]


def test_executed_argv_includes_dry_run_when_requested(tmp_path: Path) -> None:
    module = _load_module()
    active_app = module.default_core_smoke_target()

    argv = module._executed_argv(
        active_app=active_app,
        dry_run=True,
        with_install=False,
        with_ui=False,
        max_seconds=float(module.DEFAULT_MAX_SECONDS),
        manifest_path=tmp_path / "run_manifest.json",
    )

    assert argv[:4] == ("agilab", "first-proof", "--json", "--dry-run")
    assert "--active-app" not in argv


def test_resolve_active_app_rejects_missing_path_and_files(tmp_path: Path) -> None:
    module = _load_module()
    missing = tmp_path / "missing_project"
    file_path = tmp_path / "demo_project"
    file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Active app path not found"):
        module.resolve_active_app(str(missing))
    with pytest.raises(NotADirectoryError):
        module.resolve_active_app(str(file_path))


def test_resolve_active_app_explains_missing_packaged_app_payload(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    package_root = tmp_path / "package" / "agilab"
    monkeypatch.setattr(module, "PACKAGE_ROOT", package_root)
    monkeypatch.setattr(module, "_detect_repo_root", lambda start=package_root: None)

    with pytest.raises(FileNotFoundError, match=r"agilab\[examples\].*agilab\[ui\]"):
        module.resolve_active_app(None)


def test_dry_run_does_not_require_public_asset_packages(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_module()
    package_root = tmp_path / "package" / "agilab"
    package_root.mkdir(parents=True)
    monkeypatch.setattr(module, "PACKAGE_ROOT", package_root)
    monkeypatch.setattr(module, "_detect_repo_root", lambda start=package_root: None)

    captured_commands = []

    def fake_run_proof(commands):
        captured_commands.extend(commands)
        return [
            module.ProofStepResult(
                label=command.label,
                description=command.description,
                argv=list(command.argv),
                returncode=0,
                duration_seconds=0.25,
                stdout="core ok",
                env=command.env,
            )
            for command in commands
        ]

    monkeypatch.setattr(module, "run_proof", fake_run_proof)

    exit_code = module.main(["--dry-run", "--json", "--no-manifest"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["active_app"] == str(package_root.resolve())
    assert payload["success"] is True
    assert [command.label for command in captured_commands] == ["package preinit smoke"]
    assert "active_app =" not in captured_commands[0].argv[-1]
    assert "core-smoke" in captured_commands[0].argv[-1]


def test_resolve_active_app_rejects_missing_pyproject(tmp_path: Path) -> None:
    module = _load_module()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()

    with pytest.raises(FileNotFoundError, match="pyproject.toml"):
        module.resolve_active_app(str(active_app))


def test_write_agilab_path_marker_initializes_packaged_examples(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setenv("HOME", str(tmp_path))

    marker = module.write_agilab_path_marker()

    assert marker == tmp_path / ".local" / "share" / "agilab" / ".agilab-path"
    assert marker.read_text(encoding="utf-8").strip() == str(ROOT / "src" / "agilab")


def test_agi_apps_umbrella_keeps_installer_without_payload_dependencies() -> None:
    pyproject = tomllib.loads(AGI_APPS_PYPROJECT.read_text(encoding="utf-8"))

    package_data = pyproject["tool"]["setuptools"]["package-data"]["agilab.apps"]
    dependencies = pyproject["project"]["dependencies"]

    assert "install.py" in package_data
    builtin_patterns = [pattern for pattern in package_data if pattern.startswith("builtin/")]
    assert builtin_patterns == ["builtin/mycode_project/**/*"]
    assert any(dependency.startswith("agi-core==") for dependency in dependencies)
    assert {
        _project_dependency_pin("agi-app-mission-decision"),
        _project_dependency_pin("agi-app-flight-telemetry"),
        _project_dependency_pin("agi-app-weather-forecast"),
        _project_dependency_pin("agi-app-uav-relay-queue"),
    } <= set(dependencies)


def test_flight_telemetry_project_package_data_includes_payload_for_execute() -> None:
    pyproject = tomllib.loads(
        (ROOT / "src/agilab/lib/agi-app-flight-telemetry/pyproject.toml").read_text(encoding="utf-8")
    )

    package_data = pyproject["tool"]["setuptools"]["package-data"]["agi_app_flight_telemetry"]
    excluded_data = pyproject["tool"]["setuptools"].get("exclude-package-data", {}).get("agi_app_flight_telemetry", [])

    assert (ROOT / "src/agilab/apps/builtin/flight_telemetry_project/src/flight_worker/dataset.7z").is_file()
    assert "project/**/*" in package_data
    assert "project/**/.venv/**" in excluded_data


def test_package_discovery_includes_about_page_helpers() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_includes = set(pyproject["tool"]["setuptools"]["packages"]["find"]["include"])

    assert "agilab.about_page*" in package_includes
    for helper in ("bootstrap.py", "env_editor.py", "layout.py", "onboarding.py"):
        assert (ROOT / "src" / "agilab" / "about_page" / helper).is_file()


def test_script_entrypoint_print_only_exits_successfully(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "--print-only"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")

    assert exc.value.code == 0
    assert "AGILAB first proof" in capsys.readouterr().out
