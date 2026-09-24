"""Public usage and CLI evidence boundaries."""
import json
from types import ModuleType
import sys

import pytest

from agilab.agent_runtime import usage


@pytest.mark.parametrize("cached", [-1, True, 11, "3"])
def test_usage_rejects_invalid_cached_counts(cached):
    report = usage.parse_codex_jsonl(json.dumps({"type":"turn.completed",
        "usage":{"input_tokens":10, "output_tokens":2, "cached_input_tokens":cached}}))
    assert report["status"] == "missing"
    assert report["usage"] is None


def test_usage_ignores_blank_lines_but_rejects_non_event_json():
    valid = json.dumps({"type":"turn.completed", "usage":{"input_tokens":10, "output_tokens":2}})
    assert usage.parse_codex_jsonl("\n  \n" + valid + "\n")["status"] == "available"
    invalid = usage.parse_codex_jsonl("[]\n" + valid)
    assert invalid["status"] == "missing"
    assert invalid["invalid_line_count"] == 1


def test_usage_bounds_event_type_and_model_inventory_and_deduplicates_models():
    events = [{"type":f"event-{i}", "model":f"model-{i // 2}"} for i in range(80)]
    report = usage.parse_codex_jsonl("\n".join(json.dumps(event) for event in events))
    assert len(report["event_types"]) == 64
    assert report["reported_models"] == [f"model-{i}" for i in range(16)]
    assert report["event_count"] == 80
    assert report["usage"] is None


def test_usage_rejects_oversized_utf8_evidence():
    with pytest.raises(ValueError, match="8 MiB"):
        usage.parse_codex_jsonl("é" * (4 * 1024 * 1024 + 1))


def test_usage_started_after_completion_is_not_authoritative():
    complete = {"type":"turn.completed", "usage":{"input_tokens":1, "output_tokens":1}}
    report = usage.parse_codex_jsonl(json.dumps(complete) + '\n{"type":"turn.started"}')
    assert report["status"] == "missing"
    assert report["usage"] is None


