from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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


def test_checked_in_capability_manifest_is_current() -> None:
    module = _load_module()

    assert module.check_manifest(module.DEFAULT_OUTPUT)


def test_capability_manifest_is_valid_json() -> None:
    payload = json.loads((REPO_ROOT / "agilab-capabilities.json").read_text(encoding="utf-8"))

    assert payload["summary"]["cli_command_count"] == len(payload["cli_commands"])
    assert payload["summary"]["public_app_count"] == len(payload["public_apps"])
    assert payload["generated_by"]["command"] == "python3 tools/agilab_capabilities_manifest.py --apply"
