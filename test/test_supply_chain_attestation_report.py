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
    assert report["summary"]["core_release_graph_aligned"] is True
    assert report["summary"]["page_lib_component_count"] == 1
    assert report["summary"]["page_lib_release_graph_aligned"] is True
    assert report["summary"]["aligned_internal_dependency_pins"] is True
    assert report["summary"]["mismatched_internal_dependency_pin_count"] == 0
    assert report["summary"]["builtin_app_pyproject_count"] == 10
    assert report["summary"]["package_data_pattern_count"] >= 1
    assert report["summary"]["builtin_payload_file_count"] >= 1
    assert report["summary"]["builtin_payload_bytes"] >= 1
    assert report["summary"]["builtin_payload_within_budget"] is True
    budget = report["summary"]["builtin_payload_budget"]
    assert budget["file_count"] <= budget["max_files"]
    assert budget["bytes"] <= budget["max_bytes"]
    assert report["summary"]["builtin_archive_file_count"] >= 0
    assert report["summary"]["builtin_notebook_file_count"] >= 0
    assert ".toml" in report["summary"]["builtin_payload_extension_counts"]
    assert report["summary"]["aligned_builtin_app_versions"] is True
    assert report["summary"]["mismatched_builtin_app_version_count"] == 0
    assert report["summary"]["aligned_builtin_app_internal_dependency_bounds"] is True
    assert report["summary"]["mismatched_builtin_app_internal_dependency_bound_count"] == 0
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["formal_supply_chain_attestation"] is False
    assert {check["id"] for check in report["checks"]} == {
        "supply_chain_attestation_schema",
        "supply_chain_attestation_package_metadata",
        "supply_chain_attestation_core_alignment",
        "supply_chain_attestation_page_lib_alignment",
        "supply_chain_attestation_internal_dependency_pins",
        "supply_chain_attestation_app_manifests",
        "supply_chain_attestation_builtin_app_alignment",
        "supply_chain_attestation_payload_inventory",
        "supply_chain_attestation_payload_budget",
        "supply_chain_attestation_no_execution",
        "supply_chain_attestation_persistence",
        "supply_chain_attestation_docs_reference",
    }


def test_supply_chain_attestation_records_core_and_app_manifests() -> None:
    core = _load_module(CORE_PATH, "supply_chain_attestation_core_test_module")

    state = core.build_supply_chain_attestation(Path.cwd())

    assert state["run_status"] == "validated"
    assert state["summary"]["package_name"] == "agilab"
    assert state["summary"]["core_release_graph_aligned"] is True
    assert state["summary"]["page_lib_release_graph_aligned"] is True
    assert state["summary"]["aligned_internal_dependency_pins"] is True
    assert state["summary"]["mismatched_internal_dependency_pin_count"] == 0
    assert state["summary"]["aligned_builtin_app_versions"] is True
    assert state["summary"]["mismatched_builtin_app_version_count"] == 0
    assert state["summary"]["aligned_builtin_app_internal_dependency_bounds"] is True
    assert state["summary"]["mismatched_builtin_app_internal_dependency_bound_count"] == 0
    assert state["summary"]["package_data_pattern_count"] >= 1
    assert state["summary"]["builtin_payload_file_count"] >= 1
    assert state["summary"]["builtin_payload_bytes"] >= 1
    assert state["summary"]["builtin_payload_within_budget"] is True
    budget = state["summary"]["builtin_payload_budget"]
    assert budget["file_count"] <= budget["max_files"]
    assert budget["bytes"] <= budget["max_bytes"]
    assert state["summary"]["builtin_payload_extension_counts"][".toml"] >= 1
    assert state["summary"]["builtin_archive_file_count"] >= 0
    assert state["summary"]["builtin_notebook_file_count"] >= 0
    assert all(row["sha256"] for row in state["builtin_payload_files"])
    assert not any("/.venv/" in row["path"] for row in state["builtin_payload_files"])
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
        "global_dag_project",
        "meteo_forecast_project",
        "mycode_project",
        "tescia_diagnostic_project",
        "uav_queue_project",
        "uav_relay_queue_project",
    ]
    assert all(row["sha256"] for row in state["root_files"])
    assert state["provenance"]["executes_commands"] is False
    assert state["provenance"]["queries_network"] is False


