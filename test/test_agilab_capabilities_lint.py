from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_MODULE_PATH = REPO_ROOT / "tools" / "agilab_capabilities_manifest.py"
LINT_MODULE_PATH = REPO_ROOT / "tools" / "agilab_capabilities_lint.py"
SCHEMA_PATH = REPO_ROOT / "agilab-capabilities.schema.json"
RULES_PATH = REPO_ROOT / "agilab-capability-rules.yml"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest_module():
    return _load_module(MANIFEST_MODULE_PATH, "agilab_capability_manifest_lint_test_module")


def _lint_module():
    return _load_module(LINT_MODULE_PATH, "agilab_capability_lint_test_module")


def _schema_payload() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _rules_payload() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def test_capability_schema_contract_targets_manifest_shape() -> None:
    schema = _schema_payload()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema"]["const"] == "agilab.capabilities.v1"
    assert schema["properties"]["schema_version"]["const"] == 1
    assert "cli_commands" in schema["required"]
    assert "PublicApp" in schema["$defs"]
    assert "EvidenceSchema" in schema["$defs"]


def test_capability_lint_passes_for_checked_in_manifest() -> None:
    lint = _lint_module()

    report = lint.lint_files(lint.DEFAULT_MANIFEST, lint.DEFAULT_SCHEMA)

    assert report["schema"] == "agilab.capabilities_lint.v1"
    assert report["status"] == "pass"
    assert report["rules_file"] == "agilab-capability-rules.yml"
    assert report["summary"] == {"issue_count": 0, "error_count": 0, "warning_count": 0, "rule_count": 60}


def test_capability_rules_catalog_declares_profiles_and_metadata() -> None:
    rules = _rules_payload()

    assert rules["schema"] == "agilab.capability_rules.v1"
    assert rules["schema_version"] == 1
    assert "governance" in rules["profiles"]
    assert "ai-safety" in rules["profiles"]
    assert "security" in rules["profiles"]
    rule_ids = {row["id"] for row in rules["rules"]}
    assert "summary-count" in rule_ids
    assert "rules-catalog-missing-rule" in rule_ids


def test_capability_lint_detects_summary_drift() -> None:
    manifest = _manifest_module().build_manifest(output_path=REPO_ROOT / "agilab-capabilities.json")
    lint = _lint_module()
    mutated = lint.mutated_manifest(manifest, "summary", "public_app_count", value=999)

    report = lint.lint_manifest(mutated, _schema_payload(), _rules_payload())

    assert report["status"] == "fail"
    summary_issue = next(issue for issue in report["issues"] if issue["rule"] == "summary-count")
    assert summary_issue["category"] == "summary-contract"
    assert summary_issue["title"] == "Summary counts match manifest rows"


def test_capability_lint_detects_missing_doc_path() -> None:
    manifest = _manifest_module().build_manifest(output_path=REPO_ROOT / "agilab-capabilities.json")
    lint = _lint_module()
    mutated = lint.mutated_manifest(
        manifest,
        "cli_commands",
        "0",
        "docs",
        "0",
        value="docs/source/does-not-exist.rst",
    )

    report = lint.lint_manifest(mutated, _schema_payload(), _rules_payload())

    assert report["status"] == "fail"
    assert any(issue["rule"] == "doc-path-exists" for issue in report["issues"])


def test_capability_lint_detects_unknown_public_app_package() -> None:
    manifest = _manifest_module().build_manifest(output_path=REPO_ROOT / "agilab-capabilities.json")
    lint = _lint_module()
    mutated = lint.mutated_manifest(
        manifest,
        "public_apps",
        "0",
        "package",
        value="agi-app-does-not-exist",
    )

    report = lint.lint_manifest(mutated, _schema_payload(), _rules_payload())

    assert report["status"] == "fail"
    assert any(issue["rule"] == "public-app-package-known" for issue in report["issues"])


def test_capability_lint_detects_rules_catalog_drift() -> None:
    manifest = _manifest_module().build_manifest(output_path=REPO_ROOT / "agilab-capabilities.json")
    lint = _lint_module()
    rules = lint.mutated_manifest(_rules_payload(), "rules", "0", "id", value="stale-renamed-rule")

    report = lint.lint_manifest(manifest, _schema_payload(), rules)

    assert report["status"] == "fail"
    assert any(issue["rule"] == "rules-catalog-missing-rule" for issue in report["issues"])
    assert any(issue["rule"] == "rules-catalog-stale-rule" for issue in report["issues"])
