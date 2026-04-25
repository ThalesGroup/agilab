from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SRC_ROOT = Path("src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
package = sys.modules.get("agilab")
package_paths = getattr(package, "__path__", None)
if package_paths is not None and str(SRC_ROOT / "agilab") not in list(package_paths):
    package_paths.append(str(SRC_ROOT / "agilab"))

from agilab.ci_provider_artifacts import (
    build_artifact_index_from_archives,
    write_artifact_index,
    write_sample_github_actions_archive,
)


REPORT_PATH = Path("tools/ci_artifact_harvest_report.py").resolve()
CORE_PATH = Path("src/agilab/ci_artifact_harvest.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ci_artifact_harvest_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "ci_artifact_harvest_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "ci_artifact_harvest.json",
    )

    assert report["report"] == "CI artifact harvest report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.ci_artifact_harvest.v1"
    assert report["summary"]["run_status"] == "harvest_ready"
    assert report["summary"]["execution_mode"] == "ci_artifact_contract_only"
    assert report["summary"]["release_status"] == "validated"
    assert report["summary"]["artifact_count"] == 4
    assert report["summary"]["required_artifact_count"] == 4
    assert report["summary"]["loaded_artifact_count"] == 4
    assert report["summary"]["missing_required_count"] == 0
    assert report["summary"]["checksum_verified_count"] == 4
    assert report["summary"]["checksum_mismatch_count"] == 0
    assert report["summary"]["provenance_tagged_count"] == 4
    assert report["summary"]["external_machine_evidence_count"] == 4
    assert report["summary"]["live_ci_query_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["artifact_kinds"] == [
        "compatibility_report",
        "kpi_evidence_bundle",
        "promotion_decision",
        "run_manifest",
    ]
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "ci_artifact_harvest_schema",
        "ci_artifact_harvest_required_artifacts",
        "ci_artifact_harvest_checksums",
        "ci_artifact_harvest_release_status",
        "ci_artifact_harvest_external_machine_provenance",
        "ci_artifact_harvest_no_live_ci",
        "ci_artifact_harvest_persistence",
        "ci_artifact_harvest_docs_reference",
    }


def test_ci_artifact_harvest_persists_release_mapping(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "ci_artifact_harvest_json_test_module")
    output_path = tmp_path / "ci_artifact_harvest.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=output_path)

    assert report["status"] == "pass"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.ci_artifact_harvest.v1"
    assert payload["run_status"] == "harvest_ready"
    assert payload["execution_mode"] == "ci_artifact_contract_only"
    assert payload["release"]["public_status"] == "validated"
    assert payload["release"]["artifact_statuses"] == {
        "run_manifest": "validated",
        "kpi_evidence_bundle": "validated",
        "compatibility_report": "validated",
        "promotion_decision": "validated",
    }
    assert payload["release"]["missing_required_artifact_kinds"] == []
    assert payload["release"]["failed_required_artifact_kinds"] == []
    assert {artifact["attachment_status"] for artifact in payload["artifacts"]} == {
        "provenance_tagged"
    }
    assert all(artifact["sha256_verified"] is True for artifact in payload["artifacts"])
    assert payload["provenance"]["queries_ci_provider"] is False
    assert payload["provenance"]["executes_network_probe"] is False
    assert payload["provenance"]["executes_commands"] is False


def test_ci_artifact_harvest_report_accepts_provider_artifact_index(
    tmp_path: Path,
) -> None:
    module = _load_module(REPORT_PATH, "ci_artifact_harvest_provider_index_test_module")
    archive_path = write_sample_github_actions_archive(tmp_path / "public-evidence.zip")
    artifact_index_path = tmp_path / "artifact_index.json"
    write_artifact_index(
        artifact_index_path,
        build_artifact_index_from_archives(
            [archive_path],
            repository="ThalesGroup/agilab",
            run_id="123456789",
            workflow="public-evidence.yml",
            run_attempt="1",
            source_machine="github-actions:ubuntu-24.04",
        ),
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "ci_artifact_harvest.json",
        artifact_index_path=artifact_index_path,
    )

    assert report["status"] == "pass"
    assert report["summary"]["artifact_count"] == 4
    assert report["summary"]["release_status"] == "validated"
    assert report["summary"]["external_machine_evidence_count"] == 4


def test_ci_artifact_harvest_core_detects_missing_required_artifacts() -> None:
    module = _load_module(CORE_PATH, "ci_artifact_harvest_core_test_module")

    payload = module.build_ci_artifact_harvest(
        [
            {
                "id": "run_manifest",
                "kind": "run_manifest",
                "path": "run_manifest.json",
                "payload": {
                    "kind": "agilab.run_manifest",
                    "path_id": "source-checkout-first-proof",
                    "status": "pass",
                },
                "source_machine": "github-actions:macos",
                "workflow": "public-evidence.yml",
                "run_attempt": "1",
            }
        ]
    )

    assert payload["run_status"] == "incomplete"
    assert payload["summary"]["artifact_count"] == 1
    assert payload["summary"]["missing_required_count"] == 3
    assert payload["release"]["public_status"] == "missing_evidence"
    assert payload["release"]["missing_required_artifact_kinds"] == [
        "kpi_evidence_bundle",
        "compatibility_report",
        "promotion_decision",
    ]
