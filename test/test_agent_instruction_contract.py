from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "agent_instruction_contract.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_instruction_contract_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_minimal_contract_tree(module, root: Path) -> None:
    for contract in module.CONTRACTS:
        path = root / contract.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(term.text for term in contract.required_terms) + "\n", encoding="utf-8")
    catalog_paths = [{"path": path, "kind": "test", "description": "test"} for path in module.CATALOG_PATHS]
    payload = {
        "cli_commands": [
            {
                "id": module.CAPABILITY_COMMAND_ID,
                "command": "python3 tools/agent_instruction_contract.py --check",
                "docs": ["docs/source/agent-workflows.rst"],
                "evidence_outputs": [module.SCHEMA],
            }
        ],
        "catalog_files": catalog_paths,
    }
    (root / "agilab-capabilities.json").write_text(json.dumps(payload), encoding="utf-8")


def test_current_agent_instruction_contract_passes() -> None:
    module = _load_module()

    report = module.build_report(REPO_ROOT)

    assert report["schema"] == module.SCHEMA
    assert report["status"] == "pass"
    assert report["summary"]["error_count"] == 0


def test_contract_detects_missing_root_runbook_marker(tmp_path: Path) -> None:
    module = _load_module()
    _write_minimal_contract_tree(module, tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8").replace("No silent fallbacks", ""), encoding="utf-8")

    report = module.build_report(tmp_path)

    assert report["status"] == "fail"
    assert any(
        issue["rule"] == "agent-instruction-required-term"
        and issue["path"] == "AGENTS.md"
        and "no-fallbacks" in issue["message"]
        for issue in report["issues"]
    )


def test_contract_detects_missing_capability_command(tmp_path: Path) -> None:
    module = _load_module()
    _write_minimal_contract_tree(module, tmp_path)
    payload = json.loads((tmp_path / "agilab-capabilities.json").read_text(encoding="utf-8"))
    payload["cli_commands"] = []
    (tmp_path / "agilab-capabilities.json").write_text(json.dumps(payload), encoding="utf-8")

    report = module.build_report(tmp_path)

    assert report["status"] == "fail"
    assert any(issue["rule"] == "agent-instruction-capability-command" for issue in report["issues"])
