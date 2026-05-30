from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "maintenance_dashboard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("maintenance_dashboard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_maintenance_dashboard_exposes_long_term_contract_checks() -> None:
    module = _load_module()

    report = module.build_report(
        repo_root=ROOT,
        include_app_contracts=False,
        include_hotspots=False,
    )

    assert report["schema"] == "agilab.maintenance_dashboard.v1"
    check_ids = {check["id"] for check in report["checks"]}
    assert {
        "extension_contract_kit",
        "architecture_decision_records",
        "docs_mirror",
        "package_split_contract",
        "release_skip_existing_packages",
        "evidence_core_docs",
        "product_tier_labels",
        "shared_core_guardrails",
        "generated_artifact_hygiene",
        "coverage_badge_signal",
    } <= check_ids


def test_extension_contract_kit_declares_required_extension_types() -> None:
    module = _load_module()

    check = module.check_extension_contract_kit(ROOT).as_dict()

    assert check["status"] == "pass"
    assert set(module.REQUIRED_EXTENSION_TYPES) <= set(check["details"]["type_ids"])
    assert check["details"]["missing_types"] == []
    assert check["details"]["malformed"] == []


def test_release_friction_check_proves_skip_existing_mode_without_network() -> None:
    module = _load_module()

    check = module.check_release_friction(ROOT).as_dict()

    assert check["status"] == "pass"
    assert check["details"]["pypi_selection_mode"] == "missing-artifacts"
    assert check["details"]["pypi_publish_selected"] == "false"
    assert check["details"]["existing_count"] > 0


def test_maintenance_dashboard_cli_writes_machine_readable_report(tmp_path: Path, capsys) -> None:
    module = _load_module()
    output = tmp_path / "maintenance.json"

    rc = module.main(
        [
            "--repo-root",
            str(ROOT),
            "--skip-app-contracts",
            "--skip-hotspots",
            "--output",
            str(output),
            "--compact",
        ]
    )

    captured = capsys.readouterr()
    assert rc in {0, 1}
    report = json.loads(output.read_text(encoding="utf-8"))
    stdout_report = json.loads(captured.out)
    assert report["schema"] == "agilab.maintenance_dashboard.v1"
    assert stdout_report["summary"]["check_count"] == report["summary"]["check_count"]
