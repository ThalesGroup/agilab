from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "agilab_capabilities_manifest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_capabilities_manifest_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_capability_manifest_exposes_public_surfaces() -> None:
    module = _load_module()
    payload = module.build_manifest(output_path=module.DEFAULT_OUTPUT)

    assert payload["schema"] == "agilab.capabilities.v1"
    assert payload["schema_version"] == 1
    assert payload["boundary"]["does_not_prove"].startswith("It does not prove runtime success")

    commands = {row["id"]: row for row in payload["cli_commands"]}
    assert commands["first-proof"]["evidence_outputs"] == ["run_manifest.json"]
    assert "agilab workflow validate" in commands["workflow-validate"]["command"]
    assert "[--profile agilab]" in commands["agent-context-router"]["command"]
    assert "optional scoped context profile" in commands["agent-context-router"]["description"]

    pages = {row["title"]: row for row in payload["streamlit_pages"]}
    assert pages["ORCHESTRATE"]["source"] == "src/agilab/pages/2_ORCHESTRATE.py"
    assert pages["ANALYSIS"]["visible_in_nav"] is True

    packages = {row["name"]: row for row in payload["packages"]}
    assert packages["agilab"]["role"] == "top-level-bundle"
    assert packages["agi-app-flight-telemetry"]["status"] == "PyPI app package"

    apps = {row["project"]: row for row in payload["public_apps"]}
    assert apps["flight_telemetry_project"]["package"] == "agi-app-flight-telemetry"
    assert apps["minimal_app_project"]["status"] == "Source built-in"

    schemas = {row["schema"] for row in payload["evidence_schemas"]}
    assert "agilab.workflow_dry_run_report.v1" in schemas
    assert "agilab.notebook_export_manifest.v1" in schemas

    catalogs = {row["path"]: row for row in payload["catalog_files"]}
    assert catalogs["AGENT_SKILLS.md"]["exists"] is True
    assert catalogs["AGENTS.md"]["kind"] == "agent-runbook"
    assert catalogs["AGENT_CONVENTIONS.md"]["kind"] == "agent-runbook"
    assert catalogs["AGENT_LEARNINGS.md"]["kind"] == "agent-correction-ledger"
    assert catalogs["tools/agent_workflows.md"]["kind"] == "agent-workflow-runbook"
    assert catalogs["agenticweb.md"]["kind"] == "agenticweb-discovery"
    assert catalogs["agilab-capabilities.json"]["kind"] == "capability-manifest"
    assert catalogs["agilab-capabilities.schema.json"]["kind"] == "capability-schema"
    assert catalogs["agilab-capability-rules.yml"]["kind"] == "capability-rules"

    assert commands["agenticweb-manifest"]["evidence_outputs"] == ["agilab.agenticweb_discovery.v1"]
    assert commands["agent-instruction-contract"]["evidence_outputs"] == [
        "agilab.agent_instruction_contract.v1"
    ]
    assert commands["data-artifact-lane-contract"]["evidence_outputs"] == [
        "agilab.data_artifact_lane_contract.v1"
    ]
    assert commands["regulatory-readiness-report"]["evidence_outputs"] == [
        "agilab.regulatory_readiness.v1"
    ]


def test_schema_scan_excludes_gitignored_workspace_artifacts(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    tracked = tmp_path / "tracked.py"
    ignored = tmp_path / "lab_stages.notebook_export.json"
    tracked.write_text('SCHEMA = "agilab.tracked_evidence.v1"\n', encoding="utf-8")
    ignored.write_text(
        '{"schema": "agilab.ignored_workspace_artifact.v1"}\n',
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "lab_stages.notebook_export.json\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "add", ".gitignore", tracked.name],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "SCHEMA_SCAN_ROOTS", (tmp_path,))
    monkeypatch.setattr(module, "SCHEMA_SCAN_FILES", ())

    schemas = {row["schema"] for row in module.collect_evidence_schemas()}

    assert "agilab.tracked_evidence.v1" in schemas
    assert "agilab.ignored_workspace_artifact.v1" not in schemas


def test_schema_scan_fails_closed_when_git_inventory_fails(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"fatal: inventory unavailable",
        ),
    )

    with pytest.raises(RuntimeError, match="inventory unavailable"):
        module._git_visible_paths()


def test_schema_scan_without_git_metadata_uses_source_tree_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("Git must not be called for a source tree without .git")

    monkeypatch.setattr(module.subprocess, "run", unexpected_run)

    assert module._git_visible_paths() is None


def test_checked_in_capability_manifest_is_current() -> None:
    module = _load_module()

    assert module.check_manifest(module.DEFAULT_OUTPUT)


def test_capability_manifest_is_valid_json() -> None:
    payload = json.loads((REPO_ROOT / "agilab-capabilities.json").read_text(encoding="utf-8"))

    assert payload["summary"]["cli_command_count"] == len(payload["cli_commands"])
    assert payload["summary"]["public_app_count"] == len(payload["public_apps"])
    assert payload["generated_by"]["command"] == "python3 tools/agilab_capabilities_manifest.py --apply"
