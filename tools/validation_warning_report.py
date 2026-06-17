#!/usr/bin/env python3
"""Summarize validation warnings from local AGILAB validation artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = (REPO_ROOT / "reports" / "dev-logs",)
SCHEMA = "agilab.validation_warning_report.v1"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TIMESTAMP_PREFIX_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\s+(?P<message>.*)"
)
PYTEST_WARNING_SUMMARY_RE = re.compile(r"\b(?P<count>\d+) warnings? in\b")
WARNING_CLASS_RE = re.compile(
    r"\b(?:PytestConfigWarning|PytestWarning|DeprecationWarning|"
    r"FutureWarning|RuntimeWarning|ResourceWarning|UserWarning)\b"
)
WARNING_LINE_RE = re.compile(
    r"(?i)(::warning|##\[warning\]|\bWARNING\b|\bwarning\s+-|\bwarning:)"
)
SUPPORTED_SUFFIXES = {".log", ".txt", ".out", ".err", ".json", ".ndjson"}


@dataclass(frozen=True)
class WarningOccurrence:
    source: Path
    line: int
    category: str
    message: str
    raw: str
    count: int = 1


@dataclass(frozen=True)
class WarningGroup:
    warning_id: str
    category: str
    message: str
    count: int
    sources: tuple[str, ...]
    examples: tuple[dict[str, Any], ...]
    approved: bool
    allowlist_id: str | None


@dataclass(frozen=True)
class AllowRule:
    rule_id: str
    fingerprint: str | None
    category: str | None
    message_pattern: re.Pattern[str] | None
    source_pattern: re.Pattern[str] | None
    owner: str | None
    expires: date | None
    reason: str | None

    @property
    def expired(self) -> bool:
        return self.expires is not None and self.expires < date.today()

    def matches(self, occurrence: WarningOccurrence, warning_id: str) -> bool:
        if self.expired:
            return False
        if self.fingerprint and self.fingerprint != warning_id:
            return False
        if self.category and self.category != occurrence.category:
            return False
        if self.message_pattern and not self.message_pattern.search(
            f"{occurrence.message}\n{occurrence.raw}"
        ):
            return False
        if self.source_pattern and not self.source_pattern.search(
            _display_path(occurrence.source)
        ):
            return False
        return any(
            (
                self.fingerprint,
                self.category,
                self.message_pattern,
                self.source_pattern,
            )
        )


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _extract_message(line: str) -> str:
    message = _strip_ansi(line).strip()
    if "\t" in message:
        message = message.split("\t")[-1].strip()
    timestamp_match = TIMESTAMP_PREFIX_RE.search(message)
    if timestamp_match:
        message = timestamp_match.group("message").strip()
    return re.sub(r"\s+", " ", message)


def _normalize_message(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message.strip())
    normalized = re.sub(r"\b0x[0-9a-fA-F]+\b", "0x...", normalized)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}T[^\s]+\b", "<timestamp>", normalized)
    return normalized


def _warning_id(category: str, message: str) -> str:
    payload = f"{category}\0{_normalize_message(message)}"
    return sha256(payload.encode("utf-8", "replace")).hexdigest()[:16]


def _classify_line(path: Path, line_number: int, line: str) -> WarningOccurrence | None:
    message = _extract_message(line)
    if not message:
        return None

    pytest_summary = PYTEST_WARNING_SUMMARY_RE.search(message)
    if pytest_summary:
        count = int(pytest_summary.group("count"))
        return WarningOccurrence(
            source=path,
            line=line_number,
            category="pytest-warning-summary",
            message=f"pytest reported {count} warnings",
            raw=line.rstrip(),
            count=count,
        )

    if WARNING_CLASS_RE.search(message):
        return WarningOccurrence(
            source=path,
            line=line_number,
            category="python-warning",
            message=message,
            raw=line.rstrip(),
        )

    if WARNING_LINE_RE.search(message):
        return WarningOccurrence(
            source=path,
            line=line_number,
            category="log-warning",
            message=message,
            raw=line.rstrip(),
        )

    return None


def _browser_warning_from_issue(
    path: Path, issue: Any, *, line_number: int
) -> WarningOccurrence | None:
    if not isinstance(issue, dict):
        return None
    kind = str(issue.get("kind") or issue.get("type") or "browser").strip()
    detail = str(
        issue.get("detail")
        or issue.get("message")
        or issue.get("text")
        or issue.get("url")
        or ""
    ).strip()
    payload = f"{kind}: {detail}".strip(": ")
    lower = payload.lower()
    if not payload or ("warn" not in lower and "warning" not in lower):
        return None
    return WarningOccurrence(
        source=path,
        line=line_number,
        category="browser-warning",
        message=payload,
        raw=json.dumps(issue, sort_keys=True),
    )


def _walk_browser_issues(
    path: Path, value: Any, *, line_number: int
) -> Iterable[WarningOccurrence]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"browser_issues", "browserIssues"} and isinstance(child, list):
                for issue in child:
                    warning = _browser_warning_from_issue(
                        path, issue, line_number=line_number
                    )
                    if warning:
                        yield warning
            else:
                yield from _walk_browser_issues(path, child, line_number=line_number)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_browser_issues(path, item, line_number=line_number)


def _scan_text(path: Path) -> list[WarningOccurrence]:
    warnings: list[WarningOccurrence] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        warning = _classify_line(path, line_number, line)
        if warning:
            warnings.append(warning)
    return warnings


def _scan_json(path: Path) -> list[WarningOccurrence]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _scan_text(path)
    return list(_walk_browser_issues(path, payload, line_number=1))


def _scan_ndjson(path: Path) -> list[WarningOccurrence]:
    warnings: list[WarningOccurrence] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            warning = _classify_line(path, line_number, line)
            if warning:
                warnings.append(warning)
            continue
        warnings.extend(_walk_browser_issues(path, payload, line_number=line_number))
    return warnings


def _scan_file(path: Path) -> list[WarningOccurrence]:
    if path.suffix == ".json":
        return _scan_json(path)
    if path.suffix == ".ndjson":
        return _scan_ndjson(path)
    return _scan_text(path)


def _iter_input_files(paths: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix in SUPPORTED_SUFFIXES:
                files.append(path)
            continue
        for candidate in sorted(path.rglob("*")):
            if candidate.is_file() and candidate.suffix in SUPPORTED_SUFFIXES:
                files.append(candidate)
    return sorted(files)


def _compile_regex(value: object, *, field: str, rule_id: str) -> re.Pattern[str] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"warning allowlist rule {rule_id}: {field} must be a string")
    try:
        return re.compile(value)
    except re.error as exc:
        raise ValueError(
            f"warning allowlist rule {rule_id}: invalid {field} regex: {exc}"
        ) from exc


def _parse_expiry(value: object, *, rule_id: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"warning allowlist rule {rule_id}: expires must be YYYY-MM-DD"
            ) from exc
    raise ValueError(f"warning allowlist rule {rule_id}: expires must be a date")


def load_allowlist(path: Path | None) -> list[AllowRule]:
    if path is None or not path.exists():
        return []
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_rules = payload.get("warnings") or payload.get("allow") or payload.get("rules") or []
    if not isinstance(raw_rules, list):
        raise ValueError("warning allowlist must contain a list named warnings, allow, or rules")

    rules: list[AllowRule] = []
    for index, item in enumerate(raw_rules, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"warning allowlist rule {index}: rule must be a table")
        rule_id = str(item.get("id") or f"rule-{index}")
        owner = item.get("owner")
        reason = item.get("reason")
        rules.append(
            AllowRule(
                rule_id=rule_id,
                fingerprint=str(item["fingerprint"])
                if item.get("fingerprint") not in (None, "")
                else None,
                category=str(item["category"])
                if item.get("category") not in (None, "")
                else None,
                message_pattern=_compile_regex(
                    item.get("message"), field="message", rule_id=rule_id
                ),
                source_pattern=_compile_regex(
                    item.get("source"), field="source", rule_id=rule_id
                ),
                owner=str(owner) if owner not in (None, "") else None,
                expires=_parse_expiry(item.get("expires"), rule_id=rule_id),
                reason=str(reason) if reason not in (None, "") else None,
            )
        )
    return rules


def _allowance_for(
    occurrence: WarningOccurrence, warning_id: str, rules: Sequence[AllowRule]
) -> str | None:
    for rule in rules:
        if rule.matches(occurrence, warning_id):
            return rule.rule_id
    return None


def build_report(
    paths: Sequence[Path],
    *,
    allowlist_path: Path | None = None,
    max_examples: int = 3,
) -> dict[str, Any]:
    files = _iter_input_files(paths)
    rules = load_allowlist(allowlist_path)
    occurrences = [warning for file in files for warning in _scan_file(file)]

    grouped: dict[tuple[str, str], list[WarningOccurrence]] = {}
    for occurrence in occurrences:
        warning_id = _warning_id(occurrence.category, occurrence.message)
        grouped.setdefault((warning_id, occurrence.category), []).append(occurrence)

    warning_groups: list[WarningGroup] = []
    for (warning_id, category), group_occurrences in sorted(grouped.items()):
        first = group_occurrences[0]
        allowlist_id = _allowance_for(first, warning_id, rules)
        examples = tuple(
            {
                "source": _display_path(item.source),
                "line": item.line,
                "message": item.message,
                "raw": item.raw,
            }
            for item in group_occurrences[:max_examples]
        )
        warning_groups.append(
            WarningGroup(
                warning_id=warning_id,
                category=category,
                message=first.message,
                count=sum(item.count for item in group_occurrences),
                sources=tuple(
                    sorted({_display_path(item.source) for item in group_occurrences})
                ),
                examples=examples,
                approved=allowlist_id is not None,
                allowlist_id=allowlist_id,
            )
        )

    approved_count = sum(group.count for group in warning_groups if group.approved)
    total_count = sum(group.count for group in warning_groups)
    unapproved_count = total_count - approved_count
    expired_rules = [rule.rule_id for rule in rules if rule.expired]

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paths": [_display_path(path) for path in paths],
        "allowlist": _display_path(allowlist_path) if allowlist_path else None,
        "status": "pass" if unapproved_count == 0 else "warn",
        "summary": {
            "file_count": len(files),
            "warning_count": total_count,
            "unique_warning_count": len(warning_groups),
            "approved_warning_count": approved_count,
            "unapproved_warning_count": unapproved_count,
            "expired_allowlist_rule_count": len(expired_rules),
        },
        "expired_allowlist_rules": expired_rules,
        "warnings": [
            {
                "id": group.warning_id,
                "category": group.category,
                "message": group.message,
                "count": group.count,
                "sources": list(group.sources),
                "approved": group.approved,
                "allowlist_id": group.allowlist_id,
                "examples": list(group.examples),
            }
            for group in warning_groups
        ],
    }


def _render_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        (
            "validation warnings: "
            f"status={report['status']} "
            f"warnings={summary['warning_count']} "
            f"unique={summary['unique_warning_count']} "
            f"unapproved={summary['unapproved_warning_count']} "
            f"files={summary['file_count']}"
        )
    ]
    if report["expired_allowlist_rules"]:
        lines.append(
            "expired allowlist rules: " + ", ".join(report["expired_allowlist_rules"])
        )
    for warning in report["warnings"][:20]:
        approval = (
            f"approved:{warning['allowlist_id']}"
            if warning["approved"]
            else "unapproved"
        )
        lines.append(
            f"- {warning['category']} {warning['id']} count={warning['count']} "
            f"{approval}: {warning['message']}"
        )
        if warning["sources"]:
            lines.append(f"  source: {warning['sources'][0]}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Validation log or robot artifact files/directories to scan. Defaults to reports/dev-logs.",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        help="Optional TOML allowlist with [[warnings]] rules.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when unapproved warnings are present.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--output", type=Path, help="Write the JSON report to a file.")
    parser.add_argument(
        "--max-examples",
        type=int,
        default=3,
        help="Maximum examples retained per warning group.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = tuple(Path(item) for item in args.paths) or DEFAULT_INPUTS
    try:
        report = build_report(
            paths,
            allowlist_path=args.allowlist,
            max_examples=max(args.max_examples, 0),
        )
    except (OSError, ValueError) as exc:
        print(f"validation warning report failed: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_render_text(report))

    if args.strict and report["summary"]["unapproved_warning_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
