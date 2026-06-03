from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "data_artifact_lane_contract.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("data_artifact_lane_contract_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str = "payload\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_data_analysis_bundle(root: Path) -> None:
    _write(root / "_in" / "sales.csv", "date,region,revenue\n2026-01-01,north,10\n")
    _write(root / "_out" / "clean" / "clean_sales.csv", "date,region,revenue\n2026-01-01,north,10\n")
    _write(root / "_out" / "aggregates" / "revenue_by_region_month.csv", "region,year_month,revenue\nnorth,2026-01,10\n")
    _write(root / "_out" / "aggregates" / "REPORT.md", "# Report\n")
    _write(root / "_out" / "viz" / "revenue_by_region_month_overall.svg", "<svg />\n")


def test_data_analysis_bundle_contract_passes(tmp_path: Path) -> None:
    module = _load_module()
    _make_data_analysis_bundle(tmp_path)

    report = module.build_contract_report(root=tmp_path, profile_id="data-analysis")

    assert report["schema"] == module.SCHEMA
    assert report["status"] == "pass"
    assert report["summary"]["artifact_count"] == 5
    assert report["summary"]["hashed_artifact_count"] == 5
    assert {artifact["rule"] for artifact in report["artifacts"]} == {
        "raw-inputs",
        "cleaned-data",
        "aggregate-data",
        "human-report",
        "visualizations",
    }


def test_data_analysis_bundle_contract_fails_when_report_is_missing(tmp_path: Path) -> None:
    module = _load_module()
    _make_data_analysis_bundle(tmp_path)
    (tmp_path / "_out" / "aggregates" / "REPORT.md").unlink()

    report = module.build_contract_report(root=tmp_path, profile_id="data-analysis")

    assert report["status"] == "fail"
    assert any(issue["rule"] == "required-artifact-missing" and issue["path"] == "human-report" for issue in report["issues"])


def test_document_ingestion_contract_accepts_role_overrides(tmp_path: Path) -> None:
    module = _load_module()
    input_dir = tmp_path / "watch"
    output_dir = tmp_path / "markdown"
    done_dir = tmp_path / "processed"
    _write(output_dir / "paper.md", "# Paper\n")
    (done_dir).mkdir(parents=True)
    (done_dir / "paper.pdf").write_bytes(b"%PDF-1.7\n")
    input_dir.mkdir()

    report = module.build_contract_report(
        root=tmp_path,
        profile_id="document-ingestion",
        role_overrides={
            "input": input_dir,
            "output": output_dir,
            "done": done_dir,
        },
    )

    assert report["status"] == "pass"
    assert report["summary"]["artifact_count"] == 2
    assert {rule["id"]: rule["match_count"] for rule in report["artifact_rules"]}["pending-documents"] == 0


def test_cli_writes_json_report(tmp_path: Path) -> None:
    _make_data_analysis_bundle(tmp_path)
    output = tmp_path / "contract.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--root",
            str(tmp_path),
            "--profile",
            "data-analysis",
            "--check",
            "--json",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.data_artifact_lane_contract.v1"
    assert written["status"] == "pass"
