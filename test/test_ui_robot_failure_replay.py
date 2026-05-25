from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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


def test_failure_replay_rejects_unreadable_non_object_and_bad_command(tmp_path) -> None:
    module = _load_module()

    with pytest.raises(SystemExit, match="Could not read failure bundle manifest"):
        module.load_manifest(tmp_path / "missing-bundle")

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{not-json", encoding="utf-8")
    with pytest.raises(SystemExit, match="Could not read failure bundle manifest"):
        module.load_manifest(invalid_json)

    array_manifest = tmp_path / "array.json"
    array_manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a JSON object"):
        module.load_manifest(array_manifest)

    bad_command = tmp_path / "bad-command.json"
    bad_command.write_text(
        json.dumps({"schema": "agilab.widget_robot_failure_bundle.v1", "command": "python -m test"}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="does not contain a string command array"):
        module.load_manifest(bad_command)


def test_failure_replay_execute_and_human_rendering(monkeypatch, tmp_path) -> None:
    module = _load_module()
    calls: list[tuple[list[str], Path, bool]] = []

    def _fake_run(command, *, cwd, check):
        calls.append((list(command), cwd, check))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    payload = module.replay_payload(
        {
            "schema": "agilab.widget_robot_matrix_failure_bundle.v1",
            "command": ["python", "-m", "robot"],
            "_manifest_path": str(tmp_path / "manifest.json"),
        },
        execute=True,
        cwd=tmp_path,
    )

    assert payload["returncode"] == 7
    assert calls == [(["python", "-m", "robot"], tmp_path, False)]
    rendered = module.render_human(payload)
    assert "AGILAB UI robot failure replay" in rendered
    assert "exit: 7" in rendered


def test_failure_replay_human_cli_uses_manifest_file(tmp_path, capsys) -> None:
    module = _load_module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "agilab.widget_robot_matrix_failure_bundle.v1",
                "command": ["python", "tools/agilab_widget_robot_matrix.py", "--json"],
            }
        ),
        encoding="utf-8",
    )

    exit_code = module.main([str(manifest)])

    assert exit_code == 0
    rendered = capsys.readouterr().out
    assert "AGILAB UI robot failure replay" in rendered
    assert "tools/agilab_widget_robot_matrix.py" in rendered
