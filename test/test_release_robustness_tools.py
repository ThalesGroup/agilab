from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pending_publisher = _load_tool("pypi_pending_trusted_publisher")
pypi_project_preflight = _load_tool("pypi_project_preflight")
release_handoff_guard = _load_tool("release_handoff_guard")
release_status = _load_tool("release_status")


def _planned_project(version: str = "2026.05.26") -> pypi_project_preflight.PlannedPyPIProject:
    return pypi_project_preflight.PlannedPyPIProject(
        package="agi-page-live-artifacts",
        project="src/agilab/apps-pages/view_live_artifacts",
        pypi_project="agi-page-live-artifacts",
        pypi_environment="pypi-agi-page-live-artifacts",
        artifact_policy="wheel+sdist",
        version=version,
    )


def test_pypi_project_preflight_reports_missing_project_with_pending_command() -> None:
    status = pypi_project_preflight.classify_project(
        _planned_project(),
        fetch_json=lambda _name: None,
    )

    assert status.status == "missing-project"
    assert status.pending_publisher_command is not None
    assert "pypi-pending-trusted-publisher.yaml" in status.pending_publisher_command
    assert "project_name=agi-page-live-artifacts" in status.pending_publisher_command
    assert "pypi_environment=pypi-agi-page-live-artifacts" in status.pending_publisher_command


def test_pypi_project_preflight_treats_pep440_normalized_version_as_current() -> None:
    status = pypi_project_preflight.classify_project(
        _planned_project(version="2026.05.26"),
        fetch_json=lambda _name: {
            "info": {"version": "2026.5.26"},
            "releases": {"2026.5.26": []},
        },
    )

    assert status.status == "current"
    assert status.latest == "2026.5.26"


def test_pypi_project_preflight_allows_existing_project_with_unpublished_version() -> None:
    report = pypi_project_preflight.build_report(
        fetch_json=lambda _name: {
            "info": {"version": "2026.5.25"},
            "releases": {"2026.5.25": []},
        },
        package_names=["agi-page-live-artifacts"],
    )

    assert report["status"] == "pass"
    assert report["summary"]["to_publish"] == 1
    assert report["blockers"] == []


def test_pypi_project_preflight_allows_explicit_missing_project_for_first_publish() -> None:
    report = pypi_project_preflight.build_report(
        fetch_json=lambda _name: None,
        package_names=["agi-page-live-artifacts"],
        allowed_missing_projects=["agi-page-live-artifacts"],
    )

    assert report["status"] == "pass"
    assert report["summary"]["allowed_missing_projects"] == 1
    assert report["allowed_missing_projects"][0]["pypi_project"] == "agi-page-live-artifacts"
    assert report["blockers"] == []


def test_release_status_derives_package_version_from_release_tag() -> None:
    assert release_status.package_version_from_tag("v2026.05.23-2") == "2026.05.23"
    assert release_status.package_version_from_tag("refs/tags/v2026.05.26") == "2026.05.26"


def test_release_handoff_guard_requires_archiving_old_handoffs(tmp_path: Path) -> None:
    handoff = tmp_path / "v2026.05.23-2-other-machine.md"
    handoff.write_text("# AGILAB release handoff for v2026.05.23-2\n", encoding="utf-8")

    assert release_handoff_guard.stale_handoffs(
        handoff_dir=tmp_path,
        latest_tag="v2026.05.26",
    ) == [handoff]

    handoff.write_text(
        "# AGILAB release handoff for v2026.05.23-2\n\nStatus: archived\n",
        encoding="utf-8",
    )

    assert release_handoff_guard.stale_handoffs(
        handoff_dir=tmp_path,
        latest_tag="v2026.05.26",
    ) == []


def test_pending_publisher_confirm_url_freshness_blocks_stale_variable() -> None:
    payload = pending_publisher.GitHubActionsVariable(
        value="https://pypi.org/account/confirm-login/?token=fresh",
        updated_at=100.0,
    )

    assert not pending_publisher._github_variable_is_fresh(
        payload,
        minimum_updated_at=200.0,
        allow_existing=False,
    )
    assert pending_publisher._github_variable_is_fresh(
        payload,
        minimum_updated_at=200.0,
        allow_existing=True,
    )
