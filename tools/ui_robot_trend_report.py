#!/usr/bin/env python3
"""Summarize AGILAB widget robot NDJSON progress logs for flakes and slow pages."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.ui_robot_trend_report.v1"


@dataclass
class PageTrend:
    app: str
    page: str
    runs: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    durations: list[float] = field(default_factory=list)
    failure_samples: list[str] = field(default_factory=list)

    @property
    def flaky(self) -> bool:
        return self.passed > 0 and self.failed > 0

    @property
    def max_duration_seconds(self) -> float:
        return max(self.durations or [0.0])

    @property
    def mean_duration_seconds(self) -> float:
        return sum(self.durations) / max(1, len(self.durations))

    def as_report(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "page": self.page,
            "runs": self.runs,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "flaky": self.flaky,
            "max_duration_seconds": self.max_duration_seconds,
            "mean_duration_seconds": self.mean_duration_seconds,
            "failure_samples": self.failure_samples[:5],
        }


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            records.append({"event": "parse_error", "path": str(path), "detail": line[:240]})
            continue
        if isinstance(payload, dict):
            payload.setdefault("_source", str(path))
            records.append(payload)
    return records


def discover_progress_logs(patterns: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = sorted(REPO_ROOT.glob(pattern)) if any(token in pattern for token in "*?[") else [Path(pattern)]
        for match in matches:
            path = match if match.is_absolute() else REPO_ROOT / match
            path = path.resolve(strict=False)
            if path.is_file() and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _failure_detail(record: Mapping[str, Any]) -> str:
    result = record.get("result")
    if not isinstance(result, dict):
        return str(record.get("status") or "failed")
    failures = result.get("failures")
    if isinstance(failures, list) and failures:
        first = failures[0]
        if isinstance(first, dict):
            return f"{first.get('kind', '')} {first.get('label', '')}: {first.get('detail', '')}".strip()
    return str(result.get("status") or record.get("status") or "failed")


def build_report(*, progress_logs: Sequence[Path], slow_page_seconds: float) -> dict[str, Any]:
    trends: dict[tuple[str, str], PageTrend] = {}
    parse_errors: list[dict[str, str]] = []
    event_count = 0
    for path in progress_logs:
        for record in _load_ndjson(path):
            event_count += 1
            if record.get("event") == "parse_error":
                parse_errors.append({"path": str(path), "detail": str(record.get("detail", ""))})
                continue
            if record.get("event") != "page_done":
                continue
            app = str(record.get("app") or "")
            page = str(record.get("page") or "")
            key = (app, page)
            trend = trends.setdefault(key, PageTrend(app=app, page=page))
            trend.runs += 1
            status = str(record.get("status") or "")
            success = bool(record.get("success", False))
            if success and status == "passed":
                trend.passed += 1
            elif status in {"skipped", "environment_blocked"}:
                trend.skipped += 1
            else:
                trend.failed += 1
                if len(trend.failure_samples) < 5:
                    trend.failure_samples.append(_failure_detail(record))
            try:
                trend.durations.append(float(record.get("duration_seconds", 0.0)))
            except (TypeError, ValueError):
                trend.durations.append(0.0)
    page_reports = [trend.as_report() for trend in sorted(trends.values(), key=lambda item: (item.app, item.page))]
    flaky = [item for item in page_reports if item["flaky"]]
    failed = [item for item in page_reports if item["failed"]]
    slow = [item for item in page_reports if item["max_duration_seconds"] > slow_page_seconds]
    return {
        "schema": SCHEMA,
        "success": not parse_errors,
        "progress_logs": [str(path) for path in progress_logs],
        "event_count": event_count,
        "summary": {
            "page_count": len(page_reports),
            "failed_page_count": len(failed),
            "flaky_page_count": len(flaky),
            "slow_page_count": len(slow),
            "parse_error_count": len(parse_errors),
        },
        "failed_pages": failed,
        "flaky_pages": flaky,
        "slow_pages": slow,
        "pages": page_reports,
        "parse_errors": parse_errors,
    }


def render_human(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "AGILAB UI robot trend report",
        f"verdict: {'PASS' if report.get('success') else 'FAIL'}",
        (
            f"pages={summary.get('page_count', 0)} failed={summary.get('failed_page_count', 0)} "
            f"flaky={summary.get('flaky_page_count', 0)} slow={summary.get('slow_page_count', 0)}"
        ),
    ]
    for item in report.get("flaky_pages", [])[:10]:
        lines.append(f"- flaky: {item.get('app')}/{item.get('page')} passed={item.get('passed')} failed={item.get('failed')}")
    for item in report.get("failed_pages", [])[:10]:
        lines.append(f"- failed: {item.get('app')}/{item.get('page')} failed={item.get('failed')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress-log", action="append", type=Path, default=[])
    parser.add_argument("--glob", action="append", default=["test-results/**/*.ndjson"])
    parser.add_argument("--slow-page-seconds", type=float, default=120.0)
    parser.add_argument("--strict", action="store_true", help="Fail when failed or flaky pages are found.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    paths = [path.resolve(strict=False) for path in args.progress_log if path.exists()]
    paths.extend(path for path in discover_progress_logs(args.glob) if path not in paths)
    report = build_report(progress_logs=paths, slow_page_seconds=args.slow_page_seconds)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_human(report))
    if not report["success"]:
        return 1
    summary = report["summary"]
    if args.strict and (summary["failed_page_count"] or summary["flaky_page_count"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
