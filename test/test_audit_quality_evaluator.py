from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_quality_evaluator.py"
FIXTURES = ROOT / "test" / "fixtures" / "audit_quality"
SPEC = importlib.util.spec_from_file_location("audit_quality_evaluator_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_audit_quality_evaluator_scores_strong_audit() -> None:
    payload = module.evaluate_text(_fixture("strong_agilab_audit.md"))

    assert payload["score"] >= 85
    assert payload["grade"] in {"strong", "excellent"}
    by_id = {item["id"]: item for item in payload["rubric"]}
    assert by_id["evidence"]["score"] == by_id["evidence"]["weight"]
    assert by_id["security_release"]["score"] == by_id["security_release"]["weight"]
    assert payload["architecture_evidence"]["status"] == "pass"


def test_audit_quality_evaluator_flags_weak_audit() -> None:
    payload = module.evaluate_text(_fixture("weak_agilab_audit.md"))

    assert payload["score"] < 50
    assert payload["grade"] == "poor"
    missing_ids = {item["id"] for item in payload["missing_or_partial"]}
    assert {"scope", "evidence", "severity", "validation"}.issubset(missing_ids)
    assert payload["architecture_evidence"]["status"] == "fail"


def test_audit_quality_evaluator_cli_writes_json_and_returns_failure(tmp_path: Path) -> None:
    audit = tmp_path / "audit.md"
    output = tmp_path / "report.json"
    audit.write_text(_fixture("weak_agilab_audit.md"), encoding="utf-8")

    rc = module.main([str(audit), "--min-score", "80", "--output", str(output), "--json"])

    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "fail"
    assert payload["threshold"] == 80
    assert payload["source"] == str(audit)
    assert payload["architecture_evidence"]["status"] == "fail"


def test_audit_quality_evaluator_preflight_prints_architecture_checklist(capsys) -> None:
    rc = module.main(["--preflight"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "AGILAB deep-audit preflight" in captured.out
    assert "control plane, payload plane, evidence plane" in captured.out
    assert "Linux, macOS, and Windows" in captured.out
