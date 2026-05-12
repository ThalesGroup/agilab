from __future__ import annotations

from pathlib import Path
import tomllib


DEPENDABOT = Path(".github/dependabot.yml")
PR_TEMPLATE = Path(".github/PULL_REQUEST_TEMPLATE.md")
CONTRIBUTING = Path("CONTRIBUTING.md")
README = Path("README.md")
PYPI_README = Path("README.pypi.md")
PYPROJECT = Path("pyproject.toml")


def test_dependabot_visibility_covers_python_and_github_actions() -> None:
    text = DEPENDABOT.read_text(encoding="utf-8")

    assert 'package-ecosystem: "github-actions"' in text
    assert text.count('package-ecosystem: "pip"') >= 6
    assert 'directory: "/"' in text
    assert 'directory: "/src/agilab/core/agi-env"' in text
    assert 'directory: "/src/agilab/core/agi-node"' in text
    assert 'directory: "/src/agilab/core/agi-cluster"' in text
    assert 'directory: "/src/agilab/core/agi-core"' in text
    assert 'directory: "/src/agilab/lib/agi-gui"' in text
    assert 'interval: "weekly"' in text


def test_contributing_documents_enterprise_governance_boundaries() -> None:
    contributing = CONTRIBUTING.read_text(encoding="utf-8")
    template = PR_TEMPLATE.read_text(encoding="utf-8")

    for fragment in (
        "Developer Certificate of Origin 1.1",
        "no separate contributor license agreement is required",
        "Review policy: every pull request needs maintainer review",
        "Branch protection: `main`, release tags, and publication workflows are maintainer-owned",
        "Release ownership: only maintainers should create release tags",
        "Security Checklist",
        "External App Acceptance",
        "SBOM / `pip-audit` evidence",
        "State the stability boundary",
        "Keep repository-scope changes explicit",
    ):
        assert fragment in contributing

    for fragment in (
        "Stability boundary: runtime core / beta UI / built-in app / learning example / release tooling / agent or IDE automation",
        "DCO/CLA status",
        "Repository-scope changes stay within the stated stability boundary",
        "Security checklist considered",
        "SBOM / `pip-audit` evidence",
        "External app/example changes meet the public acceptance criteria",
    ):
        assert fragment in template


def test_readmes_explain_production_dependency_and_evidence_boundaries() -> None:
    for path in (README, PYPI_README):
        text = path.read_text(encoding="utf-8")
        for fragment in (
            "## Production Boundary",
            "Safe for production-like use",
            "Conditional use only",
            "Not safe as-is",
            "Sole production MLOps control plane",
            "## Dependency And Supply-Chain Boundaries",
            "Cluster/Dask dependencies are currently part of the base package",
            "Dependabot watches",
            "CycloneDX SBOM artifacts",
            "tools/profile_supply_chain_scan.py",
            "## Evidence Taxonomy",
            "Automated proof",
            "Integration tests",
            "Benchmarks",
            "Self-assessment",
            "External validation",
            "Independent certification",
            "## Repository Map And Stability Boundaries",
            "Runtime packages",
            "Beta product surface",
            "Packaged examples",
            "Maintainer tooling, not runtime API",
        ):
            assert fragment in text


def test_readmes_document_package_surface_contract() -> None:
    for path in (README, PYPI_README):
        text = path.read_text(encoding="utf-8")
        for fragment in (
            "Local source checkouts can grow after runs",
            "not the package contract",
            "exclude virtual environments",
            "tests, `docs/html`, build directories",
            "generated C files",
            "`__pycache__`, `.pyc`",
            "`.egg-info` artifacts",
        ):
            assert fragment in text


def test_pyproject_keeps_local_artifacts_out_of_package_surface() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    setuptools_config = pyproject["tool"]["setuptools"]
    find_config = setuptools_config["packages"]["find"]
    package_data = setuptools_config["package-data"]["agilab"]
    exclude_data = setuptools_config["exclude-package-data"]["agilab"]

    assert setuptools_config["include-package-data"] is False
    assert ".venv*" in find_config["exclude"]
    assert "test*" in find_config["exclude"]
    assert "build*" in find_config["exclude"]
    assert not any(".venv" in pattern for pattern in package_data)
    assert not any("docs/html" in pattern for pattern in package_data)
    assert "apps/builtin/*/src/*/*.c" in exclude_data
    assert "apps/builtin/*/src/*.pyc" in exclude_data
    assert "apps/builtin/*/src/*/*.egg-info/*" in exclude_data
