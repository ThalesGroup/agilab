"""Evidence consumers must distinguish readable records from verified results."""

import json
from pathlib import Path
import sys

import pytest

from agilab.agent_runtime import agent_run
from agilab_mcp import manifest_tools


def _run(root: Path) -> dict:
    return agent_run.trace_agent_run(
        [
            sys.executable,
            "-c",
            "import sys; print('original'); print('diagnose', file=sys.stderr)",
        ],
        agent="fixture",
        cwd=root,
        output_dir=root / "run",
        run_id="integrity",
        permission_level="standard",
    ).manifest


@pytest.mark.parametrize("artifact", ["stdout", "stderr"])
def test_changed_output_rejected_by_cli_and_mcp(tmp_path, monkeypatch, artifact):
    manifest = _run(tmp_path)
    path = Path(manifest["artifacts"][artifact]["path"])
    original = path.read_bytes()
    path.write_bytes(b"x" * len(original))
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))

    direct = agent_run.validate_agent_run(tmp_path / "run")
    remote = manifest_tools.validate_agent_run(tmp_path / "run")["validation"]
    for result in (direct, remote):
        assert result["ok"] is False
        assert f"{artifact}_sha256" in {issue["code"] for issue in result["issues"]}
        assert result["content_integrity"]["status"] == "failed"
        assert "original" not in json.dumps(result)


@pytest.mark.parametrize(
    "status,code",
    [("pass", 7), ("fail", 0), ("timeout", 1), ("pass", True), ("pass", None)],
)
def test_contradictory_terminal_metadata_is_rejected(tmp_path, status, code):
    manifest = _run(tmp_path)
    manifest.update(status=status, returncode=code)
    result = agent_run.validate_agent_run(manifest)
    assert result["ok"] is False
    assert {issue["code"] for issue in result["issues"]} & {
        "status_returncode",
        "returncode",
    }


def test_legacy_hashless_outputs_remain_readable_but_unverified(tmp_path):
    manifest = _run(tmp_path)
    for name in ("stdout", "stderr"):
        manifest["artifacts"][name].pop("sha256")
    result = agent_run.validate_agent_run(manifest)
    assert result["ok"] is True
    assert result["content_integrity"]["status"] == "unverified"
    assert {row["code"] for row in result["warnings"]} >= {
        "stdout_integrity",
        "stderr_integrity",
    }


def test_terminal_trace_must_agree_with_manifest(tmp_path):
    manifest = _run(tmp_path)
    trace = Path(manifest["artifacts"]["agent_trace"]["events"])
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    events[-1]["status"] = "fail"
    events[-1]["metadata"]["returncode"] = 7
    trace.write_text("".join(json.dumps(event) + "\n" for event in events))
    result = agent_run.validate_agent_run(manifest)
    assert result["ok"] is False
    assert {issue["code"] for issue in result["issues"]} >= {
        "trace_terminal",
        "trace_returncode",
    }


def test_complete_manifest_verifies_only_recorded_artifact_scope(tmp_path):
    manifest = _run(tmp_path)
    result = agent_run.validate_agent_run(manifest)
    assert result["ok"] is True
    assert result["content_integrity"]["status"] == "verified"
    assert result["content_integrity"]["artifacts"] == dict.fromkeys(
        ("stdout", "stderr", "claim"), "verified"
    )


def test_publication_failure_after_success_keeps_distinct_terminal_outcomes(tmp_path, monkeypatch):
    original_write = agent_run._atomic_write_text
    failed = False

    def fail_first_manifest(path, text):
        nonlocal failed
        if path.name == agent_run.MANIFEST_FILENAME and not failed:
            failed = True
            raise OSError("injected manifest publication failure")
        return original_write(path, text)

    monkeypatch.setattr(agent_run, "_atomic_write_text", fail_first_manifest)
    manifest = _run(tmp_path)
    assert manifest["status"] == "fail"
    assert manifest["returncode"] == 125
    assert manifest["termination"]["phase"] == "manifest publication"
    result = agent_run.validate_agent_run(tmp_path / "run")
    assert result["ok"] is True
    assert result["content_integrity"]["status"] == "verified"


def test_command_event_must_be_internally_consistent(tmp_path):
    manifest = _run(tmp_path)
    trace = Path(manifest["artifacts"]["agent_trace"]["events"])
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    command = next(event for event in events if event["event"] == "command_done")
    command["status"] = "fail"
    trace.write_text("".join(json.dumps(event) + "\n" for event in events))
    result = agent_run.validate_agent_run(manifest)
    assert result["ok"] is False
    assert "trace_outcome" in {issue["code"] for issue in result["issues"]}
