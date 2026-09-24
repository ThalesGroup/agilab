"""Failure contracts for immutable notebook source acquisition and trace replay."""
import base64
import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agilab.agent_runtime import notebook_agent as notebook
from agilab.agent_runtime import agent_trace as trace


def notebook_bytes(**changes):
    return json.dumps({"nbformat": 4, "cells": [], **changes}).encode()


@pytest.mark.parametrize("suffix", ["?token=secret", "#fragment"])
def test_pinned_source_rejects_query_or_fragment(suffix):
    with pytest.raises(ValueError, match="Use https"):
        notebook.pinned_notebook_url(notebook.SOURCE_URL + suffix)


@pytest.mark.parametrize("path", ["../a.ipynb", "folder/%2e%2e/a.ipynb", "folder/%00.ipynb", "folder/%5ca.ipynb", "folder//a.ipynb", "a.py"])
def test_pinned_source_rejects_ambiguous_or_non_notebook_paths(path):
    with pytest.raises(ValueError):
        notebook.pinned_notebook_url("https://github.com/owner/repo/blob/" + "a" * 40 + "/" + path)


def test_pinned_source_canonicalizes_commit_and_quotes_path():
    raw, provenance = notebook.pinned_notebook_url("https://github.com/owner/repo/blob/" + "A" * 40 + "/folder/a%20b.ipynb")
    assert raw == "https://raw.githubusercontent.com/owner/repo/" + "a" * 40 + "/folder/a%20b.ipynb"
    assert provenance["commit"] == "a" * 40
    assert provenance["source_kind"] == "github"


@pytest.mark.parametrize("status,chunks,error", [(302, [], "HTTP 200"), (200, [b"123", b"456"], "16 MiB")])
def test_download_refuses_redirects_and_stream_overflow(monkeypatch, status, chunks, error):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status_code = status
    response.iter_content.return_value = chunks
    get = Mock(return_value=response)
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=get))
    monkeypatch.setattr(notebook, "MAX_SOURCE_BYTES", 5)
    with pytest.raises(ValueError, match=error):
        notebook._download_source("https://raw.githubusercontent.com/owner/repo/hash/a.ipynb")
    assert get.call_args.kwargs == {"timeout": (10, 60), "stream": True, "allow_redirects": False}
    response.__exit__.assert_called_once()


def test_source_import_records_hash_and_never_executes_cells(tmp_path):
    selected = tmp_path / "selected.ipynb"
    sentinel = tmp_path / "must-not-exist"
    payload = notebook_bytes(cells=[{"cell_type": "code", "source": f"from pathlib import Path; Path({str(sentinel)!r}).write_text('executed')", "metadata": {}}])
    selected.write_bytes(payload)
    project = tmp_path / "run" / "project"
    project.mkdir(parents=True)
    provenance = notebook.fetch_source(project, notebook=selected)
    assert provenance["sha256"] == hashlib.sha256(payload).hexdigest()
    assert provenance["source_cells"] == 1
    assert provenance["source_kind"] == "local"
    assert (project / "source" / "original.ipynb").read_bytes() == payload
    assert (project.parent / "source_import.json").is_file()
    assert not sentinel.exists()


@pytest.mark.parametrize("payload,error", [
    (b"[]", "version 4"), (notebook_bytes(nbformat=3), "version 4"),
    (notebook_bytes(cells={}), "version 4"),
    (notebook_bytes(cells=[None]), "Malformed notebook"),
    (notebook_bytes(cells=[{"cell_type": "invalid", "source": ""}]), "Malformed notebook"),
    (notebook_bytes(cells=[{"cell_type": "code", "source": 42}]), "Malformed notebook"),
])
def test_malformed_source_never_publishes_provenance_or_import(tmp_path, payload, error):
    selected = tmp_path / "selected.ipynb"
    selected.write_bytes(payload)
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match=error):
        notebook.fetch_source(project, notebook=selected)
    assert not (project / "source" / "provenance.json").exists()
    assert not (project.parent / "source_import.json").exists()


def test_source_selection_is_exclusive_and_bounded(monkeypatch, tmp_path):
    selected = tmp_path / "selected.ipynb"
    selected.write_bytes(notebook_bytes())
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match="not both"):
        notebook.fetch_source(project, notebook=selected, notebook_url=notebook.SOURCE_URL)
    assert not (project / "source").exists()
    monkeypatch.setattr(notebook, "MAX_SOURCE_BYTES", 1)
    with pytest.raises(ValueError, match="16 MiB"):
        notebook.fetch_source(project, notebook=selected)


