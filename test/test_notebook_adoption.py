import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from agilab.agent_runtime.notebook_adoption import (
    github_report_url, summarize, validate_receipt, write_completion_receipt,
)


def _record(root: Path, status="passed") -> dict:
    root.mkdir()
    write_completion_receipt(root, {
        "status": status, "seconds": 320,
        "source": {"source_kind": "local", "url": "file:///private/notebook.ipynb"},
        "verification_scope": "execution_and_interface",
        "request": "private prompt", "error": "secret credentials",
    })
    return json.loads((root / "completion_receipt.json").read_text())


def test_receipts_count_first_success_per_workspace_and_deduplicate(tmp_path):
    failed = _record(tmp_path / "attempt1", "failed")
    first = _record(tmp_path / "attempt2")
    second = _record(tmp_path / "attempt3")
    report = summarize([failed, first, first, second])
    assert report["reported_builds"] == 3
    assert report["reported_completed_builds"] == 2
    assert report["reported_first_builds"] == 1
    assert report["visitor_conversion_rate"] is None


def test_receipt_redacts_payload_and_github_link_is_only_a_draft(tmp_path):
    receipt = _record(tmp_path / "run")
    serialized = json.dumps(receipt)
    assert not any(value in serialized for value in ("private", "secret", "credentials", str(tmp_path)))
    url = urlparse(github_report_url(receipt))
    assert url.netloc == "github.com"
    assert url.path == "/ThalesGroup/agilab/issues/new"
    assert receipt["receipt_id"] in parse_qs(url.query)["body"][0]


def test_pending_run_does_not_create_completion_receipt(tmp_path):
    write_completion_receipt(tmp_path, {"status": "running"})
    assert not (tmp_path / "completion_receipt.json").exists()


def test_unknown_fields_and_conflicting_receipts_fail_closed(tmp_path):
    receipt = _record(tmp_path / "run")
    with pytest.raises(ValueError):
        validate_receipt({**receipt, "notebook": "private content"})
    with pytest.raises(ValueError):
        summarize([receipt, {**receipt, "status": "failed"}])


def test_rewriting_terminal_result_keeps_receipt_identifier(tmp_path):
    root = tmp_path / "run"
    receipt = _record(root)
    write_completion_receipt(root, {"status": "passed", "seconds": 1})
    assert json.loads((root / "completion_receipt.json").read_text())["receipt_id"] == receipt["receipt_id"]
