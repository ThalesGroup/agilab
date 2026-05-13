from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "release_plan.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

from package_split_contract import LIBRARY_PACKAGE_CONTRACTS, UMBRELLA_PACKAGE_CONTRACT


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
    return {
        "package": package.name,
        "project": package.project,
        "dist": package.dist,
        "pypi_project": package.name,
        "pypi_environment": package.pypi_environment,
        "artifact_policy": package.artifact_policy,
        "publish_to_pypi": "true" if package.role in module.PYPI_PUBLISH_ROLES else "false",
    }


def test_release_plan_library_matrix_matches_package_split_contract() -> None:
    module = _load_module()

    assert module.library_matrix() == [
        _expected_entry(package, module) for package in LIBRARY_PACKAGE_CONTRACTS
    ]
    assert module.umbrella_package() == _expected_entry(UMBRELLA_PACKAGE_CONTRACT, module)


def test_release_plan_publishes_all_payload_packages_required_by_umbrellas() -> None:
    module = _load_module()
    matrix = {entry["package"]: entry for entry in module.library_matrix()}

    assert APP_PROJECT_PACKAGES
    assert PAGE_BUNDLE_PACKAGES
    assert matrix["agi-app-flight-project"]["publish_to_pypi"] == "true"
    for package in (*APP_PROJECT_PACKAGES, *PAGE_BUNDLE_PACKAGES):
        assert matrix[package.name]["publish_to_pypi"] == "true", package.name


def test_release_plan_github_output_is_compact_and_parseable(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "github_output.txt"

    module.write_github_output(output, module.release_plan())

    values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert json.loads(values["library_matrix"]) == module.library_matrix()
    assert json.loads(values["umbrella_package"]) == module.umbrella_package()
    assert "\n" not in values["library_matrix"]


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
