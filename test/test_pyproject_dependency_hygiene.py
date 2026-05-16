from __future__ import annotations

import tomllib
from pathlib import Path
import sys

from packaging.markers import default_environment
from packaging.requirements import Requirement


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
TOOLS_ROOT = REPO_ROOT / "tools"
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(TOOLS_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agilab.app_template_registry import discover_app_templates
from package_split_contract import PACKAGE_NAMES, ROOT_EXTRA_INTERNAL_REQUIREMENTS


def _load_pyproject(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _dependency_names(path: Path) -> set[str]:
    data = _load_pyproject(path)
    dependencies = data.get("project", {}).get("dependencies", [])
    return {Requirement(dependency).name.lower() for dependency in dependencies}


def _dependencies(path: Path) -> list[Requirement]:
    data = _load_pyproject(path)
    return [Requirement(dependency) for dependency in data.get("project", {}).get("dependencies", [])]


def _optional_dependency_names(path: Path, extra: str) -> set[str]:
    data = _load_pyproject(path)
    dependencies = data.get("project", {}).get("optional-dependencies", {}).get(extra, [])
    return {Requirement(dependency).name.lower() for dependency in dependencies}


def _optional_dependencies(path: Path, extra: str) -> list[Requirement]:
    data = _load_pyproject(path)
    return [Requirement(dependency) for dependency in data.get("project", {}).get("optional-dependencies", {}).get(extra, [])]


def _has_version_floor(requirement: Requirement) -> bool:
    return any(spec.operator in {">=", "~=", "=="} for spec in requirement.specifier)


def test_root_base_dependencies_do_not_own_app_or_example_stacks() -> None:
    deps = _dependency_names(REPO_ROOT / "pyproject.toml")

    app_or_example_owned = {
        *{
            package
            for extra, packages in ROOT_EXTRA_INTERNAL_REQUIREMENTS.items()
            if extra != "dependencies"
            for package in packages
        },
        "asyncssh",
        "fastparquet",
        "geojson",
        "geopy",
        "humanize",
        "jupyter-ai",
        "jupyterlab",
        "keras",
        "matplotlib",
        "mlflow",
        "mlx",
        "mlx-lm",
        "noise",
        "numba",
        "networkx",
        "openai",
        "plotly",
        "polars",
        "pulp",
        "py7zr",
        "scipy",
        "seaborn",
        "sgp4",
        "simpy",
        "skforecast",
        "streamlit",
        "tomli",
        "tomli_w",
    }
    assert deps.isdisjoint(app_or_example_owned)

    # The default package keeps only the core runtime and tiny stdlib shims.
    assert "agi-core" in deps


def test_root_runtime_dependencies_have_explicit_version_policy() -> None:
    pyproject = REPO_ROOT / "pyproject.toml"
    internal_exact_pins = {"agi-core"}
    violations: list[str] = []

    for requirement in _dependencies(pyproject):
        name = requirement.name.lower()
        if name in internal_exact_pins:
            if not any(spec.operator == "==" for spec in requirement.specifier):
                violations.append(f"{requirement}: internal package must be exactly pinned")
            continue
        if not _has_version_floor(requirement):
            violations.append(f"{requirement}: missing lower bound or compatible version floor")

    assert violations == []


def test_root_apple_silicon_dependencies_are_optional_and_platform_marked() -> None:
    root_requirements = {requirement.name.lower(): requirement for requirement in _dependencies(REPO_ROOT / "pyproject.toml")}
    assert {"mlx", "mlx-lm"}.isdisjoint(root_requirements)

    requirements = {
        requirement.name.lower(): requirement
        for requirement in _optional_dependencies(REPO_ROOT / "pyproject.toml", "local-llm")
    }

    windows_env = default_environment()
    windows_env.update(
        {
            "os_name": "nt",
            "platform_machine": "AMD64",
            "platform_system": "Windows",
            "sys_platform": "win32",
        }
    )
    linux_env = default_environment()
    linux_env.update(
        {
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_system": "Linux",
            "sys_platform": "linux",
        }
    )
    mac_arm_env = default_environment()
    mac_arm_env.update(
        {
            "os_name": "posix",
            "platform_machine": "arm64",
            "platform_system": "Darwin",
            "sys_platform": "darwin",
        }
    )

    for name in ("mlx", "mlx-lm"):
        requirement = requirements[name]
        assert requirement.marker is not None
        assert requirement.marker.evaluate(windows_env) is False
        assert requirement.marker.evaluate(linux_env) is False
        assert requirement.marker.evaluate(mac_arm_env) is True


def test_root_optional_extras_own_ai_and_visualization_stacks() -> None:
    pyproject = REPO_ROOT / "pyproject.toml"

    assert _optional_dependency_names(pyproject, "ai") == {"openai"}
    assert _optional_dependency_names(pyproject, "agents") == {"openai"}
    assert set(ROOT_EXTRA_INTERNAL_REQUIREMENTS["examples"]) | {"jupyterlab", "matplotlib", "plotly"} <= _optional_dependency_names(pyproject, "examples")
    assert _optional_dependency_names(pyproject, "pages") == set(ROOT_EXTRA_INTERNAL_REQUIREMENTS["pages"])
    assert {"matplotlib", "plotly"} <= _optional_dependency_names(pyproject, "viz")
    assert set(ROOT_EXTRA_INTERNAL_REQUIREMENTS["ui"]) | {"streamlit", "networkx", "pandas", "tomli_w"} <= _optional_dependency_names(pyproject, "ui")
    assert _optional_dependency_names(pyproject, "mlflow") == {"mlflow"}
    assert {"build", "pytest", "pytest-cov", "pip-audit", "cyclonedx-bom", "twine", "wheel"} <= _optional_dependency_names(
        pyproject, "dev"
    )
    assert {"gpt-oss", "mlx", "mlx-lm", "transformers", "torch"} <= _optional_dependency_names(
        pyproject, "local-llm"
    )
    assert _optional_dependency_names(pyproject, "offline") == _optional_dependency_names(pyproject, "local-llm")

    optional_dependencies = _load_pyproject(pyproject).get("project", {}).get("optional-dependencies", {})
    violations: list[str] = []
    for extra_name, dependencies in optional_dependencies.items():
        for dependency in dependencies:
            requirement = Requirement(dependency)
            if not _has_version_floor(requirement):
                violations.append(f"{extra_name}: {requirement}")

    assert violations == []


def test_builtin_app_manifests_depend_on_core_packages_not_core_internals() -> None:
    app_roots = sorted((REPO_ROOT / "src/agilab/apps/builtin").glob("*_project"))
    assert app_roots

    copied_core_internals = {
        "astor",
        "cython",
        "dask",
        "humanize",
        "msgpack",
        "numba",
        "parso",
        "pathspec",
        "psutil",
        "python-dotenv",
        "scipy",
        "setuptools",
        "tomli",
        "tomlkit",
        "typing-inspection",
        "wheel",
    }

    for app_root in app_roots:
        pyproject = app_root / "pyproject.toml"
        data = _load_pyproject(pyproject)
        deps = _dependency_names(pyproject)

        assert deps.isdisjoint(copied_core_internals), app_root.name
        assert {"agi-env", "agi-node", "agi-cluster"} <= deps, app_root.name

        sources = data.get("tool", {}).get("uv", {}).get("sources", {})
        for package in ("agi-env", "agi-node", "agi-cluster"):
            raw_path = sources.get(package, {}).get("path")
            assert raw_path, f"{app_root.name}: missing local source for {package}"
            assert (app_root / raw_path).resolve(strict=False).exists()


def test_builtin_worker_manifests_have_resolvable_core_sources() -> None:
    worker_pyprojects = sorted((REPO_ROOT / "src/agilab/apps/builtin").glob("*_project/src/*_worker/pyproject.toml"))
    assert worker_pyprojects
    core_worker_pyprojects: list[Path] = []

    for pyproject in worker_pyprojects:
        data = _load_pyproject(pyproject)
        deps = _dependency_names(pyproject)
        if deps.isdisjoint({"agi-env", "agi-node"}):
            continue
        core_worker_pyprojects.append(pyproject)
        assert {"agi-env", "agi-node"} <= deps, pyproject

        sources = data.get("tool", {}).get("uv", {}).get("sources", {})
        for package in ("agi-env", "agi-node"):
            raw_path = sources.get(package, {}).get("path")
            assert raw_path, f"{pyproject}: missing local source for {package}"
            assert (pyproject.parent / raw_path).resolve(strict=False).exists(), f"{pyproject}: {package} -> {raw_path}"

    assert core_worker_pyprojects


def test_shared_core_runtime_dependencies_are_not_copied_meta_stacks() -> None:
    stale_by_manifest = {
        "src/agilab/core/agi-env/pyproject.toml": {
            "humanize",
            "numba",
            "setuptools",
        },
        "src/agilab/core/agi-node/pyproject.toml": {
            "dask",
            "msgpack",
            "numba",
            "python-dotenv",
            "scikit-learn",
            "scipy",
            "tomli",
            "typing-inspection",
            "wheel",
        },
        "src/agilab/core/agi-cluster/pyproject.toml": {
            "astor",
            "cython",
            "jupyter",
            "msgpack",
            "mypy",
            "numba",
            "parso",
            "pathspec",
            "pydantic",
            "py7zr",
            "python-dotenv",
            "requests",
            "scipy",
            "setuptools",
            "tomli",
            "typing-inspection",
            "urllib3",
            "wheel",
        },
    }

    for relative_path, stale_names in stale_by_manifest.items():
        deps = _dependency_names(REPO_ROOT / relative_path)
        assert deps.isdisjoint(stale_names), relative_path

    assert {"agi-env", "cython", "humanize", "numpy", "pandas", "polars", "psutil"} <= _dependency_names(
        REPO_ROOT / "src/agilab/core/agi-node/pyproject.toml"
    )
    assert {
        "agi-env",
        "agi-node",
        "asyncssh",
        "dask",
        "humanize",
        "numpy",
        "packaging",
        "polars",
        "psutil",
        "scikit-learn",
        "tomlkit",
    } <= _dependency_names(REPO_ROOT / "src/agilab/core/agi-cluster/pyproject.toml")


def test_agi_gui_uses_native_streamlit_dialogs_and_declares_only_used_ui_runtime() -> None:
    deps = _dependency_names(REPO_ROOT / "src/agilab/lib/agi-gui/pyproject.toml")

    assert {"agi-env", "streamlit", "streamlit_code_editor", "watchdog"} <= deps
    assert deps.isdisjoint({"gitpython", "streamlit-modal", "streamlit_extras"})


def test_app_templates_keep_dependency_lists_app_local() -> None:
    templates = discover_app_templates(REPO_ROOT / "src/agilab/apps/templates").templates
    assert templates

    stale_template_deps = {
        "cython",
        "dask",
        "geopy",
        "humanize",
        "ipython",
        "numpy",
        "parso",
        "psutil",
        "python-dotenv",
        "requests",
        "setuptools",
    }

    for template in templates:
        deps = _dependency_names(template.pyproject_path)
        assert deps.isdisjoint(stale_template_deps), template.name
        assert {"pydantic", "streamlit"} <= deps, template.name


def test_non_core_app_manifests_avoid_exact_pins_except_known_runtime_caps() -> None:
    app_pyprojects = [
        *(REPO_ROOT / "src/agilab/apps-pages").glob("*/pyproject.toml"),
        *(REPO_ROOT / "src/agilab/apps/builtin").glob("*_project/pyproject.toml"),
        *(template.pyproject_path for template in discover_app_templates(REPO_ROOT / "src/agilab/apps/templates")),
    ]
    allowed_exact_pins = {
        "src/agilab/apps-pages/view_autoencoder_latenspace/pyproject.toml": {"tensorflow"},
    }
    internal_packages = {name.lower() for name in PACKAGE_NAMES}

    violations: list[str] = []
    for pyproject in sorted(app_pyprojects):
        data = _load_pyproject(pyproject)
        relative_path = pyproject.relative_to(REPO_ROOT).as_posix()
        allowed = allowed_exact_pins.get(relative_path, set())
        for dependency in data.get("project", {}).get("dependencies", []):
            requirement = Requirement(dependency)
            if requirement.name.lower() in allowed:
                continue
            if requirement.name.lower() in internal_packages:
                continue
            if any(spec.operator == "==" for spec in requirement.specifier):
                violations.append(f"{relative_path}: {dependency}")

    assert violations == []


def test_shared_core_third_party_dependencies_avoid_exact_runtime_pins() -> None:
    pyprojects = [
        REPO_ROOT / "src/agilab/core/agi-env/pyproject.toml",
        REPO_ROOT / "src/agilab/core/agi-node/pyproject.toml",
        REPO_ROOT / "src/agilab/core/agi-cluster/pyproject.toml",
    ]
    internal_packages = {"agi-env", "agi-node", "agi-cluster"}

    violations: list[str] = []
    for pyproject in pyprojects:
        relative_path = pyproject.relative_to(REPO_ROOT).as_posix()
        for requirement in _dependencies(pyproject):
            if requirement.name.lower() in internal_packages:
                continue
            if any(spec.operator == "==" for spec in requirement.specifier):
                violations.append(f"{relative_path}: {requirement}")

    assert violations == []
