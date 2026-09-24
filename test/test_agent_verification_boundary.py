"""The read-only verification owner stays independent of execution and CLI code."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from agilab.agent_runtime import verification
from agilab import agent_run


def test_read_only_import_does_not_load_execution_owner():
    source = Path(__file__).resolve().parents[1] / "src"
    code = """import json, sys
sys.path.insert(0, sys.argv[1])
from agilab.agent_runtime.verification import validate_agent_run
print(json.dumps({"execution_loaded": "agilab.agent_runtime.agent_run" in sys.modules,
                  "capture_loaded": "agilab.agent_runtime.process_capture" in sys.modules}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(source)],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout) == {
        "execution_loaded": False,
        "capture_loaded": False,
    }


def test_public_facade_and_read_only_verifier_preserve_outcomes(tmp_path):
    manifest = {
        "kind": verification.TRACE_KIND,
        "status": "planned",
        "run_id": "planned",
        "command": {"argv_sha256": "hash"},
        "artifacts": {},
    }
    assert agent_run.validate_agent_run(manifest) == verification.validate_agent_run(
        manifest
    )
    assert agent_run.AgentRunSummary is verification.AgentRunSummary
    assert agent_run.summarize_agent_run(manifest) == verification.summarize_agent_run(
        manifest
    )


def test_verification_source_remains_small_and_execution_free():
    path = Path(verification.__file__)
    assert len(path.read_text().splitlines()) <= 550
    assert "from agilab.agent_runtime.agent_run import" not in path.read_text()


def _terminal_manifest(tmp_path):
    import hashlib
    artifacts = {}
    for name in ("stdout", "stderr"):
        path = tmp_path / (name + ".txt")
        path.write_bytes(b"")
        artifacts[name] = {"path": str(path), "sha256": hashlib.sha256(b"").hexdigest(), "size_bytes": 0}
    return {"kind": verification.TRACE_KIND, "status": "fail", "returncode": 1,
            "run_id": "run", "command": {"argv_sha256": "digest"}, "artifacts": artifacts,
            "termination": {"schema": "agilab.agent_run.termination.v1",
                "reason": "execution_infrastructure_error", "phase": "publish",
                "error_type": "OSError", "trace_recorded": False}}


@pytest.mark.parametrize(("changes", "code"), [
    ({"schema": "other"}, "termination_schema"),
    ({"reason": "other"}, "termination_reason"),
    ({"phase": ""}, "termination_phase"),
    ({"error_type": ""}, "termination_error_type"),
    ({"trace_recorded": "false"}, "termination_trace_state"),
    ({"reason": "system_exit", "error_type": "OSError"}, "termination_error_type"),
    ({"reason": "operator_cancelled", "error_type": "KeyboardInterrupt"}, "termination_status"),
    ({"reason": "operator_cancelled", "error_type": "OSError"}, "termination_error_type"),
])
def test_termination_evidence_rejects_inconsistent_fields(tmp_path, changes, code):
    manifest = _terminal_manifest(tmp_path)
    manifest["termination"].update(changes)
    report = verification.validate_agent_run(manifest)
    assert not report["ok"]
    assert code in {issue["code"] for issue in report["issues"]}


@pytest.mark.parametrize(("reason", "status", "returncode", "error_type", "code"), [
    ("system_exit", "planned", None, "SystemExit", "termination_returncode"),
    ("system_exit", "timeout", 124, "SystemExit", "termination_status"),
    ("execution_infrastructure_error", "pass", 0, "OSError", "termination_status"),
    ("execution_infrastructure_error", "fail", None, "OSError", "termination_returncode"),
])
def test_termination_requires_matching_terminal_outcome(tmp_path, reason, status, returncode, error_type, code):
    manifest = _terminal_manifest(tmp_path)
    manifest.update(status=status, returncode=returncode)
    manifest["termination"].update(reason=reason, error_type=error_type)
    report = verification.validate_agent_run(manifest)
    assert code in {issue["code"] for issue in report["issues"]}


def test_non_object_termination_is_invalid_even_when_artifacts_verify(tmp_path):
    manifest = _terminal_manifest(tmp_path)
    manifest["termination"] = "cancelled"
    report = verification.validate_agent_run(manifest)
    assert "termination" in {issue["code"] for issue in report["issues"]}
    assert report["content_integrity"]["status"] == "verified"


@pytest.mark.parametrize(("reason", "returncode", "error_type"), [
    ("system_exit", 1, "SystemExit"),
    ("operator_cancelled", 130, "KeyboardInterrupt"),
    ("execution_infrastructure_error", 1, "OSError"),
])
def test_valid_terminal_manifest_remains_authoritative_when_trace_cannot_be_written(tmp_path, reason, returncode, error_type):
    manifest = _terminal_manifest(tmp_path)
    manifest["returncode"] = returncode
    manifest["termination"].update(reason=reason, error_type=error_type)
    manifest["artifacts"]["agent_trace"] = {"events": str(tmp_path / "missing.jsonl")}
    report = verification.validate_agent_run(manifest)
    assert report["ok"]
    assert "termination_trace" in {warning["code"] for warning in report["warnings"]}
    assert report["content_integrity"]["status"] == "verified"


