from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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
    assert any("pip-audit" in command for command in profiles["ui"]["commands"][1])
    assert any("cyclonedx-py" in command for command in profiles["ui"]["commands"][2])


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
