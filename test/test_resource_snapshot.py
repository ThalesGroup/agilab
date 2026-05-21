from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/resource_snapshot.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("resource_snapshot_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_snapshot_contains_resource_evidence_contract(tmp_path: Path) -> None:
    module = _load_module()

    snapshot = module.build_snapshot(tmp_path)

    assert snapshot["schema"] == module.SCHEMA
    assert snapshot["workdir"] == str(tmp_path.resolve())
    assert snapshot["cpu"]["logical_cores"] is not None
    assert "available_gb" in snapshot["memory"]
    assert "available_backends" in snapshot["gpu"]
    assert snapshot["recommendations"]["parallel_processing"]["suggested_workers"] >= 1


def test_resource_snapshot_cli_writes_json(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "resource_snapshot.json"

    result = module.main(["--workdir", str(tmp_path), "--output", str(output), "--compact"])

    assert result == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == module.SCHEMA
    assert payload["recommendations"]["artifact_storage"]["strategy"]