@pytest.mark.parametrize(("descriptor", "code"), [
    ({}, "claim_path"),
    ({"path": "absent"}, "claim_exists"),
])
def test_declared_claim_must_resolve_to_an_existing_artifact(tmp_path, descriptor, code):
    manifest = _terminal_manifest(tmp_path)
    if descriptor.get("path"):
        descriptor["path"] = str(tmp_path / descriptor["path"])
    manifest["artifacts"]["claim"] = descriptor
    report = verification.validate_agent_run(manifest)
    assert code in {issue["code"] for issue in report["issues"]}


@pytest.mark.parametrize(("payload", "code"), [
    ("{", "claim_payload"), ("[]", "claim_schema"),
    ('{"schema":"other"}', "claim_schema"),
    ('{"schema":"agilab.agent_run.claim.v1","run_id":"other"}', "claim_run_id"),
])
def test_claim_content_is_checked_independently_of_its_recorded_hash(tmp_path, payload, code):
    import hashlib
    manifest = _terminal_manifest(tmp_path)
    claim = tmp_path / "claim.json"
    claim.write_text(payload)
    manifest["artifacts"]["claim"] = {"path":str(claim),
        "sha256":hashlib.sha256(claim.read_bytes()).hexdigest(), "size_bytes":claim.stat().st_size}
    report = verification.validate_agent_run(manifest)
    assert code in {issue["code"] for issue in report["issues"]}
    assert report["content_integrity"]["artifacts"]["claim"] == "verified"


@pytest.mark.parametrize(("field", "value", "code"), [
    ("sha256", "not-a-digest", "stdout_sha256"),
    ("sha256", 3, "stdout_sha256"),
    ("size_bytes", -1, "stdout_size"),
    ("size_bytes", True, "stdout_size"),
    ("size_bytes", 1, "stdout_size"),
])
def test_integrity_rejects_invalid_descriptors_and_changed_sizes(tmp_path, field, value, code):
    manifest = _terminal_manifest(tmp_path)
    manifest["artifacts"]["stdout"][field] = value
    report = verification.validate_agent_run(manifest)
    assert code in {issue["code"] for issue in report["issues"]}
    assert report["content_integrity"]["artifacts"]["stdout"] == "failed"


def test_legacy_artifact_without_hash_is_unverified_and_warns(tmp_path):
    manifest = _terminal_manifest(tmp_path)
    del manifest["artifacts"]["stdout"]["sha256"]
    report = verification.validate_agent_run(manifest)
    assert report["ok"]
    assert "stdout_integrity" in {warning["code"] for warning in report["warnings"]}
    assert report["content_integrity"]["status"] == "unverified"


def test_artifact_directory_cannot_satisfy_file_integrity(tmp_path):
    manifest = _terminal_manifest(tmp_path)
    manifest["artifacts"]["stdout"]["path"] = str(tmp_path)
    report = verification.validate_agent_run(manifest)
    assert "stdout_file" in {issue["code"] for issue in report["issues"]}


def test_artifact_read_failure_does_not_report_verified_content(tmp_path, monkeypatch):
    manifest = _terminal_manifest(tmp_path)
    target = Path(manifest["artifacts"]["stdout"]["path"])
    real_open = Path.open
    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError("unreadable artifact")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    report = verification.validate_agent_run(manifest)
    assert "stdout_read" in {issue["code"] for issue in report["issues"]}
    assert report["content_integrity"]["status"] == "failed"


def test_trace_parse_failure_is_error_unless_manifest_records_unavailable_trace(tmp_path):
    manifest = _terminal_manifest(tmp_path)
    trace = tmp_path / "trace.jsonl"
    trace.write_text("invalid")
    manifest["artifacts"]["agent_trace"] = {"events":str(trace)}
    def invalid_trace(path):
        raise ValueError("malformed trace")
    manifest["termination"]["trace_recorded"] = True
    report = verification.validate_agent_run(manifest, trace_loader=invalid_trace)
    assert "trace_events_invalid" in {issue["code"] for issue in report["issues"]}
    manifest["termination"]["trace_recorded"] = False
    assert verification.validate_agent_run(manifest, trace_loader=invalid_trace)["ok"]


def test_command_identity_is_required_and_unredacted_arguments_warn(tmp_path):
    manifest = _terminal_manifest(tmp_path)
    manifest["command"] = {"argv_redacted": False}
    report = verification.validate_agent_run(manifest)
    assert "argv_sha256" in {issue["code"] for issue in report["issues"]}
    assert "argv_redaction" in {warning["code"] for warning in report["warnings"]}
