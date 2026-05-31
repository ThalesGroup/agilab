from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_MODULE_PATH = REPO_ROOT / "tools" / "agilab_capabilities_manifest.py"
LINT_MODULE_PATH = REPO_ROOT / "tools" / "agilab_capabilities_lint.py"
SCHEMA_PATH = REPO_ROOT / "agilab-capabilities.schema.json"


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
    assert report["summary"] == {"issue_count": 0, "error_count": 0, "warning_count": 0}


def test_capability_lint_detects_summary_drift() -> None:
    manifest = _manifest_module().build_manifest(output_path=REPO_ROOT / "agilab-capabilities.json")
    lint = _lint_module()
    mutated = lint.mutated_manifest(manifest, "summary", "public_app_count", value=999)

    report = lint.lint_manifest(mutated, _schema_payload())

    assert report["status"] == "fail"
    assert any(issue["rule"] == "summary-count" for issue in report["issues"])


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

    report = lint.lint_manifest(mutated, _schema_payload())

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

    report = lint.lint_manifest(mutated, _schema_payload())

    assert report["status"] == "fail"
    assert any(issue["rule"] == "public-app-package-known" for issue in report["issues"])
