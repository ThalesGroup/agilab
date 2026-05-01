from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/production_readiness_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "production_readiness_report_test_module", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_passes_static_production_readiness_contracts() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)

    assert report["kpi"] == "Production readiness"
    assert report["supported_score"] == module.SUPPORTED_SCORE
    assert report["status"] == "pass"
    assert report["summary"]["docs_profile_executed"] is False
    check_ids = {check["id"] for check in report["checks"]}
    assert check_ids == {
        "docs_mirror_stamp",
        "docs_workflow_parity_profile",
        "compatibility_matrix_validated_paths",
        "service_health_json_prometheus",
        "release_decision_promotion_export",
        "security_disclosure_hardening",
    }


def test_docs_workflow_profile_check_reports_expected_sphinx_command() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    check = next(
        check for check in report["checks"] if check["id"] == "docs_workflow_parity_profile"
    )

    assert check["status"] == "pass"
    release_proof_argv = check["details"]["release_proof_argv"]
    sphinx_argv = check["details"]["sphinx_argv"]
    assert release_proof_argv[-2:] == ["--check", "--compact"]
    assert "tools/release_proof_report.py" in release_proof_argv
    assert sphinx_argv[-2:] == ["docs/source", "docs/html"]
    assert "sphinx" in sphinx_argv
    assert "myst-parser" in sphinx_argv


def test_main_emits_json_and_returns_success(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--compact"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kpi"] == "Production readiness"
    assert payload["status"] == "pass"
    assert payload["summary"]["failed"] == 0
