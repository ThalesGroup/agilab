from __future__ import annotations

from pathlib import Path


DOCS_SOURCE = Path("docs/source")
CAPABILITY_MAP = DOCS_SOURCE / "capability-map.rst"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_capability_map_is_discoverable_from_public_entry_points() -> None:
    index = _read(DOCS_SOURCE / "index.rst")
    readme = _read(Path("README.md"))
    pypi_readme = _read(Path("README.pypi.md"))
    features = _read(DOCS_SOURCE / "features.rst")

    assert "Capability map <capability-map>" in index
    assert "Capability map](https://thalesgroup.github.io/agilab/capability-map.html)" in readme
    assert "Capability map](https://thalesgroup.github.io/agilab/capability-map.html)" in pypi_readme
    assert ":doc:`capability-map`" in features
    assert "agilab-capabilities.json" in readme
    assert "agilab-capabilities.schema.json" in readme
    assert "agilab-capability-rules.yml" in readme
    assert "agilab-capabilities.json" in pypi_readme
    assert "agilab-capabilities.schema.json" in pypi_readme
    assert "agilab-capability-rules.yml" in pypi_readme


def test_capability_map_routes_features_by_user_job_evidence_and_boundary() -> None:
    page = _read(CAPABILITY_MAP)

    for heading in (
        "Maturity labels",
        "Job-to-route map",
        "Evidence Core reading order",
        "Adoption rule",
    ):
        assert heading in page

    for label in (
        "Live product path",
        "Local proof",
        "Contract proof",
        "Operator-triggered live check",
        "Roadmap boundary",
    ):
        assert label in page

    for route in (
        ":doc:`quick-start`",
        ":doc:`notebook-quickstart`",
        ":doc:`notebook-migration-skforecast-meteo`",
        ":doc:`proof-capsule`",
        ":doc:`data-connectors`",
        ":doc:`regulatory-readiness`",
        ":doc:`public-app-catalog`",
        ":doc:`release-proof`",
    ):
        assert route in page

    for evidence in (
        "``run_manifest.json``",
        "``lab_stages.toml``",
        "``agilab prove``",
        "``agilab.regulatory_readiness.v1``",
        "``.agipack``",
        "SBOM",
        "``pip-audit``",
    ):
        assert evidence in page

    assert "Use the lowest maturity level that proves the question" in page
    assert "Do not present it as current capability" in page
    assert "agilab-capabilities.json" in page
    assert "tools/agilab_capabilities_manifest.py --apply" in page
    assert "agilab-capabilities.schema.json" in page
    assert "agilab-capability-rules.yml" in page
    assert "tools/agilab_capabilities_lint.py --check" in page
    assert "cross-object" in page
    assert "runtime validation" in page
    assert "certification evidence" in page


def test_data_connector_docs_explain_live_contract_and_local_proof_levels() -> None:
    page = _read(DOCS_SOURCE / "data-connectors.rst")

    assert "Connector Maturity Levels" in page
    assert ".. _sqlite-database-proof:" in page
    assert "Local proof" in page
    assert "Contract proof" in page
    assert "Emulator proof" in page
    assert "Operator-triggered live check" in page
    assert "Real endpoint reachability, IAM, firewall rules, quota, latency, or" in page
    assert "General certification for every region, tenant, credential, or network" in page
