from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "release_plan.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

from package_split_contract import (
    LIBRARY_PACKAGE_CONTRACTS,
    PROMOTED_APP_PROJECT_PACKAGE_NAMES,
    UMBRELLA_PACKAGE_CONTRACT,
)


APP_PROJECT_PACKAGES = tuple(
    package for package in LIBRARY_PACKAGE_CONTRACTS if package.role == "app-project"
)
PAGE_BUNDLE_PACKAGES = tuple(
    package for package in LIBRARY_PACKAGE_CONTRACTS if package.role == "page-bundle"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("release_plan_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _expected_entry(package, module) -> dict[str, str]:
    publish_to_pypi = package.role in module.PYPI_PUBLISH_ROLES or package.name in PROMOTED_APP_PROJECT_PACKAGE_NAMES
    return {
        "package": package.name,
        "project": package.project,
        "dist": package.dist,
        "pypi_project": package.name,
        "pypi_environment": package.pypi_environment,
        "artifact_policy": package.artifact_policy,
        "publish_to_pypi": "true" if publish_to_pypi else "false",
    }


def test_release_plan_library_matrix_matches_package_split_contract() -> None:
    module = _load_module()

    assert module.library_matrix() == [
        _expected_entry(package, module) for package in LIBRARY_PACKAGE_CONTRACTS
    ]
    assert module.umbrella_package() == _expected_entry(UMBRELLA_PACKAGE_CONTRACT, module)


def test_release_plan_publishes_page_payloads_and_promoted_app_payloads() -> None:
    module = _load_module()
    matrix = {entry["package"]: entry for entry in module.library_matrix()}

    assert APP_PROJECT_PACKAGES
    assert PAGE_BUNDLE_PACKAGES
    for package_name in PROMOTED_APP_PROJECT_PACKAGE_NAMES:
        assert matrix[package_name]["publish_to_pypi"] == "true", package_name
    for package in APP_PROJECT_PACKAGES:
        if package.name not in PROMOTED_APP_PROJECT_PACKAGE_NAMES:
            assert matrix[package.name]["publish_to_pypi"] == "false", package.name
    for package in PAGE_BUNDLE_PACKAGES:
        assert matrix[package.name]["publish_to_pypi"] == "true", package.name
    assert matrix["agi-pages"]["publish_to_pypi"] == "true"
    assert matrix["agi-apps"]["publish_to_pypi"] == "true"


def test_release_plan_github_output_is_compact_and_parseable(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "github_output.txt"

    module.write_github_output(output, module.release_plan())

    values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert json.loads(values["library_matrix"]) == module.library_matrix()
    assert json.loads(values["umbrella_package"]) == module.umbrella_package()
    assert values["library_selected"] == "true"
    assert values["umbrella_selected"] == "true"
    assert values["pypi_publish_selected"] == "true"
    assert "agi-env" in values["provenance_packages"]
    assert "\n" not in values["library_matrix"]


def test_release_plan_can_target_page_packages_without_unrelated_apps() -> None:
    module = _load_module()

    payload = module.release_plan(roles=["page-bundle"])

    selected_names = {package["package"] for package in payload["library_matrix"]}
    assert selected_names == {package.name for package in PAGE_BUNDLE_PACKAGES}
    assert payload["library_selected"] == "true"
    assert payload["umbrella_selected"] == "false"
    assert payload["pypi_publish_selected"] == "true"
    assert set(payload["provenance_packages"]) == selected_names
    assert "agi-app-uav-relay-queue" not in selected_names


def test_release_plan_can_target_umbrella_only() -> None:
    module = _load_module()

    payload = module.release_plan(package_names=["agilab"])

    assert payload["library_matrix"] == []
    assert payload["library_selected"] == "false"
    assert payload["umbrella_selected"] == "true"
    assert payload["pypi_publish_selected"] == "true"
    assert payload["provenance_packages"] == ["agilab"]


def test_release_plan_rejects_unknown_filters() -> None:
    module = _load_module()

    with pytest.raises(ValueError, match="Unknown package"):
        module.release_plan(package_names=["missing-package"])
    with pytest.raises(ValueError, match="Unknown package role"):
        module.release_plan(roles=["missing-role"])


def test_release_plan_workflow_contract_rejects_static_library_matrix(tmp_path: Path) -> None:
    module = _load_module()
    workflow = tmp_path / "pypi-publish.yaml"
    workflow.write_text(
        """
publish-library-packages:
  strategy:
    matrix:
      include:
          - package: agi-env
""",
        encoding="utf-8",
    )

    missing = module.validate_workflow_contract(workflow)

    assert "library package matrix must not be hard-coded in the workflow" in missing


def test_release_plan_current_workflow_consumes_generated_matrix() -> None:
    module = _load_module()
    missing = module.validate_workflow_contract(
        REPO_ROOT / ".github/workflows/pypi-publish.yaml"
    )

    assert missing == []