def test_export_quarto_cli_writes_replayable_manifest_without_renderer(tmp_path, capsys):
    from agilab import bridge_cli
    from test.test_audience_bridges import _write_manifest
    manifest = _write_manifest(tmp_path)
    output = tmp_path / "workflow-evidence.qmd"
    assert bridge_cli.main(["export","quarto","--run",str(manifest),
                            "--output",str(output),"--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "pass"
    assert "Audience bridge proof" in output.read_text()
    assert (tmp_path / "manifest.json").is_file()


@pytest.mark.parametrize("separator", [False, True])
def test_mcp_cli_forwards_argument_boundary_without_starting_server(monkeypatch, separator):
    from agilab import bridge_cli
    import agilab_mcp
    server = ModuleType("agilab_mcp.server")
    received = []
    server.main = lambda args: received.append(args) or 7
    monkeypatch.setitem(sys.modules, "agilab_mcp.server", server)
    monkeypatch.setattr(agilab_mcp, "server", server)
    argv = ["mcp"] + (["--","--help"] if separator else [])
    assert bridge_cli.main(argv) == 7
    assert received == [["--help"] if separator else []]


def test_vscode_bridge_preserves_existing_quickstart(tmp_path):
    from agilab import bridge_cli
    quickstart = tmp_path / "AGILAB_QUICKSTART.md"
    quickstart.write_text("operator notes")
    with pytest.raises(FileExistsError, match="AGILAB_QUICKSTART"):
        bridge_cli.init_vscode_bridge(tmp_path)
    assert quickstart.read_text() == "operator notes"


def _capture(tmp_path, code, **kwargs):
    import os
    from agilab.agent_runtime.process_capture import capture_command
    return capture_command([sys.executable, "-c", code], cwd=str(tmp_path),
        env=dict(os.environ), timeout=5, stdout_path=tmp_path / "stdout.txt",
        stderr_path=tmp_path / "stderr.txt", **kwargs)


@pytest.mark.parametrize("limit", [True, 0, 1023, "2048"])
def test_capture_rejects_invalid_log_budget_before_starting_child(tmp_path, monkeypatch, limit):
    from agilab.agent_runtime import process_capture
    monkeypatch.setattr(process_capture.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("child must not start"))
    with pytest.raises(ValueError, match="max_log_bytes"):
        _capture(tmp_path, "pass", max_log_bytes=limit)


@pytest.mark.parametrize("redact", [False, True])
def test_capture_preserves_complete_nonnewline_output_and_explicit_redaction_choice(tmp_path, redact):
    result = _capture(tmp_path, "import sys; sys.stdout.write('API_KEY=synthetic_secret')", redact=redact)
    assert result["returncode"] == 0
    text = (tmp_path / "stdout.txt").read_text()
    assert ("synthetic_secret" in text) is (not redact)
    assert result["streams"]["stdout"]["stream_complete"] is True
    assert result["streams"]["stdout"]["truncated"] is False


def test_capture_cancellation_stops_only_its_owned_child(tmp_path, monkeypatch):
    from agilab.agent_runtime import process_capture
    real_popen = process_capture.subprocess.Popen
    children = []
    def start(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(process_capture.subprocess, "Popen", start)
    ready = tmp_path / "child-ready"
    result = _capture(tmp_path,
        "from pathlib import Path; import time; Path('child-ready').write_text('ready'); time.sleep(30)",
        cancelled=ready.exists)
    assert result["termination"] == "cancelled"
    assert result["returncode"] == 130
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("pause", [False, True])
def test_capture_log_write_failure_is_propagated_and_child_reaped(tmp_path, monkeypatch, pause):
    from agilab.agent_runtime import process_capture
    real_popen = process_capture.subprocess.Popen
    children = []
    def start(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(process_capture.subprocess, "Popen", start)
    (tmp_path / "stdout.txt").mkdir()
    # Windows reports EACCES for opening a directory as a file.
    with pytest.raises((IsADirectoryError, PermissionError)):
        _capture(tmp_path, "import time; print('output'); time.sleep(30)" if pause else "print('output')")
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("invalid_input", ["missing_evidence", "linked_project", "linked_evidence"])
def test_hf_export_rejects_invalid_inputs_before_mutating_existing_output(tmp_path, invalid_input):
    from agilab import bridge_cli
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('app')")
    output = tmp_path / "export"
    output.mkdir()
    marker = output / "operator-data"
    marker.write_text("preserve")
    evidence = None
    if invalid_input == "missing_evidence":
        evidence = tmp_path / "missing-evidence"
        error, message = FileNotFoundError, "Evidence path does not exist"
    elif invalid_input == "linked_project":
        link = tmp_path / "project-link"
        link.symlink_to(project, target_is_directory=True)
        project = link
        error, message = RuntimeError, "symlink"
    else:
        evidence = tmp_path / "evidence-link"
        evidence.symlink_to(project / "app.py")
        error, message = RuntimeError, "symlink"
    with pytest.raises(error, match=message):
        bridge_cli.export_hf_space(project, output, evidence_path=evidence, force=True)
    assert marker.read_text() == "preserve"
    assert sorted(path.name for path in output.iterdir()) == ["operator-data"]


def test_notebook_client_preserves_explicit_kernel_and_failed_execution_output(tmp_path, monkeypatch):
    from agilab import bridge_cli
    import nbformat
    import nbclient
    prepared = tmp_path / "prepared.ipynb"
    executed = tmp_path / "executed.ipynb"
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("raise ValueError('failure')")]), prepared)
    captured = []
    class FailedClient:
        def __init__(self, notebook, **kwargs):
            self.notebook = notebook
            captured.append(kwargs)
        def execute(self):
            self.notebook.cells[0].outputs = [nbformat.v4.new_output(
                "error", ename="ValueError", evalue="failure", traceback=["ValueError: failure"])]
            raise RuntimeError("kernel failed")
    monkeypatch.setattr(nbclient, "NotebookClient", FailedClient)
    with pytest.raises(RuntimeError, match="kernel failed"):
        bridge_cli._execute_notebook_with_nbclient(prepared, executed, tmp_path, tmp_path, {}, 17, "custom-kernel", False)
    assert captured == [{"timeout":17, "resources":{"metadata":{"path":str(tmp_path)}},
                         "allow_errors":False, "kernel_name":"custom-kernel"}]
    assert bridge_cli._extract_notebook_streams(executed)["stderr"] == "ValueError: failure"
