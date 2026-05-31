from __future__ import annotations

import json
from pathlib import Path

from agilab import run_markdown_evidence


def test_run_markdown_evidence_writes_plan_process_report_and_manifest(tmp_path: Path):
    paths = run_markdown_evidence.build_run_evidence_paths(tmp_path / "run_1_evidence")
    log_path = tmp_path / "run.log"
    log_path.write_text("ok\n", encoding="utf-8")

    run_markdown_evidence.write_run_plan(
        paths,
        run_id="run_1",
        app="demo_project",
        target="demo",
        project_path=tmp_path / "demo_project",
        command="OPENAI_API_KEY=secret python run.py",
        execution_mode="cluster",
        cluster_enabled=True,
        service_mode=False,
        approval_required=True,
        approval_status_value="approved",
        created_at="2026-05-31T10:00:00Z",
        metadata={"benchmark": False},
    )
    run_markdown_evidence.append_run_process(
        paths,
        event="started",
        status="running",
        message="started",
        at="2026-05-31T10:00:01Z",
    )
    run_markdown_evidence.write_run_report(
        paths,
        run_id="run_1",
        status="success",
        started_at="2026-05-31T10:00:00Z",
        ended_at="2026-05-31T10:00:03Z",
        duration_seconds=3.0,
        log_path=log_path,
        artifacts=(paths.plan, paths.process),
    )
    run_markdown_evidence.write_run_evidence_manifest(
        paths,
        run_id="run_1",
        status="success",
        context={"app": "demo_project"},
    )

    assert paths.plan.is_file()
    assert paths.process.is_file()
    assert paths.report.is_file()
    assert paths.manifest.is_file()
    assert run_markdown_evidence.RUN_MARKDOWN_EVIDENCE_SCHEMA in paths.plan.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=<redacted>" in paths.plan.read_text(encoding="utf-8")
    report = paths.report.read_text(encoding="utf-8")
    assert "RUN_REPORT" in report
    assert "Verdict: `PASS`" in report

    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert manifest["schema"] == run_markdown_evidence.RUN_MARKDOWN_EVIDENCE_SCHEMA
    assert manifest["run_id"] == "run_1"
    assert {item["relative_path"] for item in manifest["artifacts"]} == {
        "RUN_PLAN.md",
        "RUN_PROCESS.md",
        "RUN_REPORT.md",
    }


def test_execution_approval_contract():
    assert run_markdown_evidence.requires_execution_approval(cluster_enabled=False, service_mode=False) is False
    assert run_markdown_evidence.requires_execution_approval(cluster_enabled=True, service_mode=False) is True
    assert run_markdown_evidence.requires_execution_approval(cluster_enabled=False, service_mode=True) is True
    assert run_markdown_evidence.approval_status(approval_required=False, approved=False) == "not_required"
    assert run_markdown_evidence.approval_status(approval_required=True, approved=False) == "pending"
    assert run_markdown_evidence.approval_status(approval_required=True, approved=True) == "approved"
