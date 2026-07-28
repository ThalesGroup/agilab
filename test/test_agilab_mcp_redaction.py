"""Redaction and read-boundary contract for the AGILAB MCP evidence tools.

The MCP server hands run evidence to external agents, so every tool that returns
manifest-derived text must redact secrets - not just the tools that return the
manifest itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agilab_mcp import manifest_tools


SECRET = "sk-LIVEKEY1234567890abcdefSECRET"

# Exercises the trap that makes a blanket ``redact_mapping`` wrong here:
# ``manifest_summary`` keys ``validation_statuses`` by validation label, and the
# secret-key pattern matches a bare "auth"/"key" substring.
_VALIDATION_LABEL = "auth_check"


def _write_manifest(root: Path) -> Path:
    payload = {
        "schema_version": 1,
        "kind": "agilab.run_manifest",
        "run_id": "a" * 32,
        "path_id": "demo",
        "label": f"nightly {SECRET}",
        "status": "pass",
        "command": {"argv": ["run", "--token", SECRET], "cwd": str(root)},
        "environment": {"password": SECRET, "python": "3.13"},
        "timing": {"duration_seconds": 1.0, "target_seconds": 2.0},
        "artifacts": [
            {
                "name": f"out-{SECRET}.csv",
                "kind": "data",
                "path": "out.csv",
                "size_bytes": 3,
                "sha256": "",
            }
        ],
        "validations": [{"label": _VALIDATION_LABEL, "status": "pass"}],
        "created_at": "2026-01-01T00:00:00Z",
    }
    manifest_path = root / "run_manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    (root / "out.csv").write_text("a,b", encoding="utf-8")
    return manifest_path


@pytest.fixture
def manifest(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))
    return _write_manifest(tmp_path)


@pytest.mark.parametrize(
    "tool_name, build_args",
    [
        ("read_manifest", lambda path: (str(path),)),
        ("summarize_run", lambda path: (str(path),)),
        ("list_artifacts", lambda path: (str(path),)),
        ("compare_runs", lambda path: (str(path), str(path))),
    ],
)
def test_mcp_tools_never_return_raw_secrets(manifest: Path, tool_name, build_args):
    """No manifest-derived MCP payload may carry a secret verbatim."""

    result = getattr(manifest_tools, tool_name)(*build_args(manifest))
    assert SECRET not in json.dumps(result, sort_keys=True)


def test_summarize_run_redacts_label_but_keeps_status(manifest: Path):
    summary = manifest_tools.summarize_run(str(manifest))["summary"]

    assert SECRET not in summary["label"]
    assert "<redacted>" in summary["label"]
    # Redaction must not cost us the run outcome or the counts.
    assert summary["status"] == "pass"
    assert summary["artifact_count"] == 1


def test_validation_status_survives_redaction(manifest: Path):
    """A validation label matching the secret-key pattern keeps its status.

    ``redact_mapping`` blanks a value whose *key* matches SECRET|TOKEN|KEY|AUTH.
    Because validation labels are keys here, using it would report an
    ``auth_check`` result as ``<redacted>`` instead of ``pass``, hiding a real
    pass/fail signal behind a redaction.
    """

    summary = manifest_tools.summarize_run(str(manifest))["summary"]
    assert summary["validation_statuses"] == {_VALIDATION_LABEL: "pass"}


def test_list_artifacts_redacts_name_but_keeps_metadata(manifest: Path):
    artifacts = manifest_tools.list_artifacts(str(manifest))["artifacts"]

    assert len(artifacts) == 1
    row = artifacts[0]
    assert SECRET not in row["name"]
    assert row["kind"] == "data"
    assert row["exists"] is True


def test_compare_runs_keeps_numeric_deltas_after_redaction(manifest: Path):
    result = manifest_tools.compare_runs(str(manifest), str(manifest))

    assert SECRET not in json.dumps(result, sort_keys=True)
    # Deltas are computed from the redacted summaries, so numbers must survive.
    assert result["artifact_count_delta"] == 0
    assert result["duration_delta_seconds"] == 0.0
    assert result["status_changed"] is False


def test_read_boundary_rejects_paths_outside_allowed_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))

    with pytest.raises(ValueError, match="outside configured read roots"):
        manifest_tools.read_manifest("/etc/passwd")
