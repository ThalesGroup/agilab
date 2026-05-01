from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/public_certification_profile_report.py").resolve()
CORE_PATH = Path("src/agilab/public_certification.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_certification_profile_report_passes_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "public_certification_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "public_certification_profile.json",
    )

    assert report["report"] == "Public certification profile report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.public_certification_profile.v1"
    assert report["summary"]["execution_mode"] == "public_certification_static"
    assert report["summary"]["certification_profile"] == "bounded_public_evidence"
    assert report["summary"]["path_count"] == 6
    assert report["summary"]["certified_public_evidence_count"] == 5
    assert report["summary"]["documented_not_certified_count"] == 1
    assert report["summary"]["certified_beyond_newcomer_operator_count"] == 3
    assert report["summary"]["production_certification_claimed"] is False
    assert report["summary"]["formal_third_party_certification"] is False
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert {check["id"] for check in report["checks"]} == {
        "public_certification_profile_schema",
        "public_certification_profile_scope",
        "public_certification_profile_broader_slices",
        "public_certification_profile_boundaries",
        "public_certification_profile_no_execution",
        "public_certification_profile_persistence",
        "public_certification_profile_docs_reference",
    }


def test_public_certification_profile_marks_documented_routes() -> None:
    core = _load_module(CORE_PATH, "public_certification_core_test_module")

    state = core.build_public_certification_profile(Path.cwd())

    rows = {row["path_id"]: row for row in state["certification_paths"]}
    assert rows["source-checkout-first-proof"]["certification_status"] == (
        "certified_public_evidence"
    )
    assert rows["web-ui-local-first-proof"]["extends_beyond_newcomer_operator"] is True
    assert rows["agilab-hf-demo"]["extends_beyond_newcomer_operator"] is True
    assert rows["notebook-quickstart"]["certification_status"] == (
        "documented_not_certified"
    )
    assert rows["published-package-route"]["certification_status"] == (
        "certified_public_evidence"
    )
    assert state["summary"]["certified_beyond_newcomer_operator_paths"] == [
        "web-ui-local-first-proof",
        "agilab-hf-demo",
        "published-package-route",
    ]
    assert state["summary"]["production_certification_claimed"] is False
