from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
import subprocess
import sys


ENTRYPOINT_FILES = {"__init__.py", "bridge_cli.py", "lab_run.py", "main_page.py"}
CORE_PACKAGE_ENTRYPOINT_FILES = {"__init__.py"}
TOP_LEVEL_COMPAT_IMPORT_EXEMPTIONS = {
    "agilab.agi_codex",  # Streamlit page module with session-state side effects on plain import.
}


def _target_module_from_shim(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_TARGET_MODULE"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError(f"{path} does not declare _TARGET_MODULE")


def _legacy_name_from_shim(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_activate_compat_module":
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "legacy_name"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                return keyword.value.value
    raise AssertionError(f"{path} does not declare legacy_name")


def test_top_level_agilab_modules_are_classified_or_entrypoints():
    root = Path(__file__).resolve().parents[1] / "src" / "agilab"
    top_level_modules = sorted(path for path in root.glob("*.py"))

    assert {path.name for path in top_level_modules if path.name in ENTRYPOINT_FILES} == ENTRYPOINT_FILES

    for path in top_level_modules:
        if path.name in ENTRYPOINT_FILES:
            continue
        target_module = _target_module_from_shim(path)
        assert target_module.startswith("agilab.")
        relative_target = Path(*target_module.split(".")[1:]).with_suffix(".py")
        assert (root / relative_target).is_file(), (path, target_module)
        text = path.read_text(encoding="utf-8")
        assert "activate_compat_module" in text
        assert "classified" in text
        assert "package layout" in text


def test_top_level_agilab_shims_declare_exact_legacy_names() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "agilab"

    for path in sorted(root.glob("*.py")):
        if path.name in ENTRYPOINT_FILES:
            continue
        assert _legacy_name_from_shim(path) == f"agilab.{path.stem}"


def test_top_level_agilab_compat_modules_preserve_legacy_identity_for_import_safe_shims() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    root = repo_root / "src" / "agilab"
    modules = [
        f"agilab.{path.stem}"
        for path in sorted(root.glob("*.py"))
        if path.name not in ENTRYPOINT_FILES
        and f"agilab.{path.stem}" not in TOP_LEVEL_COMPAT_IMPORT_EXEMPTIONS
    ]
    script = f"""
import importlib

modules = {modules!r}
for name in modules:
    module = importlib.import_module(name)
    expected_package = name.rpartition(".")[0]
    if module.__name__ != name or module.__package__ != expected_package:
        raise AssertionError(
            f"{{name}} exposed {{module.__name__}} / {{module.__package__}}"
        )
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str((repo_root / "src").resolve())

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def _assert_package_modules_are_classified(root: Path, package: str) -> None:
    package_parts = package.split(".")
    direct_modules = sorted(path for path in root.glob("*.py"))

    assert (root / "__init__.py").is_file()

    for path in direct_modules:
        if path.name in CORE_PACKAGE_ENTRYPOINT_FILES:
            continue
        target_module = _target_module_from_shim(path)
        assert target_module.startswith(f"{package}.")
        target_parts = target_module.split(".")
        assert target_parts[: len(package_parts)] == package_parts
        relative_target = Path(*target_parts[len(package_parts) :]).with_suffix(".py")
        assert (root / relative_target).is_file(), (path, target_module)
        text = path.read_text(encoding="utf-8")
        assert "activate_compat_module" in text
        assert "classified" in text
        assert "package layout" in text


def test_agi_env_modules_are_classified_or_entrypoints():
    root = Path(__file__).resolve().parents[1] / "src/agilab/core/agi-env/src/agi_env"

    _assert_package_modules_are_classified(root, "agi_env")


def test_agi_distributor_modules_are_classified_or_entrypoints():
    root = (
        Path(__file__).resolve().parents[1]
        / "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor"
    )

    _assert_package_modules_are_classified(root, "agi_cluster.agi_distributor")


def test_shared_core_compat_modules_preserve_legacy_module_identity():
    assert importlib.import_module("agi_env.pagelib").__name__ == "agi_env.pagelib"
    assert (
        importlib.import_module("agi_cluster.agi_distributor.deployment_local_support").__name__
        == "agi_cluster.agi_distributor.deployment_local_support"
    )


def test_top_level_agilab_compat_modules_preserve_legacy_module_identity():
    assert importlib.import_module("agilab.agent_run").__name__ == "agilab.agent_run"
    assert (
        importlib.import_module("agilab.pipeline_runtime").__name__
        == "agilab.pipeline_runtime"
    )


def test_data_quality_gate_modules_are_classified_or_entrypoints() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "src/agilab/apps/builtin/data_quality_gate_project/src/data_quality_gate"
    )
    _assert_package_modules_are_classified(root, "data_quality_gate")
