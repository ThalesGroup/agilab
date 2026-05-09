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

    scan = module.build_profile_scan("offline", output_root=tmp_path)

    export_cmd = list(scan.commands[0])
    assert scan.extras == ("offline",)
    assert export_cmd[:5] == ["uv", "--preview-features", "extra-build-dependencies", "export", "--no-dev"]
    assert "--extra" in export_cmd
    assert "offline" in export_cmd
    assert scan.requirements.endswith("offline/requirements.txt")
    assert scan.pip_audit_json.endswith("offline/pip-audit.json")
    assert scan.sbom_json.endswith("offline/sbom-cyclonedx.json")


def test_cli_prints_all_profile_scan_plan(tmp_path: Path, capsys) -> None:
    module = _load_module()

    rc = module.main(["--output-dir", str(tmp_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    profiles = {entry["profile"]: entry for entry in payload["profiles"]}
    assert set(profiles) == set(module.DEFAULT_PROFILES)
    assert profiles["base"]["extras"] == []
    assert profiles["ui"]["extras"] == ["ui"]
    assert any("pip-audit" in command for command in profiles["ui"]["commands"][1])
    assert any("cyclonedx-py" in command for command in profiles["ui"]["commands"][2])