def test_supply_chain_attestation_rejects_stale_internal_dependency_pin(
    tmp_path: Path,
) -> None:
    core = _load_module(CORE_PATH, "supply_chain_attestation_core_mismatch_test_module")

    version = "2026.04.30.post4"
    stale_version = "2026.04.30.post3"
    files = {
        "pyproject.toml": (
            "[project]\n"
            "name = 'agilab'\n"
            f"version = '{version}'\n"
            "dependencies = [\n"
            f"  'agi-core=={stale_version}',\n"
            f"  'agi-gui=={version}',\n"
            "]\n"
        ),
        "src/agilab/core/agi-core/pyproject.toml": (
            "[project]\n"
            "name = 'agi-core'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}', 'agi-node=={version}', 'agi-cluster=={version}']\n"
        ),
        "src/agilab/core/agi-env/pyproject.toml": (
            "[project]\n"
            "name = 'agi-env'\n"
            f"version = '{version}'\n"
            "dependencies = []\n"
        ),
        "src/agilab/core/agi-cluster/pyproject.toml": (
            "[project]\n"
            "name = 'agi-cluster'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}', 'agi-node=={version}']\n"
        ),
        "src/agilab/core/agi-node/pyproject.toml": (
            "[project]\n"
            "name = 'agi-node'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}']\n"
        ),
        "src/agilab/lib/agi-gui/pyproject.toml": (
            "[project]\n"
            "name = 'agi-gui'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}']\n"
        ),
        "uv.lock": "",
        "LICENSE": "license\n",
        "README.pypi.md": "readme\n",
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    state = core.build_supply_chain_attestation(tmp_path)

    assert state["run_status"] == "invalid"
    assert state["summary"]["aligned_core_versions"] is True
    assert state["summary"]["core_release_graph_aligned"] is True
    assert state["summary"]["aligned_page_lib_versions"] is True
    assert state["summary"]["page_lib_release_graph_aligned"] is True
    assert state["summary"]["aligned_internal_dependency_pins"] is False
    assert state["summary"]["mismatched_internal_dependency_pin_count"] == 1
    mismatch = state["summary"]["mismatched_internal_dependency_pins"][0]
    assert mismatch["package"] == "agilab"
    assert mismatch["dependency"] == "agi-core"
    assert mismatch["operator"] == "=="
    assert mismatch["expected_operator"] == "=="
    assert mismatch["pinned_version"] == stale_version
    assert mismatch["expected_version"] == version
    assert mismatch["aligned"] is False
    assert mismatch["specifier"] == f"agi-core=={stale_version}"
    assert any(
        issue["location"] == "dependencies.agilab.agi-core"
        for issue in state["issues"]
    )


def test_supply_chain_attestation_accepts_partial_umbrella_post_release(
    tmp_path: Path,
) -> None:
    core = _load_module(CORE_PATH, "supply_chain_attestation_core_partial_release_test_module")

    root_version = "2026.04.30.post4"
    library_version = "2026.04.30.post3"
    files = {
        "pyproject.toml": (
            "[project]\n"
            "name = 'agilab'\n"
            f"version = '{root_version}'\n"
            f"dependencies = ['agi-core=={library_version}', 'agi-gui=={library_version}']\n"
        ),
        "src/agilab/core/agi-core/pyproject.toml": (
            "[project]\n"
            "name = 'agi-core'\n"
            f"version = '{library_version}'\n"
            f"dependencies = ['agi-env=={library_version}', 'agi-node=={library_version}', 'agi-cluster=={library_version}']\n"
        ),
        "src/agilab/core/agi-env/pyproject.toml": (
            "[project]\n"
            "name = 'agi-env'\n"
            f"version = '{library_version}'\n"
            "dependencies = []\n"
        ),
        "src/agilab/core/agi-cluster/pyproject.toml": (
            "[project]\n"
            "name = 'agi-cluster'\n"
            f"version = '{library_version}'\n"
            f"dependencies = ['agi-env=={library_version}', 'agi-node=={library_version}']\n"
        ),
        "src/agilab/core/agi-node/pyproject.toml": (
            "[project]\n"
            "name = 'agi-node'\n"
            f"version = '{library_version}'\n"
            f"dependencies = ['agi-env=={library_version}']\n"
        ),
        "src/agilab/lib/agi-gui/pyproject.toml": (
            "[project]\n"
            "name = 'agi-gui'\n"
            f"version = '{library_version}'\n"
            f"dependencies = ['agi-env=={library_version}']\n"
        ),
        "src/agilab/apps/builtin/demo_project/pyproject.toml": (
            "[project]\n"
            "name = 'demo-project'\n"
            f"version = '{root_version}'\n"
            f"dependencies = ['agi-env>={library_version}', 'agi-node>={library_version}']\n"
        ),
        "uv.lock": "",
        "LICENSE": "license\n",
        "README.pypi.md": "readme\n",
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    state = core.build_supply_chain_attestation(tmp_path)

    assert state["run_status"] == "validated"
    assert state["summary"]["aligned_core_versions"] is False
    assert state["summary"]["core_release_graph_aligned"] is True
    assert state["summary"]["aligned_page_lib_versions"] is False
    assert state["summary"]["page_lib_release_graph_aligned"] is True
    assert state["summary"]["aligned_internal_dependency_pins"] is True
    assert state["summary"]["mismatched_internal_dependency_pin_count"] == 0


def test_supply_chain_attestation_rejects_stale_builtin_app_release_metadata(
    tmp_path: Path,
) -> None:
    core = _load_module(CORE_PATH, "supply_chain_attestation_core_app_test_module")

    version = "2026.04.30.post4"
    stale_version = "2026.04.30.post3"
    files = {
        "pyproject.toml": (
            "[project]\n"
            "name = 'agilab'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-core=={version}', 'agi-gui=={version}']\n"
        ),
        "src/agilab/core/agi-core/pyproject.toml": (
            "[project]\n"
            "name = 'agi-core'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}', 'agi-node=={version}', 'agi-cluster=={version}']\n"
        ),
        "src/agilab/core/agi-env/pyproject.toml": (
            "[project]\n"
            "name = 'agi-env'\n"
            f"version = '{version}'\n"
            "dependencies = []\n"
        ),
        "src/agilab/core/agi-cluster/pyproject.toml": (
            "[project]\n"
            "name = 'agi-cluster'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}', 'agi-node=={version}']\n"
        ),
        "src/agilab/core/agi-node/pyproject.toml": (
            "[project]\n"
            "name = 'agi-node'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}']\n"
        ),
        "src/agilab/lib/agi-gui/pyproject.toml": (
            "[project]\n"
            "name = 'agi-gui'\n"
            f"version = '{version}'\n"
            f"dependencies = ['agi-env=={version}']\n"
        ),
        "src/agilab/apps/builtin/demo_project/pyproject.toml": (
            "[project]\n"
            "name = 'demo-project'\n"
            f"version = '{stale_version}'\n"
            f"dependencies = ['agi-env>={stale_version}', 'agi-node>={version}']\n"
        ),
        "uv.lock": "",
        "LICENSE": "license\n",
        "README.pypi.md": "readme\n",
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    state = core.build_supply_chain_attestation(tmp_path)

    assert state["run_status"] == "invalid"
    assert state["summary"]["aligned_core_versions"] is True
    assert state["summary"]["aligned_page_lib_versions"] is True
    assert state["summary"]["aligned_internal_dependency_pins"] is True
    assert state["summary"]["aligned_builtin_app_versions"] is False
    assert state["summary"]["mismatched_builtin_app_version_count"] == 1
    assert state["summary"]["aligned_builtin_app_internal_dependency_bounds"] is False
    assert state["summary"]["mismatched_builtin_app_internal_dependency_bound_count"] == 1
    app_mismatch = state["summary"]["mismatched_builtin_app_versions"][0]
    assert app_mismatch["app"] == "demo_project"
    bound_mismatch = state["summary"][
        "mismatched_builtin_app_internal_dependency_bounds"
    ][0]
    assert bound_mismatch["package"] == "demo_project"
    assert bound_mismatch["dependency"] == "agi-env"
    assert bound_mismatch["operator"] == ">="
    assert bound_mismatch["expected_operator"] == ">="
    assert bound_mismatch["pinned_version"] == stale_version
    assert bound_mismatch["expected_version"] == version
    assert any(
        issue["location"] == "builtin_apps.demo_project.version"
        for issue in state["issues"]
    )
    assert any(
        issue["location"] == "builtin_apps.demo_project.dependencies.agi-env"
        for issue in state["issues"]
    )