def test_curated_source_binds_notebook_and_license_hashes(monkeypatch, tmp_path):
    payload, license_bytes = notebook_bytes(), b"license evidence"
    monkeypatch.setattr(notebook, "_download_source", Mock(side_effect=[payload, license_bytes]))
    project = tmp_path / "project"
    project.mkdir()
    provenance = notebook.fetch_source(project)
    assert provenance["source_kind"] == "curated"
    assert provenance["sha256"] == hashlib.sha256(payload).hexdigest()
    assert provenance["license_sha256"] == hashlib.sha256(license_bytes).hexdigest()
    assert provenance["commit"] == notebook.SOURCE_COMMIT


def test_event_reader_limits_recent_history_and_tolerates_partial_append(tmp_path):
    assert notebook.read_events(tmp_path) == []
    lines = [json.dumps({"phase": str(i)}) for i in range(110)]
    (tmp_path / "events.jsonl").write_text("\n".join(lines) + "\n{partial")
    records = notebook.read_events(tmp_path)
    assert len(records) == 99
    assert records[0]["phase"] == "11"
    assert records[-1]["phase"] == "109"


def write_trace(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


@pytest.mark.parametrize("payload,error", [(b"[]\n", "must be an object"), (b"not-json\n", "Invalid agent trace JSONL"), (b'{"sequence":"bad"}\n', "Invalid agent trace event")])
def test_trace_rejects_complete_malformed_records(payload, error):
    with pytest.raises(ValueError, match=error):
        trace._read_event(io.BytesIO(payload), Path("events.jsonl"))


def test_trace_record_budget_and_partial_tail_are_distinct(monkeypatch):
    monkeypatch.setattr(trace, "MAX_TRACE_RECORD_BYTES", 32)
    with pytest.raises(ValueError, match="exceeds 32"):
        trace._read_event(io.BytesIO(b"x" * 33), Path("events.jsonl"))
    assert trace._read_event(io.BytesIO(b'{"partial"'), Path("events.jsonl")) is None
    assert trace._read_event(io.BytesIO(b" \n"), Path("events.jsonl")) is False


@pytest.mark.parametrize("tail", [b"[]", b"\xff", b'{"partial"'])
def test_tail_repair_quarantines_exact_invalid_bytes_without_touching_prefix(tmp_path, tail):
    path = tmp_path / "events.jsonl"
    prefix = b'{"sequence":1}\n'
    path.write_bytes(prefix + tail)
    quarantined = trace.repair_jsonl_tail(path)
    assert quarantined is not None
    assert quarantined.read_bytes() == tail
    assert path.read_bytes() == prefix


def test_valid_unterminated_tail_is_preserved_and_newline_completed(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"sequence":1}')
    assert trace.repair_jsonl_tail(path) is None
    assert path.read_bytes() == b'{"sequence":1}\n'


def test_failed_quarantine_sync_preserves_live_trace(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    payload = b'{"sequence":1}\n{partial'
    path.write_bytes(payload)
    real_os = trace.os
    proxy = SimpleNamespace(**{name: getattr(real_os, name) for name in dir(real_os)})
    proxy.fsync = Mock(side_effect=OSError("disk full"))
    monkeypatch.setattr(trace, "os", proxy)
    with pytest.raises(OSError, match="disk full"):
        trace.repair_jsonl_tail(path)
    assert path.read_bytes() == payload
    assert not list(tmp_path.glob(".events.jsonl.partial.*"))


@pytest.mark.parametrize("limit", [True, 0, 101, "2"])
def test_trace_page_rejects_invalid_page_count(tmp_path, limit):
    with pytest.raises(ValueError, match="limit"):
        trace.trace_page(tmp_path / "missing", limit=limit)


@pytest.mark.parametrize("offset", [-1, True, "1", 999])
def test_trace_cursor_invalid_offsets_rejected(tmp_path, offset):
    path = tmp_path / "events.jsonl"
    write_trace(path, [{"sequence": 1}])
    cursor = base64.urlsafe_b64encode(json.dumps([offset, 0, 0, "hash"]).encode()).decode()
    with pytest.raises(ValueError, match="Stale or invalid"):
        trace.trace_page(path, cursor=cursor)


def test_trace_cursor_cannot_start_inside_record_even_with_correct_anchor(tmp_path):
    path = tmp_path / "events.jsonl"
    write_trace(path, [{"sequence": 1}])
    with path.open("rb") as stream:
        cursor = trace._cursor(stream, 2)
    with pytest.raises(ValueError, match="Stale or invalid"):
        trace.trace_page(path, cursor=cursor)


def test_trace_page_reports_partial_tail_and_resume_cursor(tmp_path):
    path = tmp_path / "events.jsonl"
    write_trace(path, [{"sequence": 1}])
    with path.open("ab") as stream:
        stream.write(b'{"sequence":')
    page = trace.trace_page(path)
    assert len(page["events"]) == 1
    assert page["resume_cursor"]
    assert page["next_cursor"] is None
    with path.open("ab") as stream:
        stream.write(b"2}\n")
    resumed = trace.trace_page(path, cursor=page["resume_cursor"])
    assert [event["sequence"] for event in resumed["events"]] == [2]


def test_large_trace_event_is_bounded_without_losing_following_record(tmp_path):
    path = tmp_path / "events.jsonl"
    write_trace(path, [{"sequence": 1, "event": "e" * 5000, "status": "s" * 5000,
                       "message": "m" * 5000, "metadata": {"extra": "x" * 5000}}, {"sequence": 2}])
    page = trace.trace_page(path, max_bytes=2048)
    assert page["events"][0]["truncated"]
    assert len(json.dumps(page).encode()) <= 2048
    next_page = trace.trace_page(path, cursor=page["next_cursor"])
    assert next_page["events"][0]["sequence"] == 2


@pytest.fixture
def export_bundle(tmp_path):
    from agilab.notebooks import notebook_export_support as export
    linked = tmp_path / "linked_analysis.py"
    linked.write_text("print('analysis')\n")
    path = tmp_path / "workflow.ipynb"
    data = {"nbformat": 4, "cells": [], "metadata": {"agilab": {"view_sync": {"sources": [{
        "kind": "analysis", "path": str(linked), "sha256": hashlib.sha256(linked.read_bytes()).hexdigest()
    }]}}}}
    path.write_text(export.notebook_export_json_text(data))
    handoff = export.notebook_export_handoff_path(path)
    handoff.write_text("Notebook handoff evidence\n")
    manifest = export.build_notebook_export_manifest(data, path, handoff_path=handoff,
        handoff_sha256=hashlib.sha256(handoff.read_bytes()).hexdigest())
    manifest_path = export.notebook_export_manifest_path(path)
    manifest_path.write_text(json.dumps(manifest))
    assert export.verify_notebook_export_manifest(path)["ok"]
    return export, path, linked, handoff, manifest_path


@pytest.mark.parametrize("changed,expected", [
    ("notebook", "notebook_changed"), ("source", "source_changed"),
    ("both", "both_changed"), ("handoff", "support_changed"), ("manifest_missing", "unverified"),
])
def test_export_sync_identifies_which_persisted_evidence_changed(export_bundle, changed, expected):
    export, path, linked, handoff, manifest = export_bundle
    if changed in ("notebook", "both"):
        data = json.loads(path.read_text())
        data["metadata"]["edited"] = True
        path.write_text(export.notebook_export_json_text(data))
    if changed in ("source", "both"):
        linked.write_text("print('changed analysis')\n")
    if changed == "handoff":
        handoff.write_text("changed handoff")
    if changed == "manifest_missing":
        manifest.unlink()
    status = export.notebook_view_sync_status(path)
    assert status["state"] == expected
    assert not status["ok"]
    assert status["notebook_changed"] is (changed in ("notebook", "both"))
    assert status["source_changed"] is (changed in ("source", "both"))
    assert status["handoff_changed"] is (changed == "handoff")


def test_export_missing_linked_source_is_reported_as_unavailable(export_bundle):
    export, path, linked, _, _ = export_bundle
    linked.unlink()
    status = export.notebook_view_sync_status(path)
    assert status["unavailable_source_count"] == 1
    assert status["changed_source_count"] == 0
    assert not status["source_changed"]


@pytest.mark.parametrize("raw", [None, [], {"sources": None}, {"sources": [None, {}, {"path": "missing"}]}])
def test_source_drift_ignores_records_without_comparable_evidence(raw):
    from agilab.notebooks import notebook_export_support as export
    checked, changed, unavailable, total = export._view_sync_source_drift({"view_sync": raw})
    assert checked == 0
    assert changed == unavailable == []
    assert total == (3 if isinstance(raw, dict) and isinstance(raw.get("sources"), list) else 0)


def test_export_verifier_rejects_non_object_manifest(export_bundle):
    export, path, _, _, manifest = export_bundle
    manifest.write_text("[]")
    with pytest.raises(ValueError, match="Expected JSON object"):
        export.verify_notebook_export_manifest(path)
