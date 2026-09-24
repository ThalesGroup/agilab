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


@pytest.mark.parametrize(("status", "chunks", "message"), [
    (302, [], "without redirects"), (200, [b"123", b"456"], "16 MiB"),
])
def test_source_download_rejects_redirects_and_oversized_streams(monkeypatch, status, chunks, message):
    import requests
    class Response:
        status_code = status
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size):
            assert size == 65536
            return iter(chunks)
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(demo, "MAX_SOURCE_BYTES", 5)
    with pytest.raises(ValueError, match=message):
        demo._download_source("https://example.invalid/notebook")
    assert calls[0][1] == {"timeout": (10,60), "stream":True, "allow_redirects":False}


def test_curated_source_retains_license_and_never_executes_cells(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    payload = json.dumps({"nbformat":4, "cells":[{"cell_type":"code",
        "source":"raise RuntimeError('must not execute')"}]}).encode()
    monkeypatch.setattr(demo, "_download_source", lambda url: b"license" if url.endswith("/LICENSE") else payload)
    provenance = demo.fetch_source(project)
    assert provenance["source_kind"] == "curated"
    assert provenance["license_sha256"] == demo.digest(project / "source/LICENSE")
    assert provenance["source_cells"] == 1
    assert (tmp_path / "source_import.json").is_file()


@pytest.mark.parametrize("mode", ["suffix", "too_large"])
def test_local_source_rejects_wrong_type_or_size(tmp_path, monkeypatch, mode):
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / ("source.txt" if mode == "suffix" else "source.ipynb")
    source.write_bytes(b"123456")
    monkeypatch.setattr(demo, "MAX_SOURCE_BYTES", 5)
    with pytest.raises(ValueError, match="regular .ipynb|16 MiB"):
        demo.fetch_source(project, notebook=source)


@pytest.mark.parametrize(("options", "message"), [
    ({"intent":""}, "objective"), ({"timeout":59}, "time limit"),
    ({"notebook":Path("source.ipynb"), "notebook_url":"https://example.invalid"}, "not both"),
    ({"input_files":{"data.csv":Path("source.csv")}}, "Supplied inputs"),
])
def test_build_input_rejection_persists_failed_report_without_provider(tmp_path, monkeypatch, options, message):
    calls = []
    monkeypatch.setattr(demo, "run_agent_command", lambda config: calls.append(config))
    report = demo.build(tmp_path, **options)
    assert report["status"] == "failed" and message in report["error"]
    assert not calls
    assert json.loads((tmp_path / "result.json").read_text()) == report


@pytest.mark.parametrize("argv", [
    ["--timeout","59"], ["--check","--ui"],
    ["--check"], ["--notebook","x.ipynb","--input-file","bad"],
    ["--notebook","x.ipynb","--input-file","x=a","--input-file","x=b"],
])
def test_cli_rejects_invalid_arguments_before_execution(argv, monkeypatch):
    monkeypatch.setattr(demo, "create_run", lambda *a: pytest.fail("must not create a run"))
    with pytest.raises(SystemExit) as raised:
        demo.main(argv)
    assert raised.value.code == 2


@pytest.mark.parametrize("safe", [False, True])
def test_check_cli_reports_prerequisites_without_creating_run(monkeypatch, capsys, safe):
    captured = []
    monkeypatch.setattr(demo, "create_run", lambda *a: pytest.fail("must not create a run"))
    def check(**kwargs):
        captured.append(kwargs)
        return {"safe_to_build":safe}
    monkeypatch.setattr(demo, "check_notebook", check)
    assert demo.main(["--check","--notebook","x.ipynb","--input-file","data.csv=input.csv"]) == (0 if safe else 1)
    assert json.loads(capsys.readouterr().out) == {"safe_to_build":safe}
    assert captured[0]["input_files"] == {"data.csv":Path("input.csv")}


def test_check_cli_converts_source_errors_to_blocked_report(monkeypatch, capsys):
    def failed(**kwargs):
        raise OSError("source unreadable")
    monkeypatch.setattr(demo, "check_notebook", failed)
    assert demo.main(["--check","--notebook","x.ipynb"]) == 1
    assert json.loads(capsys.readouterr().out) == {"status":"blocked", "safe_to_build":False, "error":"source unreadable"}


@pytest.mark.parametrize("passed", [False, True])
def test_build_cli_propagates_selected_inputs_and_terminal_exit(tmp_path, monkeypatch, capsys, passed):
    calls = []
    monkeypatch.setattr(demo, "create_run", lambda output: tmp_path)
    def build(root, **kwargs):
        calls.append((root, kwargs))
        return {"status":"passed" if passed else "failed"}
    monkeypatch.setattr(demo, "build", build)
    assert demo.main(["--notebook","input.ipynb","--input-file","data.csv=source.csv"]) == (0 if passed else 1)
    assert calls[0][1]["intent"] == demo.GENERIC_REQUEST
    assert calls[0][1]["input_files"] == {"data.csv":Path("source.csv")}
    assert "Live run:" in capsys.readouterr().out
