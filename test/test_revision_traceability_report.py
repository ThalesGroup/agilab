from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/revision_traceability_report.py").resolve()
CORE_PATH = Path("src/agilab/revision_traceability.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_revision_traceability_report_passes_public_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "revision_traceability_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "revision_traceability.json",
    )

    assert report["report"] == "Revision traceability report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.revision_traceability.v1"
    assert report["summary"]["execution_mode"] == "revision_traceability_static"
    assert report["summary"]["core_component_count"] == 5
    assert report["summary"]["builtin_app_count"] == 8
    assert report["summary"]["app_fingerprint_count"] == 8
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert {check["id"] for check in report["checks"]} == {
        "revision_traceability_schema",
        "revision_traceability_repository_head",
        "revision_traceability_core_components",
        "revision_traceability_builtin_apps",
        "revision_traceability_no_execution",
        "revision_traceability_persistence",
        "revision_traceability_docs_reference",
    }


def test_revision_traceability_fingerprints_builtin_apps() -> None:
    core = _load_module(CORE_PATH, "revision_traceability_core_test_module")

    state = core.build_revision_traceability(Path.cwd())

    assert state["run_status"] == "validated"
    assert state["summary"]["builtin_apps"] == [
        "data_io_2026_project",
        "execution_pandas_project",
        "execution_polars_project",
        "flight_project",
        "meteo_forecast_project",
        "mycode_project",
        "uav_queue_project",
        "uav_relay_queue_project",
    ]
    assert {row["name"] for row in state["core_components"]} == {
        "agilab",
        "agi-core",
        "agi-env",
        "agi-cluster",
        "agi-node",
    }
    assert all(row["fingerprint_sha256"] for row in state["builtin_apps"])
    assert state["provenance"]["uses_git_cli"] is False
    assert state["provenance"]["queries_network"] is False
