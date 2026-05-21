from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/ui_robot_failure_replay.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_failure_replay_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_failure_replay_loads_bundle_directory_and_prints_command(tmp_path, capsys) -> None:
    module = _load_module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "agilab.widget_robot_failure_bundle.v1",
                "command": ["python", "tools/agilab_widget_robot.py", "--json"],
            }
        ),
        encoding="utf-8",
    )

    exit_code = module.main([str(bundle), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == module.SCHEMA
    assert payload["command"] == ["python", "tools/agilab_widget_robot.py", "--json"]
    assert payload["shell_command"] == "python tools/agilab_widget_robot.py --json"
    assert payload["executed"] is False


def test_failure_replay_rejects_unknown_schema(tmp_path) -> None:
    module = _load_module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": "unknown", "command": ["true"]}), encoding="utf-8")

    try:
        module.load_manifest(manifest)
    except SystemExit as exc:
        assert "Unsupported failure bundle schema" in str(exc)
    else:
        raise AssertionError("expected unsupported schema to fail")
