from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_root_base_dependencies_do_not_own_app_or_example_stacks() -> None:
    deps = _dependency_names(REPO_ROOT / "pyproject.toml")

    app_or_example_owned = {
        "asyncssh",
        "fastparquet",
        "geojson",
        "geopy",
        "humanize",
        "jupyter-ai",
        "keras",
        "matplotlib",
        "noise",
        "numba",
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
        "tomli",
    }
    assert deps.isdisjoint(app_or_example_owned)

    # These are imported directly by the packaged AGILAB UI/runtime layer.
    assert {"pandas", "pydantic", "streamlit"} <= deps
    assert "networkx" in deps


def test_root_optional_extras_own_ai_and_visualization_stacks() -> None:
    pyproject = REPO_ROOT / "pyproject.toml"

    assert _optional_dependency_names(pyproject, "ai") == {"openai"}
    assert {"matplotlib", "plotly"} <= _optional_dependency_names(pyproject, "viz")


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
        assert {"agi-env", "agi-node"} <= deps, app_root.name

        sources = data.get("tool", {}).get("uv", {}).get("sources", {})
        for package in ("agi-env", "agi-node"):
            raw_path = sources.get(package, {}).get("path")
            assert raw_path, f"{app_root.name}: missing local source for {package}"
            assert (app_root / raw_path).resolve(strict=False).exists()


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


def test_app_templates_keep_dependency_lists_app_local() -> None:
    template_roots = sorted((REPO_ROOT / "src/agilab/apps/templates").glob("*_template"))
    assert template_roots

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

    for template_root in template_roots:
        deps = _dependency_names(template_root / "pyproject.toml")
        assert deps.isdisjoint(stale_template_deps), template_root.name
        assert {"pydantic", "streamlit"} <= deps, template_root.name


def test_non_core_app_manifests_avoid_exact_pins_except_known_runtime_caps() -> None:
    app_pyprojects = [
        *(REPO_ROOT / "src/agilab/apps-pages").glob("*/pyproject.toml"),
        *(REPO_ROOT / "src/agilab/apps/builtin").glob("*_project/pyproject.toml"),
        *(REPO_ROOT / "src/agilab/apps/templates").glob("*_template/pyproject.toml"),
    ]
    allowed_exact_pins = {
        "src/agilab/apps-pages/view_autoencoder_latenspace/pyproject.toml": {"tensorflow"},
    }

    violations: list[str] = []
    for pyproject in sorted(app_pyprojects):
        data = _load_pyproject(pyproject)
        relative_path = pyproject.relative_to(REPO_ROOT).as_posix()
        allowed = allowed_exact_pins.get(relative_path, set())
        for dependency in data.get("project", {}).get("dependencies", []):
            requirement = Requirement(dependency)
            if requirement.name.lower() in allowed:
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
