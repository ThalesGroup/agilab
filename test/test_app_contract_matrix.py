from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "app_contract_matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_app_contract_matrix_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_app_contract_matrix_passes_current_repo():
    module = _load_module()

    report = module.build_report(repo_root=ROOT)
    check_ids = {check["id"] for check in report["checks"]}

    assert report["schema"] == module.SCHEMA
    assert report["status"] == "pass"
    assert report["summary"]["project_count"] >= 10
    assert report["summary"]["failed"] == 0
    assert "pytorch_playground_project:worker_pyproject" in check_ids
    assert "page_bundle_specs_point_to_source_bundles" in check_ids
    assert "page_bundle_pyprojects_match_package_contract" in check_ids
    assert "apps_pages_catalog_matches_page_contract" in check_ids
    assert "agi_pages_provider_matches_page_bundle_contract" in check_ids
    assert "promoted_pypi_app_catalog_matches_package_split" in check_ids
    assert "public_app_catalog_matches_package_contract" in check_ids


def test_app_contract_matrix_detects_promoted_catalog_drift():
    module = _load_module()

    report = module.build_report(repo_root=ROOT, pypi_promoted_packages=())
    failed = {check["id"]: check for check in report["checks"] if check["status"] == "fail"}

    assert report["status"] == "fail"
    assert "promoted_pypi_app_catalog_matches_package_split" in failed
    assert "agi-app-pytorch-playground" in failed[
        "promoted_pypi_app_catalog_matches_package_split"
    ]["details"]["missing_from_pypi_catalog"]


def test_app_contract_matrix_detects_page_bundle_provider_drift():
    module = _load_module()
    package_split = module._load_module(
        ROOT,
        Path("tools/package_split_contract.py"),
        "agilab_app_contract_matrix_page_drift_split",
    )

    class FakePackageSplit:
        APP_PROJECT_PACKAGE_SPECS = package_split.APP_PROJECT_PACKAGE_SPECS
        PROMOTED_APP_PROJECT_PACKAGE_NAMES = package_split.PROMOTED_APP_PROJECT_PACKAGE_NAMES
        PAGE_BUNDLE_PACKAGE_SPECS = tuple(
            spec
            for spec in package_split.PAGE_BUNDLE_PACKAGE_SPECS
            if spec[0] != "agi-page-training-report"
        )

    report = module.build_report(
        repo_root=ROOT,
        package_split_module=FakePackageSplit,
        pypi_promoted_packages=package_split.PROMOTED_APP_PROJECT_PACKAGE_NAMES,
    )
    failed = {check["id"]: check for check in report["checks"] if check["status"] == "fail"}

    assert report["status"] == "fail"
    assert "agi_pages_provider_matches_page_bundle_contract" in failed
    assert "view_training_analysis" in failed[
        "agi_pages_provider_matches_page_bundle_contract"
    ]["details"]["extra_in_provider"]


def test_app_contract_matrix_detects_page_bundle_pyproject_drift():
    module = _load_module()
    package_split = module._load_module(
        ROOT,
        Path("tools/package_split_contract.py"),
        "agilab_app_contract_matrix_page_pyproject_drift_split",
    )

    class FakePackageSplit:
        APP_PROJECT_PACKAGE_SPECS = package_split.APP_PROJECT_PACKAGE_SPECS
        PROMOTED_APP_PROJECT_PACKAGE_NAMES = package_split.PROMOTED_APP_PROJECT_PACKAGE_NAMES
        PAGE_BUNDLE_PACKAGE_SPECS = tuple(
            ("agi-page-renamed-map", project)
            if package == "agi-page-geospatial-map"
            else (package, project)
            for package, project in package_split.PAGE_BUNDLE_PACKAGE_SPECS
        )

    report = module.build_report(
        repo_root=ROOT,
        package_split_module=FakePackageSplit,
        pypi_promoted_packages=package_split.PROMOTED_APP_PROJECT_PACKAGE_NAMES,
    )
    failed = {check["id"]: check for check in report["checks"] if check["status"] == "fail"}

    assert report["status"] == "fail"
    assert "page_bundle_pyprojects_match_package_contract" in failed
    assert failed["page_bundle_pyprojects_match_package_contract"]["details"]["errors"][
        "agi-page-renamed-map"
    ]["name"] == "agi-page-geospatial-map"


def test_app_contract_matrix_cli_writes_json_output(tmp_path: Path, capsys):
    module = _load_module()
    output_path = tmp_path / "app-contracts.json"

    assert module.main(["--output", str(output_path), "--compact"]) == 0

    stdout_report = json.loads(capsys.readouterr().out)
    file_report = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_report["schema"] == module.SCHEMA
    assert file_report["summary"]["check_count"] == stdout_report["summary"]["check_count"]


def test_app_contract_matrix_quiet_mode_suppresses_stdout(capsys):
    module = _load_module()

    assert module.main(["--quiet"]) == 0

    assert capsys.readouterr().out == ""
