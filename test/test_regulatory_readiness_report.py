from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "regulatory_readiness_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("regulatory_readiness_report_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_ready_bundle(root: Path) -> Path:
    run_manifest = root / "run_manifest.json"
    run_manifest.write_text(
        json.dumps(
            {
                "schema": "agilab.run_manifest.v1",
                "app": "screening_demo",
                "purpose": "AI assistant for candidate screening in a controlled validation lab",
                "status": "success",
                "command": "agilab first-proof --json",
                "started_at": "2026-05-31T10:00:00Z",
                "finished_at": "2026-05-31T10:01:00Z",
                "artifacts": ["technical_documentation.md", "data_lineage.md"],
            }
        ),
        encoding="utf-8",
    )
    files = {
        "data_lineage.md": "Dataset scope, training split, validation split, and input lineage.",
        "technical_documentation.md": "Technical documentation and architecture report.",
        "human_oversight_review.md": "Human oversight review and operator approval decision.",
        "transparency_instructions.md": "Transparency disclosure and deployer instructions for use.",
        "security_check.json": '{"security": "checked", "sbom": "available", "pip-audit": "pass"}',
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return run_manifest


def test_report_exposes_non_legal_boundary_for_missing_evidence(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(root=tmp_path, source_review_date="2026-05-31")

    assert report["schema"] == module.SCHEMA
    assert report["status"] == "needs-evidence"
    assert "not legal advice" in report["disclaimer"]
    assert report["summary"]["gap_count"] > 0
    assert {source["id"] for source in report["source_review"]["references"]} == {
        "ec-ai-act-overview",
        "ai-act-service-desk-timeline",
        "eurlex-2024-1689",
    }


def test_report_can_reach_ready_for_review_with_hashable_evidence(tmp_path: Path) -> None:
    module = _load_module()
    run_manifest = _write_ready_bundle(tmp_path)

    report = module.build_report(
        root=tmp_path,
        run_manifest=run_manifest,
        evidence_dirs=[tmp_path],
        system_description="AI system that screens job applicants by analysing CVs.",
        source_review_date="2026-05-31",
    )

    assert report["status"] == "ready-for-review"
    assert report["summary"]["gap_count"] == 0
    assert report["summary"]["warning_count"] == 0
    assert report["summary"]["hashable_evidence_count"] >= 5
    controls = {row["id"]: row for row in report["controls"]}
    assert controls["human-oversight-evidence"]["status"] == "pass"
    assert controls["security-posture-evidence"]["status"] == "pass"
    assert report["screening"]["risk_bucket"] == "potential-high-risk-review"
    assert report["screening"]["method"].endswith("not legal classification")


def test_stale_source_review_date_is_warning_not_certification(tmp_path: Path) -> None:
    module = _load_module()
    run_manifest = _write_ready_bundle(tmp_path)

    report = module.build_report(
        root=tmp_path,
        run_manifest=run_manifest,
        evidence_dirs=[tmp_path],
        system_description="A chatbot for customer support.",
        source_review_date="2024-01-01",
    )

    assert report["status"] == "needs-review"
    assert report["source_review"]["status"] == "stale"
    controls = {row["id"]: row for row in report["controls"]}
    assert controls["source-freshness"]["status"] == "warning"
    assert report["screening"]["risk_bucket"] == "potential-transparency-obligation-review"


def test_cli_check_fails_when_required_evidence_is_missing(tmp_path: Path, capsys) -> None:
    module = _load_module()

    rc = module.main(["--root", str(tmp_path), "--check", "--json", "--source-review-date", "2026-05-31"])

    assert rc == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "needs-evidence"
