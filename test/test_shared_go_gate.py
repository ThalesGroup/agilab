from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "shared_go_gate.py"
SPEC = importlib.util.spec_from_file_location("agilab_shared_go_gate", TOOL_PATH)
assert SPEC and SPEC.loader
shared_go_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shared_go_gate
SPEC.loader.exec_module(shared_go_gate)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_shared_go_gate_passes_with_clean_security_and_fresh_profile_artifacts(tmp_path: Path):
    security_check = tmp_path / "security-check.json"
    supply_chain = tmp_path / "supply-chain"
    _write_json(
        security_check,
        {
            "schema": "agilab.security_check.v1",
            "status": "pass",
            "summary": {"profile": "shared", "warnings": 0, "failures": 0},
        },
    )
    _write_json(supply_chain / "base" / "pip-audit.json", {"dependencies": []})
    _write_json(supply_chain / "base" / "sbom-cyclonedx.json", {"components": []})

    gate = shared_go_gate.build_gate(
        security_check_json=security_check,
        supply_chain_dir=supply_chain,
        install_profiles=("base",),
        now=datetime.now(timezone.utc),
    )

    assert gate["schema"] == shared_go_gate.SCHEMA
    assert gate["decision"] == "go"
    assert gate["checks"]["security_check"]["status"] == "pass"
    assert gate["checks"]["supply_chain"]["profiles"]["base"]["status"] == "pass"


def test_shared_go_gate_blocks_missing_supply_chain_and_strict_cli_returns_nonzero(tmp_path: Path):
    security_check = tmp_path / "security-check.json"
    output = tmp_path / "shared_go_gate.json"
    _write_json(
        security_check,
        {
            "schema": "agilab.security_check.v1",
            "status": "pass",
            "summary": {"profile": "shared", "warnings": 0, "failures": 0},
        },
    )

    rc = shared_go_gate.main(
        [
            "--security-check-json",
            str(security_check),
            "--supply-chain-dir",
            str(tmp_path / "missing-supply-chain"),
            "--output",
            str(output),
            "--strict",
        ]
    )

    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision"] == "blocked"
    assert payload["summary"]["failed_checks"] == ["supply_chain"]
