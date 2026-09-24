"""Acceptance-boundary tests; provider execution is exercised separately live."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agilab.agent_runtime import notebook_agent as demo


def source_fixture(project):
    source = project / "source"
    source.mkdir()
    (source / "original.ipynb").write_text('{"nbformat":4,"cells":[]}')
    (source / "LICENSE").write_text("fixture license")
    return {"sha256": demo.digest(source / "original.ipynb"),
            "license_sha256": demo.digest(source / "LICENSE")}


def test_provider_failure_never_reports_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(demo.shutil, "which", lambda _: "/usr/local/bin/tokki")
    monkeypatch.setattr(demo, "fetch_source", source_fixture)
    monkeypatch.setattr(demo, "run_agent_command", lambda _: SimpleNamespace(returncode=3))
    report = demo.build(tmp_path)
    assert report["status"] == "failed"
    assert "exit 3" in report["error"]
    assert [e["phase"] for e in demo.read_events(tmp_path)] == ["import", "build", "failed"]
    assert json.loads((tmp_path / "result.json").read_text()) == report


def test_verifier_mutation_is_rejected_before_recheck(tmp_path, monkeypatch):
    monkeypatch.setattr(demo.shutil, "which", lambda _: "/usr/local/bin/tokki")
    monkeypatch.setattr(demo, "fetch_source", source_fixture)

    def mutate(config):
        assert "verified-run" in config.command
        assert config.permission_level == "standard"
        assert "--full-auto" not in config.command
        assert "workspace-write" in config.command
        (tmp_path / "verify_app").write_text("#!/bin/sh\nexit 0\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(demo, "run_agent_command", mutate)
    result = demo.build(tmp_path)
    assert result["status"] == "failed"
    assert "Verifier changed" in result["error"]


def test_upstream_mutation_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(demo.shutil, "which", lambda _: "/usr/local/bin/tokki")
    monkeypatch.setattr(demo, "fetch_source", source_fixture)

    def mutate(config):
        (config.cwd / "source" / "original.ipynb").write_text("tampered")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(demo, "run_agent_command", mutate)
    result = demo.build(tmp_path)
    assert result["status"] == "failed"
    assert "Upstream source changed" in result["error"]


def test_partial_event_append_can_be_read(tmp_path):
    demo.event(tmp_path, "import", "Imported")
    with (tmp_path / "events.jsonl").open("a") as stream:
        stream.write('{"partial":')
    assert len(demo.read_events(tmp_path)) == 1


def test_ui_starts_without_launching_provider():
    from streamlit.testing.v1 import AppTest

    app = Path(demo.__file__).parents[1] / "demos" / "notebook_demo_ui.py"
    at = AppTest.from_file(str(app), default_timeout=30).run()
    assert not at.exception
    assert at.button[0].label == "Build my app"
    assert "run_root" not in at.session_state


def test_ui_launcher_uses_packaged_file_and_preserves_settings(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(demo.subprocess, "call", lambda argv: captured.append(argv) or 0)
    assert demo.main(["--ui", "--output", str(tmp_path), "--tokki", "/custom/tokki",
                      "--timeout", "90"]) == 0
    command = captured[0]
    assert Path(command[4]).is_file()
    assert Path(command[4]).name == "notebook_demo_ui.py"
    assert Path(command[4]).parent.name == "demos"
    assert "--server.address=127.0.0.1" in command
    assert command[command.index("--tokki") + 1] == "/custom/tokki"
    assert command[command.index("--output") + 1] == str(tmp_path)


def test_verifier_rejects_non_learning_models(tmp_path, monkeypatch):
    from agilab.agent_runtime.notebook_verifier import verify

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "models", None)
    (tmp_path / "models.py").write_text(
        "from sklearn.dummy import DummyClassifier\n"
        "def build_models(max_depth=3, seed=42):\n"
        "    return {str(i): DummyClassifier(strategy='most_frequent') for i in range(3)}\n"
    )
    (tmp_path / "app.py").write_text("pass\n")
    (tmp_path / "solution.ipynb").write_text("{}")
    with pytest.raises(ValueError, match="held-out accuracy"):
        verify(tmp_path)
