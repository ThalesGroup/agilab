from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "agenticweb_manifest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agenticweb_manifest_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(path: Path) -> None:
    payload = {
        "generated_at_utc": "2026-05-31T12:00:00Z",
        "schema": "agilab.capabilities.v1",
        "source": {"version": "2026.05.31"},
        "cli_commands": [
            {
                "id": "first-proof",
                "description": "Run the packaged first proof and emit install/run evidence.",
            },
            {
                "id": "workflow-validate",
                "description": "Validate stage contracts without executing user code.",
            },
            {
                "id": "agent-run",
                "description": "Wrap coding-agent actions with redacted manifests.",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_agenticweb_manifest_builds_compact_discovery_from_capabilities(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = tmp_path / "agilab-capabilities.json"
    _write_manifest(manifest_path)

    payload = module.build_discovery(manifest_path)

    assert payload["agenticweb"] == "1"
    assert payload["updated"] == "2026-05-31"
    assert payload["organization"]["name"] == "AGILAB"
    assert payload["x_generated_by"]["schema"] == "agilab.agenticweb_discovery.v1"
    assert payload["x_generated_by"]["source_manifest"].endswith("agilab-capabilities.json")
    by_id = {item["id"]: item for item in payload["capabilities"]}
    assert by_id["capability-manifest"]["kind"] == "data"
    assert by_id["read-only-evidence"]["kind"] == "mcp"
    assert by_id["streamlit-demo"]["kind"] == "ui"
    assert by_id["first-proof-cli"]["permissions"]["execute"] is True
    assert by_id["capability-map"]["permissions"]["train"] is False


def test_agenticweb_manifest_render_and_check(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = tmp_path / "agilab-capabilities.json"
    output_path = tmp_path / "agenticweb.md"
    _write_manifest(manifest_path)

    content = module.generate_output(manifest_path)
    changed = module.write_output(output_path, content)

    assert changed is True
    assert module.check_output(output_path, manifest_path) is True
    text = output_path.read_text(encoding="utf-8")
    assert text.startswith("---\nagenticweb: \"1\"")
    assert "agilab-capabilities.json" in text
    assert "python3 tools/agenticweb_manifest.py --check" in text


def test_real_agenticweb_manifest_is_current() -> None:
    module = _load_module()

    assert module.check_output(module.DEFAULT_OUTPUT, module.DEFAULT_CAPABILITIES)
