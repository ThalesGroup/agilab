from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agilab import adoption_report, run_manifest  # noqa: E402


def _write_manifest(
    path: Path,
    *,
    app_name: str = "flight_telemetry_project",
    status: str = "pass",
    validation_status: str = "pass",
    argv: tuple[str, ...] = ("agilab", "first-proof", "--json"),
) -> Path:
    project_dir = path.parent / app_name
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest = run_manifest.build_run_manifest(
        path_id="source-checkout-first-proof",
        label="AGILAB first-proof",
        status=status,
        command=run_manifest.RunManifestCommand(
            label="agilab first-proof",
            argv=argv,
            cwd=str(ROOT),
        ),
        environment=run_manifest.RunManifestEnvironment(
            python_version="3.13",
            python_executable=sys.executable,
            platform="test",
            repo_root=str(ROOT),
            active_app=str(project_dir),
            app_name=app_name,
        ),
        timing=run_manifest.RunManifestTiming(
            started_at="2026-05-17T00:00:00Z",
            finished_at="2026-05-17T00:00:05Z",
            duration_seconds=5.0,
            target_seconds=60.0,
        ),
        artifacts=(),
        validations=(
            run_manifest.RunManifestValidation(
                label="proof_steps",
                status=validation_status,
                summary="proof steps passed",
            ),
            run_manifest.RunManifestValidation(
                label="target_seconds",
                status=validation_status,
                summary="target passed",
            ),
            run_manifest.RunManifestValidation(
                label="recommended_project",
                status=validation_status,
                summary="recommended project",
            ),
        ),
        run_id="first-proof-demo",
        created_at="2026-05-17T00:00:05Z",
    )
    return run_manifest.write_run_manifest(manifest, path)


def test_build_report_marks_passing_first_proof_safe_to_expand(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "run_manifest.json")

    report = adoption_report.build_report(manifest_path=manifest_path)

    assert report["kind"] == "agilab.adoption_report"
    assert report["summary"]["first_proof_status"] == "passed"
    assert report["summary"]["safe_to_expand"] is True
    assert report["summary"]["team_trial_handoff_ready"] is False
    assert report["first_proof"]["run_id"] == "first-proof-demo"
    evidence = {item["id"]: item for item in report["evidence"]}
    assert evidence["run_manifest"]["status"] == "present"
    assert evidence["notebook_export"]["status"] == "missing"
    assert "compatibility_report.py" in evidence["compatibility_report"]["command"]
    assert report["next_actions"][0]["label"] == "Capture compatibility evidence"


def test_build_report_detects_complete_handoff_bundle(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "run_manifest.json")
    notebook = tmp_path / "project" / "notebooks" / "lab_stages.ipynb"
    compatibility = tmp_path / "compatibility-report.json"
    security = tmp_path / "security-check.json"
    notebook.parent.mkdir(parents=True)
    notebook.write_text("{}", encoding="utf-8")
    compatibility.write_text("{}", encoding="utf-8")
    security.write_text("{}", encoding="utf-8")

    report = adoption_report.build_report(
        manifest_path=manifest_path,
        notebook_export=notebook,
        compatibility_report=compatibility,
        security_report=security,
    )

    assert report["summary"]["safe_to_expand"] is True
    assert report["summary"]["team_trial_handoff_ready"] is True
    assert report["next_actions"] == [
        {
            "label": "Proceed to the next adoption lane",
            "command": adoption_report.QUICK_START_URL,
            "reason": "The first proof and handoff evidence are present.",
        }
    ]


def test_build_report_explains_missing_manifest(tmp_path: Path) -> None:
    report = adoption_report.build_report(manifest_path=tmp_path / "missing" / "run_manifest.json")

    assert report["summary"]["first_proof_status"] == "missing"
    assert report["summary"]["safe_to_expand"] is False
    assert report["evidence"][0]["status"] == "missing"
    assert report["next_actions"][0]["command"] == "agilab first-proof --json --with-ui"


def test_build_report_rejects_dry_run_as_expansion_baseline(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path / "run_manifest.json",
        app_name="agilab",
        argv=("agilab", "first-proof", "--json", "--dry-run"),
    )

    report = adoption_report.build_report(manifest_path=manifest_path)

    assert report["summary"]["first_proof_status"] == "failing"
    assert report["summary"]["safe_to_expand"] is False
    assert any("--dry-run" in issue for issue in report["first_proof"]["issues"])


def test_render_markdown_includes_evidence_and_next_actions(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "run_manifest.json")
    report = adoption_report.build_report(manifest_path=manifest_path)

    markdown = adoption_report.render_markdown(report)

    assert "# AGILAB Adoption Report" in markdown
    assert "First-proof status: `passed`" in markdown
    assert "Capture compatibility evidence" in markdown


def test_main_writes_json_and_strict_fails_when_manifest_missing(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "run_manifest.json")
    output_path = tmp_path / "adoption-report.json"

    assert adoption_report.main([
        "--manifest",
        str(manifest_path),
        "--json",
        "--output",
        str(output_path),
        "--strict",
    ]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["first_proof_status"] == "passed"

    assert adoption_report.main([
        "--manifest",
        str(tmp_path / "missing.json"),
        "--json",
        "--output",
        str(tmp_path / "missing-report.json"),
        "--strict",
    ]) == 1
