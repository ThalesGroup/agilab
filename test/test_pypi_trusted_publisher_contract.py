from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "pypi_trusted_publisher_contract.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

from package_split_contract import PACKAGE_CONTRACTS, PACKAGE_NAMES


def _load_module():
    spec = importlib.util.spec_from_file_location("pypi_trusted_publisher_contract", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_trusted_publisher_claims_match_package_split_contract() -> None:
    module = _load_module()
    claims = module.trusted_publisher_claims()

    assert [claim.project for claim in claims] == list(PACKAGE_NAMES)
    assert [claim.environment for claim in claims] == [
        package.pypi_environment for package in PACKAGE_CONTRACTS
    ]
    for claim in claims:
        assert claim.owner == "ThalesGroup"
        assert claim.repository == "agilab"
        assert claim.workflow == "pypi-publish.yaml"
        assert claim.subject == f"repo:ThalesGroup/agilab:environment:{claim.environment}"


def test_markdown_report_explains_invalid_publisher_and_setup_path() -> None:
    module = _load_module()
    markdown = module.format_markdown(module.trusted_publisher_claims(package_names=["agi-apps"]))

    assert "PyPI Trusted Publishing contract" in markdown
    assert "`agi-apps`" in markdown
    assert "`pypi-agi-apps`" in markdown
    assert "`repo:ThalesGroup/agilab:environment:pypi-agi-apps`" in markdown
    assert "`invalid-publisher`" in markdown
    assert "Settings > Publishing > Trusted publishers" in markdown


def test_json_report_is_machine_readable() -> None:
    module = _load_module()
    payload = json.loads(module.format_json(module.trusted_publisher_claims(package_names=["agilab"])))

    assert payload == [
        {
            "environment": "pypi-agilab",
            "owner": "ThalesGroup",
            "project": "agilab",
            "repository": "agilab",
            "subject": "repo:ThalesGroup/agilab:environment:pypi-agilab",
            "workflow": "pypi-publish.yaml",
        }
    ]


def test_workflow_contract_validation_covers_release_publish_matrix() -> None:
    module = _load_module()
    missing = module.validate_workflow_contract(
        REPO_ROOT / ".github/workflows/pypi-publish.yaml",
        module.trusted_publisher_claims(),
    )

    assert missing == []


def test_docs_list_every_required_trusted_publisher_environment() -> None:
    docs = (REPO_ROOT / "docs/source/package-publishing-policy.rst").read_text(encoding="utf-8")

    assert "invalid-publisher" in docs
    assert "repo:ThalesGroup/agilab:environment:<environment>" in docs
    for package in PACKAGE_CONTRACTS:
        assert f"``{package.name}``" in docs
        assert f"``{package.pypi_environment}``" in docs
