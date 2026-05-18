from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/ui_robot_trend_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_trend_report_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_ui_robot_trend_report_detects_flaky_and_slow_pages(tmp_path) -> None:
    module = _load_module()
    log = tmp_path / "robot.ndjson"
    _write_records(
        log,
        [
            {
                "event": "page_done",
                "app": "flight",
                "page": "PROJECT",
                "status": "passed",
                "success": True,
                "duration_seconds": 2.0,
                "result": {"failures": []},
            },
            {
                "event": "page_done",
                "app": "flight",
                "page": "PROJECT",
                "status": "failed",
                "success": False,
                "duration_seconds": 140.0,
                "result": {"failures": [{"kind": "browser_error", "label": "pageerror", "detail": "broken"}]},
            },
        ],
    )

    report = module.build_report(progress_logs=[log], slow_page_seconds=120.0)

    assert report["schema"] == module.SCHEMA
    assert report["summary"]["page_count"] == 1
    assert report["summary"]["flaky_page_count"] == 1
    assert report["summary"]["slow_page_count"] == 1
    assert report["flaky_pages"][0]["page"] == "PROJECT"
    assert "browser_error" in report["failed_pages"][0]["failure_samples"][0]


def test_ui_robot_trend_report_json_cli_writes_output(tmp_path, capsys) -> None:
    module = _load_module()
    log = tmp_path / "robot.ndjson"
    output = tmp_path / "trend.json"
    _write_records(
        log,
        [
            {
                "event": "page_done",
                "app": "flight",
                "page": "ANALYSIS",
                "status": "passed",
                "success": True,
                "duration_seconds": 1.0,
            }
        ],
    )

    exit_code = module.main(["--progress-log", str(log), "--glob", "no-match/**/*.ndjson", "--output", str(output), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["page_count"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == module.SCHEMA


def test_ui_robot_trend_report_tracks_parse_errors_skips_and_bad_durations(tmp_path) -> None:
    module = _load_module()
    log = tmp_path / "robot.ndjson"
    log.write_text(
        "\n".join(
            [
                "",
                "{not-json",
                json.dumps({"event": "heartbeat", "status": "ignored"}),
                json.dumps(
                    {
                        "event": "page_done",
                        "app": "flight",
                        "page": "SETTINGS",
                        "status": "environment_blocked",
                        "success": False,
                        "duration_seconds": "bad",
                    }
                ),
                json.dumps(
                    {
                        "event": "page_done",
                        "app": "flight",
                        "page": "WORKFLOW",
                        "status": "failed",
                        "success": False,
                        "duration_seconds": None,
                        "result": "not-a-dict",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = module.build_report(progress_logs=[log], slow_page_seconds=120.0)

    assert report["success"] is False
    assert report["summary"]["parse_error_count"] == 1
    assert report["summary"]["page_count"] == 2
    settings = next(page for page in report["pages"] if page["page"] == "SETTINGS")
    workflow = next(page for page in report["pages"] if page["page"] == "WORKFLOW")
    assert settings["skipped"] == 1
    assert settings["mean_duration_seconds"] == 0.0
    assert workflow["failed"] == 1
    assert workflow["failure_samples"] == ["failed"]


def test_ui_robot_trend_report_discovers_progress_logs_once(tmp_path, monkeypatch) -> None:
    module = _load_module()
    log = tmp_path / "test-results" / "a.ndjson"
    _write_records(log, [{"event": "page_done", "app": "flight", "page": "PROJECT", "status": "passed", "success": True}])
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    paths = module.discover_progress_logs(["test-results/*.ndjson", str(log)])

    assert paths == [log.resolve()]


def test_ui_robot_trend_report_strict_cli_fails_on_failed_pages(tmp_path, capsys) -> None:
    module = _load_module()
    log = tmp_path / "robot.ndjson"
    _write_records(
        log,
        [
            {
                "event": "page_done",
                "app": "flight",
                "page": "ANALYSIS",
                "status": "failed",
                "success": False,
                "duration_seconds": 1.0,
            }
        ],
    )

    exit_code = module.main(["--progress-log", str(log), "--glob", "no-match/**/*.ndjson", "--strict"])

    assert exit_code == 1
    assert "verdict: PASS" in capsys.readouterr().out
