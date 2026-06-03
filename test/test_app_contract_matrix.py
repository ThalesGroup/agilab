from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
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
    assert "app_packages_use_generated_payload_contract" in check_ids
    assert "checked_in_app_payloads_match_generated_payloads" in check_ids
    assert "apps_pages_root_keeps_asset_bundle_shape" in check_ids
    assert "apps_pages_catalog_matches_page_contract" in check_ids
    assert "agi_pages_provider_matches_page_bundle_contract" in check_ids
    assert "promoted_pypi_app_catalog_matches_package_split" in check_ids
    assert "public_app_catalog_matches_package_contract" in check_ids


def test_discover_builtin_projects_ignores_untracked_workspace_dirs(tmp_path: Path, monkeypatch):
    module = _load_module()
    builtin_root = tmp_path / module.BUILTIN_APPS_REL
    tracked_project = builtin_root / "flight_telemetry_project"
    local_workspace = builtin_root / "scratch_project"
    tracked_project.mkdir(parents=True)
    local_workspace.mkdir()

    def _fake_run(*args, **kwargs):
        return module.subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml\0"
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    assert module.discover_builtin_projects(tmp_path) == (tracked_project,)


def test_load_module_supports_package_imports_without_preexisting_src_path(monkeypatch):
    module = _load_module()
    src_path = str((ROOT / "src").resolve())
    monkeypatch.setattr(module.sys, "path", [path for path in sys.path if path != src_path])
    for name in list(sys.modules):
        if name == "agilab" or name.startswith("agilab."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    loaded = module._load_module(
        ROOT,
        Path("src/agilab/pypi_app_packages.py"),
        "agilab_app_contract_pypi_app_packages_plain_python_test",
    )

    assert loaded.PROMOTED_PYPI_APP_PACKAGES
    assert src_path not in module.sys.path


def test_app_contract_matrix_detects_promoted_catalog_drift():
    module = _load_module()

    report = module.build_report(repo_root=ROOT, pypi_promoted_packages=())
    failed = {check["id"]: check for check in report["checks"] if check["status"] == "fail"}

    assert report["status"] == "fail"
    assert "promoted_pypi_app_catalog_matches_package_split" in failed
    assert "agi-app-pytorch-playground" in failed[
        "promoted_pypi_app_catalog_matches_package_split"
    ]["details"]["missing_from_pypi_catalog"]


def test_worker_projects_depend_on_node_cli_runtime_without_cluster_stack() -> None:
    missing_dependency: list[str] = []
    unexpected_cluster_dependency: list[str] = []
    unexpected_cluster_source: list[str] = []
    for pyproject in sorted((ROOT / "src" / "agilab").rglob("*_worker/pyproject.toml")):
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        dependencies = tuple(metadata.get("project", {}).get("dependencies", ()))
        if not any(dependency.startswith("agi-node") for dependency in dependencies):
            missing_dependency.append(pyproject.relative_to(ROOT).as_posix())
        if any(dependency.startswith("agi-cluster") for dependency in dependencies):
            unexpected_cluster_dependency.append(pyproject.relative_to(ROOT).as_posix())
        if pyproject.relative_to(ROOT).as_posix().startswith("src/agilab/apps/builtin/"):
            sources = metadata.get("tool", {}).get("uv", {}).get("sources", {})
            if "agi-cluster" in sources:
                unexpected_cluster_source.append(pyproject.relative_to(ROOT).as_posix())

    assert missing_dependency == []
    assert unexpected_cluster_dependency == []
    assert unexpected_cluster_source == []


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


def test_app_contract_matrix_detects_checked_in_payload_drift(tmp_path: Path, monkeypatch):
    module = _load_module()
    package_root = tmp_path / "src/agilab/lib/agi-app-demo"
    package_import_root = package_root / "src/agi_app_demo"
    embedded_project = package_import_root / "project/demo_project"
    embedded_project.mkdir(parents=True)
    (embedded_project / "value.txt").write_text("old\n", encoding="utf-8")
    (package_root / "setup.py").write_text(
        "APP_PROJECT = 'demo_project'\nPACKAGE_IMPORT = 'agi_app_demo'\n",
        encoding="utf-8",
    )
    (package_root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "agi-app-demo"',
                'version = "1.0"',
                "",
                "[tool.setuptools.package-data]",
                '"agi_app_demo" = ["project/**/*"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    class FakeBuildSupport:
        @staticmethod
        def app_project_specs():
            return (
                {
                    "project": "demo_project",
                    "distribution": "agi-app-demo",
                    "package": "agi_app_demo",
                },
            )

        @staticmethod
        def copy_app_project_payload(project_name: str, target_root: Path):
            generated_project = target_root / project_name
            generated_project.mkdir(parents=True)
            (generated_project / "value.txt").write_text("new\n", encoding="utf-8")
            (generated_project / ".coverage").write_text("generated coverage\n", encoding="utf-8")
            (generated_project / ".coverage.worker").write_text("generated coverage\n", encoding="utf-8")
            return []

    def _fake_load_module(_repo_root: Path, relative_path: Path, _module_name: str):
        if relative_path == module.APP_PROJECT_BUILD_SUPPORT_REL:
            return FakeBuildSupport
        raise AssertionError(relative_path)

    monkeypatch.setattr(module, "_load_module", _fake_load_module)

    contract_errors, drift_errors = module._app_payload_contract_errors(
        tmp_path,
        {"agi-app-demo": "src/agilab/lib/agi-app-demo"},
        {"agi-app-demo": "demo_project"},
    )

    assert contract_errors == {}
    assert drift_errors["agi-app-demo"]["changed"] == ["value.txt"]
    assert ".coverage" not in drift_errors["agi-app-demo"]["missing_from_embedded"]
    assert ".coverage.worker" not in drift_errors["agi-app-demo"]["missing_from_embedded"]


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
