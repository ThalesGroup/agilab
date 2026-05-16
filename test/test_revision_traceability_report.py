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
    assert report["summary"]["builtin_app_count"] == 13
    assert report["summary"]["app_fingerprint_count"] == 13
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
        "flight_telemetry_project",
        "global_dag_project",
        "meteo_forecast_project",
        "mission_decision_project",
        "mycode_project",
        "tescia_diagnostic_project",
        "uav_queue_project",
        "uav_relay_queue_project",
        "weather_forecast_project",
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


def test_revision_traceability_reports_missing_synthetic_repo_contracts(tmp_path: Path) -> None:
    core = _load_module(CORE_PATH, "revision_traceability_core_missing_test_module")
    app_dir = tmp_path / "src" / "agilab" / "apps" / "builtin" / "demo_project"
    app_dir.mkdir(parents=True)

    state = core.build_revision_traceability(tmp_path)

    issue_locations = {issue["location"] for issue in state["issues"]}
    assert state["run_status"] == "invalid"
    assert state["repository"]["status"] == "unavailable"
    assert state["summary"]["missing_core_component_count"] == 5
    assert state["summary"]["missing_app_pyproject_count"] == 1
    assert state["summary"]["missing_app_settings_count"] == 1
    assert "core.agilab" in issue_locations
    assert "apps.demo_project" in issue_locations
    assert state["builtin_apps"][0]["fingerprint_sha256"] == core._combined_digest([])


def test_revision_traceability_reads_gitdir_files_packed_refs_and_bad_versions(tmp_path: Path) -> None:
    core = _load_module(CORE_PATH, "revision_traceability_core_git_test_module")

    repo = tmp_path / "repo"
    git_dir = tmp_path / "real-git"
    repo.mkdir()
    git_dir.mkdir()
    (repo / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    packed_commit = "0123456789abcdef0123456789abcdef01234567"
    (git_dir / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n\n{packed_commit} refs/heads/main\n",
        encoding="utf-8",
    )

    assert core._read_git_head(repo) == {
        "status": "available",
        "head": "ref: refs/heads/main",
        "ref": "refs/heads/main",
        "commit": packed_commit,
    }

    (git_dir / "HEAD").write_text("ref: refs/heads/missing\n", encoding="utf-8")
    assert core._read_git_head(repo)["status"] == "unresolved_ref"

    (git_dir / "HEAD").write_text(packed_commit + "\n", encoding="utf-8")
    assert core._read_git_head(repo)["commit"] == packed_commit

    bad_pyproject = repo / "pyproject.toml"
    bad_pyproject.write_text("[project\n", encoding="utf-8")
    assert core._read_pyproject_version(bad_pyproject) == ""
    bad_pyproject.write_text("[tool.demo]\nname = 'not-project'\n", encoding="utf-8")
    assert core._read_pyproject_version(bad_pyproject) == ""
    bad_pyproject.write_text("project = 'not-a-table'\n", encoding="utf-8")
    assert core._read_pyproject_version(bad_pyproject) == ""


def test_persist_revision_traceability_round_trips_invalid_state(tmp_path: Path) -> None:
    core = _load_module(CORE_PATH, "revision_traceability_core_persist_test_module")
    (tmp_path / "src" / "agilab" / "apps" / "builtin").mkdir(parents=True)

    result = core.persist_revision_traceability(
        repo_root=tmp_path,
        output_path=tmp_path / "evidence" / "revision_traceability.json",
    )

    assert result["ok"] is False
    assert result["round_trip_ok"] is True
    assert Path(result["path"]).is_file()
    assert result["state"]["run_status"] == "invalid"
