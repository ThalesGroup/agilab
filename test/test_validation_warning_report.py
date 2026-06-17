from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validation_warning_report.py"

spec = importlib.util.spec_from_file_location("validation_warning_report", MODULE_PATH)
assert spec is not None and spec.loader is not None
validation_warning_report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validation_warning_report
spec.loader.exec_module(validation_warning_report)


def test_warning_report_summarizes_log_warning_and_pytest_warning_count(tmp_path):
    log_path = tmp_path / "validation.log"
    log_path.write_text(
        "\n".join(
            [
                "python -m pytest --disable-warnings",
                (
                    "local-only-policy\tValidate first-launch robot\t"
                    "2026-06-17T11:03:28Z WARNING streamlit.runtime: "
                    "missing ScriptRunContext"
                ),
                "1904 passed, 9 skipped, 65 warnings in 167.51s (0:02:47)",
            ]
        ),
        encoding="utf-8",
    )

    report = validation_warning_report.build_report((tmp_path,))

    assert report["status"] == "warn"
    assert report["summary"]["warning_count"] == 66
    assert report["summary"]["unique_warning_count"] == 2
    assert {warning["category"] for warning in report["warnings"]} == {
        "log-warning",
        "pytest-warning-summary",
    }
    assert not any(
        "--disable-warnings" in warning["message"] for warning in report["warnings"]
    )


def test_warning_report_does_not_treat_warning_word_in_branch_name_as_warning(tmp_path):
    log_path = tmp_path / "validation.log"
    log_path.write_text(
        "- /repo: codex/validation-warning-cleanup 3819307\n",
        encoding="utf-8",
    )

    report = validation_warning_report.build_report((tmp_path,))

    assert report["status"] == "pass"
    assert report["summary"]["warning_count"] == 0


def test_warning_report_can_scan_only_files_newer_than_marker(tmp_path):
    old_log = tmp_path / "old.log"
    marker = tmp_path / "start.marker"
    new_log = tmp_path / "new.log"
    old_log.write_text("WARNING stale warning\n", encoding="utf-8")
    marker.write_text("start\n", encoding="utf-8")
    new_log.write_text("all good\n", encoding="utf-8")
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    marker_time = datetime.now(timezone.utc) - timedelta(hours=1)
    new_time = datetime.now(timezone.utc)
    os.utime(old_log, (old_time.timestamp(), old_time.timestamp()))
    os.utime(marker, (marker_time.timestamp(), marker_time.timestamp()))
    os.utime(new_log, (new_time.timestamp(), new_time.timestamp()))

    report = validation_warning_report.build_report(
        (tmp_path,), newer_than=validation_warning_report._parse_newer_than(str(marker))
    )

    assert report["status"] == "pass"
    assert report["summary"]["file_count"] == 1
    assert report["summary"]["warning_count"] == 0


def test_warning_report_allowlist_approves_matching_warning(tmp_path):
    log_path = tmp_path / "validation.log"
    log_path.write_text("WARNING streamlit.runtime: missing ScriptRunContext\n", encoding="utf-8")
    allowlist_path = tmp_path / "warning_allowlist.toml"
    allowlist_path.write_text(
        """
[[warnings]]
id = "streamlit-bare-mode"
category = "log-warning"
message = "missing ScriptRunContext"
source = "validation[.]log"
owner = "agilab"
expires = "2099-12-31"
reason = "Streamlit bare-mode validation emits this warning outside a script context."
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = validation_warning_report.build_report(
        (tmp_path,), allowlist_path=allowlist_path
    )

    assert report["status"] == "pass"
    assert report["summary"]["warning_count"] == 1
    assert report["summary"]["approved_warning_count"] == 1
    assert report["summary"]["unapproved_warning_count"] == 0
    assert report["warnings"][0]["allowlist_id"] == "streamlit-bare-mode"


def test_warning_report_source_allowlist_does_not_approve_other_sources(tmp_path):
    allowed_log = tmp_path / "allowed.log"
    other_log = tmp_path / "other.log"
    allowed_log.write_text("WARNING shared warning\n", encoding="utf-8")
    other_log.write_text("WARNING shared warning\n", encoding="utf-8")
    allowlist_path = tmp_path / "warning_allowlist.toml"
    allowlist_path.write_text(
        """
[[warnings]]
id = "approved-source"
category = "log-warning"
message = "shared warning"
source = "allowed[.]log"
expires = "2099-12-31"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = validation_warning_report.build_report(
        (tmp_path,), allowlist_path=allowlist_path
    )

    assert report["status"] == "warn"
    assert report["summary"]["warning_count"] == 2
    assert report["summary"]["approved_warning_count"] == 1
    assert report["summary"]["unapproved_warning_count"] == 1
    assert report["summary"]["unique_warning_count"] == 1
    assert sorted(warning["approved"] for warning in report["warnings"]) == [
        False,
        True,
    ]


def test_warning_report_expired_allowlist_rule_does_not_approve(tmp_path):
    log_path = tmp_path / "validation.log"
    log_path.write_text("WARNING old warning\n", encoding="utf-8")
    allowlist_path = tmp_path / "warning_allowlist.toml"
    allowlist_path.write_text(
        """
[[warnings]]
id = "expired-warning"
category = "log-warning"
message = "old warning"
expires = "2000-01-01"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = validation_warning_report.build_report(
        (tmp_path,), allowlist_path=allowlist_path
    )

    assert report["status"] == "warn"
    assert report["summary"]["unapproved_warning_count"] == 1
    assert report["summary"]["expired_allowlist_rule_count"] == 1
    assert report["expired_allowlist_rules"] == ["expired-warning"]


def test_warning_report_extracts_browser_warning_artifacts(tmp_path):
    artifact_path = tmp_path / "robot.json"
    artifact_path.write_text(
        """
{
  "success": true,
  "pages": [
    {
      "page": "ORCHESTRATE",
      "browser_issues": [
        {
          "kind": "console.warning",
          "detail": "console.warn('slow paint')"
        }
      ]
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = validation_warning_report.build_report((artifact_path,))

    assert report["summary"]["warning_count"] == 1
    assert report["warnings"][0]["category"] == "browser-warning"
    assert "slow paint" in report["warnings"][0]["message"]


def test_warning_report_strict_mode_fails_on_unapproved_warning(tmp_path, capsys):
    log_path = tmp_path / "validation.log"
    log_path.write_text("WARNING unapproved\n", encoding="utf-8")

    exit_code = validation_warning_report.main([str(log_path), "--strict"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unapproved=1" in captured.out


def test_warning_report_strict_mode_passes_without_warnings(tmp_path):
    log_path = tmp_path / "validation.log"
    log_path.write_text("all good\n", encoding="utf-8")

    assert validation_warning_report.main([str(log_path), "--strict"]) == 0
