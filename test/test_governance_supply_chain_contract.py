from __future__ import annotations

from pathlib import Path


DEPENDABOT = Path(".github/dependabot.yml")
PR_TEMPLATE = Path(".github/PULL_REQUEST_TEMPLATE.md")
CONTRIBUTING = Path("CONTRIBUTING.md")
README = Path("README.md")
PYPI_README = Path("README.pypi.md")


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
    ):
        assert fragment in contributing

    for fragment in (
        "DCO/CLA status",
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
        ):
            assert fragment in text
