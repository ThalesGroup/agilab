from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/compatibility_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("compatibility_report_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_passes_public_compatibility_contracts() -> None:
    module = _load_module()

    report = module.build_report()

    assert report["report"] == "Compatibility report"
    assert report["status"] == "pass"
    assert report["summary"]["status_counts"] == {
        "documented": 2,
        "validated": 4,
    }
    assert report["summary"]["workflow_backed_validated_paths"] == 4
    check_ids = {check["id"] for check in report["checks"]}
    assert check_ids == {
        "compatibility_matrix_schema",
        "required_public_statuses",
        "workflow_evidence_commands",
        "documented_route_boundaries",
        "compatibility_docs_report_reference",
    }


def test_required_public_statuses_include_hf_demo_and_documented_routes() -> None:
    module = _load_module()

    check = module._check_required_public_statuses(Path.cwd())

    assert check["status"] == "pass"
    statuses = check["details"]["actual_statuses"]
    assert statuses["agilab-hf-demo"] == "validated"
    assert statuses["notebook-quickstart"] == "documented"
    assert check["details"]["mismatched"] == {}


def test_workflow_evidence_commands_resolve_public_proof_tools() -> None:
    module = _load_module()

    check = module._check_workflow_evidence_commands(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["missing_snippets"] == {}
    assert check["details"]["missing_files"] == {}
    assert check["details"]["required_evidence"]["source-checkout-first-proof"] == (
        "tools/newcomer_first_proof.py",
        "--json",
        "run_manifest.json",
    )


def test_main_emits_json_and_returns_success(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--compact"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"] == "Compatibility report"
    assert payload["status"] == "pass"
    assert payload["summary"]["failed"] == 0
