from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
import tomllib
from types import SimpleNamespace
import zipfile

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
    assert scan.source_constraints in scan.commands[0]
    assert "--no-sources" in scan.commands[0]


def _source_package(root: Path, name: str, metadata: str) -> SimpleNamespace:
    project = root / name
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[build-system]\nrequires = []\nbuild-backend = "metadata_backend"\n'
        'backend-path = ["."]\n[project]\n'
        f'name = "{name}"\nversion = "9999.0.1"\n' + metadata,
        encoding="utf-8",
    )
    (project / "metadata_backend.py").write_text(
        "import pathlib, tomllib\n"
        "def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):\n"
        "    p = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']\n"
        "    dirname = p['name'].replace('-', '_') + '-' + p['version'] + '.dist-info'\n"
        "    d = pathlib.Path(metadata_directory) / dirname; d.mkdir()\n"
        "    lines = ['Metadata-Version: 2.3', 'Name: ' + p['name'], 'Version: ' + p['version']]\n"
        "    lines += ['Requires-Dist: ' + r for r in p.get('dependencies', [])]\n"
        "    for extra, requirements in p.get('optional-dependencies', {}).items():\n"
        "        lines.append('Provides-Extra: ' + extra)\n"
        "        lines += ['Requires-Dist: ' + r + '; extra == ' + repr(extra) for r in requirements]\n"
        "    (d / 'METADATA').write_text('\\n'.join(lines) + '\\n')\n"
        "    return dirname\n",
        encoding="utf-8",
    )
    return SimpleNamespace(name=name, project=name)


def test_packaged_scan_resolves_unpublished_source_versions_and_extra_dependencies(
    tmp_path: Path, monkeypatch,
) -> None:
    """Exercise uv and CycloneDX with no registry or pre-existing first-party release."""
    module = _load_module()
    core = _source_package(tmp_path, "agi-scan-core", 'dependencies = []\n')
    ui = _source_package(
        tmp_path, "agi-scan-ui",
        'dependencies = ["agi-scan-core>=9999"]\n'
        '[project.optional-dependencies]\nwidgets = ["external-widget>=1,<2"]\n',
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "PACKAGE_CONTRACTS", (core, ui))
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    with zipfile.ZipFile(wheelhouse / "external_widget-1.2-py3-none-any.whl", "w") as wheel:
        wheel.writestr("external_widget-1.2.dist-info/METADATA", "Metadata-Version: 2.3\nName: external-widget\nVersion: 1.2\n")
        wheel.writestr("external_widget-1.2.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: regression-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr("external_widget-1.2.dist-info/RECORD", "")
    requirements = tmp_path / "requirements.in"
    requirements.write_text("agi-scan-ui[widgets]>=9999\n", encoding="utf-8")
    constraints = tmp_path / "agilab-first-party-source-constraints.txt"
    module.write_first_party_constraints(constraints)
    compiled = tmp_path / "requirements.txt"
    uv = shutil.which("uv")
    assert uv, "The release security scan requires uv"
    command = [uv, "pip", "compile", "--no-sources", "--generate-hashes", str(requirements),
               "--offline", "--no-index", "--find-links", str(wheelhouse),
               "--output-file", str(compiled)]
    before = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path)
    assert before.returncode != 0
    assert "agi-scan-ui" in before.stderr
    subprocess.run(command + ["--constraint", str(constraints)], check=True, capture_output=True, cwd=tmp_path)
    text = compiled.read_text(encoding="utf-8")
    assert "external-widget==1.2" in text
    assert "agi-scan-core @ file:" in text
    assert "agi-scan-ui @ file:" in text
    assert requirements.read_text(encoding="utf-8") == "agi-scan-ui[widgets]>=9999\n"
    audit = tmp_path / "requirements-audit.txt"
    module.write_pip_audit_requirements(compiled, audit)
    assert "agi-scan-core @" not in audit.read_text(encoding="utf-8")
    assert "agi-scan-ui @" not in audit.read_text(encoding="utf-8")
    assert "external-widget==1.2" in audit.read_text(encoding="utf-8")
    assert "--hash=sha256:" in audit.read_text(encoding="utf-8")
    sbom = tmp_path / "sbom-cyclonedx.json"
    subprocess.run([sys.executable, "-m", "cyclonedx_py", "requirements", str(compiled),
                    "--output-file", str(sbom)], check=True, capture_output=True)
    module.add_first_party_sbom_provenance(compiled, sbom)
    components = {c["name"]: c for c in json.loads(sbom.read_text())["components"]}
    assert components["external-widget"]["version"] == "1.2"
    for package in (core, ui):
        component = components[package.name]
        assert component["version"] == "9999.0.1"
        properties = {p["name"]: p["value"] for p in component["properties"]}
        assert properties["agilab:source-manifest"] == f"{package.name}/pyproject.toml"
        assert len(properties["agilab:source-manifest:sha256"]) == 64
        assert any(r["url"] == (tmp_path / package.project).as_uri() for r in component["externalReferences"])
    requirements.write_text("agi-scan-ui>=10000\n", encoding="utf-8")
    conflict = subprocess.run(command + ["--constraint", str(constraints)], capture_output=True, cwd=tmp_path)
    assert conflict.returncode != 0, "Local source constraints must retain requested version bounds"


def test_first_party_sources_fail_closed_on_missing_or_mismatched_metadata(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    package = _source_package(tmp_path, "agi-scan-core", 'dependencies = []\n')
    monkeypatch.setattr(module, "PACKAGE_CONTRACTS", (package,))
    manifest = tmp_path / package.project / "pyproject.toml"
    manifest.write_text('[project]\nname = "unrelated"\nversion = "1"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="metadata mismatch"):
        module.first_party_sources(tmp_path)
    manifest.unlink()
    with pytest.raises(FileNotFoundError):
        module.first_party_sources(tmp_path)


def test_first_party_sbom_rejects_unregistered_or_missing_components(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    package = _source_package(tmp_path, "agi-scan-core", 'dependencies = []\n')
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "PACKAGE_CONTRACTS", (package,))
    requirements = tmp_path / "requirements.txt"
    sbom = tmp_path / "sbom-cyclonedx.json"
    sbom.write_text('{"components": []}', encoding="utf-8")
    requirements.write_text("unknown @ file:///unregistered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unregistered local package source"):
        module.add_first_party_sbom_provenance(requirements, sbom)
    requirements.write_text(f"{package.name} @ {(tmp_path / package.project).as_uri()}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected one source component"):
        module.add_first_party_sbom_provenance(requirements, sbom)
    uri = (tmp_path / package.project).as_uri()
    requirements.write_text(f"-e {uri}\n", encoding="utf-8")
    sbom.write_text(json.dumps({"components": [{"name": "unknown", "externalReferences": [{"url": uri}]}]}))
    module.add_first_party_sbom_provenance(requirements, sbom)
    component = json.loads(sbom.read_text())["components"][0]
    assert component["name"] == package.name
    assert component["version"] == "9999.0.1"


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
