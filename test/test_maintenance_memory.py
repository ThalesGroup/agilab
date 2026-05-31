from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/maintenance_memory.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("maintenance_memory_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_note(module, memory_root: Path, source: str, sha256: str) -> Path:
    note = module.memory_note_path(source, memory_root=memory_root)
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        "schema: agilab.maintenance_memory.v1\n"
        f"source: {source}\n"
        f"source_sha256: {sha256}\n"
        "title: Demo invariant\n"
        "---\n\n"
        "# Demo invariant\n\n"
        "Keep the hidden contract visible to agents.\n",
        encoding="utf-8",
    )
    return note


def test_maintenance_memory_check_reports_up_to_date_and_drift(tmp_path: Path) -> None:
    module = _load_module()
    source = "src/demo.py"
    source_path = tmp_path / source
    source_path.parent.mkdir(parents=True)
    source_path.write_text("VALUE = 1\n", encoding="utf-8")
    sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    memory_root = tmp_path / "maintenance" / "memory"
    _write_note(module, memory_root, source, sha256)

    [current] = module.check_sources([source], repo_root=tmp_path, memory_root=memory_root)

    assert current.status == "up-to-date"
    assert current.title == "Demo invariant"

    source_path.write_text("VALUE = 2\n", encoding="utf-8")
    [drifted] = module.check_sources([source], repo_root=tmp_path, memory_root=memory_root)

    assert drifted.status == "drifted"
    assert drifted.expected_sha256 == sha256
    assert drifted.actual_sha256 != sha256


def test_maintenance_memory_main_json_all_checks_seeded_notes(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["check", "--all", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agilab.maintenance_memory.check.v1"
    assert payload["success"] is True
    sources = {check["source"] for check in payload["checks"]}
    assert "src/agilab/pages/4_ANALYSIS.py" in sources
    assert (
        "src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py"
        in sources
    )
