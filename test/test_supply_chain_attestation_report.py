from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/supply_chain_attestation_report.py").resolve()
CORE_PATH = Path("src/agilab/supply_chain_attestation.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_supply_chain_attestation_report_passes_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "supply_chain_attestation_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "supply_chain_attestation.json",
    )

    assert report["report"] == "Supply-chain attestation report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.supply_chain_attestation.v1"
    assert report["summary"]["execution_mode"] == "supply_chain_static_attestation"
    assert report["summary"]["package_name"] == "agilab"
    assert report["summary"]["lockfile_present"] is True
    assert report["summary"]["license_present"] is True
    assert report["summary"]["core_component_count"] == 4
    assert report["summary"]["aligned_core_versions"] is True
    assert report["summary"]["page_lib_component_count"] == 1
    assert report["summary"]["aligned_page_lib_versions"] is True
    assert report["summary"]["builtin_app_pyproject_count"] == 8
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["formal_supply_chain_attestation"] is False
    assert {check["id"] for check in report["checks"]} == {
        "supply_chain_attestation_schema",
        "supply_chain_attestation_package_metadata",
        "supply_chain_attestation_core_alignment",
        "supply_chain_attestation_page_lib_alignment",
        "supply_chain_attestation_app_manifests",
        "supply_chain_attestation_no_execution",
        "supply_chain_attestation_persistence",
        "supply_chain_attestation_docs_reference",
    }


def test_supply_chain_attestation_records_core_and_app_manifests() -> None:
    core = _load_module(CORE_PATH, "supply_chain_attestation_core_test_module")

    state = core.build_supply_chain_attestation(Path.cwd())

    assert state["run_status"] == "validated"
    assert state["summary"]["package_name"] == "agilab"
    assert state["summary"]["aligned_core_versions"] is True
    assert state["summary"]["aligned_page_lib_versions"] is True
    assert state["summary"]["pinned_core_dependency_count"] >= 1
    assert state["summary"]["pinned_page_lib_dependency_count"] >= 1
    assert {row["name"] for row in state["core_components"]} == {
        "agi-core",
        "agi-env",
        "agi-cluster",
        "agi-node",
    }
    assert {row["name"] for row in state["page_lib_components"]} == {
        "agi-gui",
    }
    assert [row["app"] for row in state["builtin_app_pyprojects"]] == [
        "data_io_2026_project",
        "execution_pandas_project",
        "execution_polars_project",
        "flight_project",
        "meteo_forecast_project",
        "mycode_project",
        "uav_queue_project",
        "uav_relay_queue_project",
    ]
    assert all(row["sha256"] for row in state["root_files"])
    assert state["provenance"]["executes_commands"] is False
    assert state["provenance"]["queries_network"] is False
