from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import tomllib

import pytest


MODULE_PATH = Path("tools/profile_supply_chain_scan.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("profile_supply_chain_scan_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_profile_scan_exports_matching_extra(tmp_path: Path) -> None:
    module = _load_module()

    scan = module.build_profile_scan("agents", output_root=tmp_path)

    export_cmd = list(scan.commands[0])
    assert scan.extras == ("agents",)
    assert export_cmd[:5] == ["uv", "--preview-features", "extra-build-dependencies", "export", "--no-dev"]
    assert "--extra" in export_cmd
    assert "agents" in export_cmd
    assert scan.requirements.endswith("agents/requirements.txt")
    assert scan.audit_requirements.endswith("agents/requirements-audit.txt")
    assert scan.pip_audit_json.endswith("agents/pip-audit.json")
    assert scan.sbom_json.endswith("agents/sbom-cyclonedx.json")
    assert str(scan.audit_requirements) in scan.commands[1]
    assert "--no-deps" in scan.commands[1]
    assert "--disable-pip" in scan.commands[1]


def test_cli_prints_all_profile_scan_plan(tmp_path: Path, capsys) -> None:
    module = _load_module()

    rc = module.main(["--output-dir", str(tmp_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    profiles = {entry["profile"]: entry for entry in payload["profiles"]}
    assert set(profiles) == set(module.DEFAULT_PROFILES)
    assert profiles["base"]["extras"] == []
    assert profiles["ui"]["extras"] == ["ui"]
    assert profiles["pages"]["extras"] == ["pages"]
    assert profiles["agents"]["extras"] == ["agents"]
    assert profiles["examples"]["extras"] == ["examples"]
    assert profiles["dev"]["extras"] == ["dev"]
    assert profiles["core"]["extras"] == ["core"]
    assert profiles["viz"]["extras"] == ["viz"]
    assert profiles["bridges"]["extras"] == ["bridges"]
    assert profiles["notebook"]["extras"] == ["notebook"]
    assert profiles["proof"]["extras"] == ["proof"]
    assert profiles["packaged-projects"]["extras"] == []
    assert any("pip-audit" in command for command in profiles["ui"]["commands"][1])
    assert any("cyclonedx-py" in command for command in profiles["ui"]["commands"][2])


def test_scanner_covers_every_root_optional_extra() -> None:
    module = _load_module()
    root = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert set(module.ROOT_OPTIONAL_EXTRAS) == set(
        root["project"]["optional-dependencies"]
    )
    for profile in ("ui", "proof"):
        assert "cryptography>=50.0.0,<51" in root["project"]["optional-dependencies"][profile]
    assert "mlflow-skinny>=3.14,<4" in root["project"]["optional-dependencies"]["mlflow"]
    assert "override-dependencies" not in root["tool"]["uv"]


def test_packaged_projects_profile_collects_build_source_dependencies(tmp_path: Path) -> None:
    module = _load_module()
    scan = module.build_profile_scan(module.PACKAGED_PROJECTS_PROFILE, output_root=tmp_path)

    assert all(path.startswith("src/agilab/apps/builtin/") for path in scan.source_manifests)
    assert any(path.endswith("weather_forecast_project/pyproject.toml") for path in scan.source_manifests)
    assert any("weather_forecast_worker/pyproject.toml" in path for path in scan.source_manifests)
    assert list(scan.commands[0])[:5] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "pip",
        "compile",
    ]

    destination = Path(scan.input_requirements)
    module.write_packaged_project_requirements(
        destination,
        (module.REPO_ROOT / path for path in scan.source_manifests),
    )
    requirements = destination.read_text(encoding="utf-8")
    assert "skforecast>=0.19,<0.20" in requirements
    assert "torch>=2.8.0,<3" in requirements


def test_packaged_project_manifests_ignore_stale_generated_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    package_path = "src/agilab/lib/agi-app-weather-forecast"
    monkeypatch.setattr(
        module,
        "APP_PROJECT_PACKAGE_SPECS",
        (("agi-app-weather-forecast", package_path),),
    )
    package_root = tmp_path / package_path
    provider = package_root / "src/agi_app_weather_forecast/__init__.py"
    provider.parent.mkdir(parents=True)
    provider.write_text('PROJECT_NAME = "weather_forecast_project"\n', encoding="utf-8")

    canonical = (
        tmp_path
        / "src/agilab/apps/builtin/weather_forecast_project/pyproject.toml"
    )
    canonical.parent.mkdir(parents=True)
    canonical.write_text("[project]\nname = 'weather-forecast'\n", encoding="utf-8")

    stale = (
        package_root
        / "src/agi_app_weather_forecast/project/stale_project/pyproject.toml"
    )
    stale.parent.mkdir(parents=True)
    stale.write_text("[project]\nname = 'stale'\n", encoding="utf-8")

    assert module.packaged_project_manifests(tmp_path) == (canonical,)


def test_packaged_project_manifests_fail_closed_without_provider_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    package_path = "src/agilab/lib/agi-app-weather-forecast"
    monkeypatch.setattr(
        module,
        "APP_PROJECT_PACKAGE_SPECS",
        (("agi-app-weather-forecast", package_path),),
    )

    with pytest.raises(ValueError, match="missing app project provider metadata"):
        module.packaged_project_manifests(tmp_path)


def test_write_pip_audit_requirements_removes_local_editables(tmp_path: Path) -> None:
    module = _load_module()
    requirements = tmp_path / "requirements.txt"
    audit_requirements = tmp_path / "requirements-audit.txt"
    requirements.write_text(
        "\n".join(
            [
                "# exported",
                "-e .",
                "    # via agilab",
                "agi-core @ file:///repo/src/agilab/core/agi-core",
                "    # via agilab",
                "requests==2.33.1 \\",
                "    --hash=sha256:abc",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.write_pip_audit_requirements(requirements, audit_requirements)

    text = audit_requirements.read_text(encoding="utf-8")
    assert "-e ." not in text
    assert "file:///repo" not in text
    assert "requests==2.33.1" in text
    assert "--hash=sha256:abc" in text


def test_current_profiles_have_no_stale_global_vulnerability_ignores(tmp_path: Path) -> None:
    module = _load_module()
    plan = module.build_profile_scan("local-llm", output_root=tmp_path)
    audit_cmd = next(cmd for cmd in plan.commands if "pip-audit" in cmd)
    assert "--ignore-vuln" not in audit_cmd
