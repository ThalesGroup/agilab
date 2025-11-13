#!/usr/bin/env python3
"""
Export Codex shell command history and aggregated statistics in one pass.

Outputs (written to ./codex by default unless --output-dir is set):
  - codex_shell_history.tsv
  - codex_shell_command_stats.tsv
  - codex_shell_command_main_stats.tsv
  - codex_shell_summary.md
"""

from __future__ import annotations

import argparse
import json
import shlex
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence


DEFAULT_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
DEFAULT_OUTPUT_DIR = Path.cwd() / "codex"


@dataclass
class ShellRecord:
    timestamp_raw: str | None
    timestamp: datetime | None
    command: Sequence[str]
    workdir: str
    source_log: str

    @property
    def command_str(self) -> str:
        return " ".join(self.command).replace("\n", " ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=DEFAULT_SESSIONS_ROOT,
        help=f"Root directory that stores Codex session JSONL logs (default: {DEFAULT_SESSIONS_ROOT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory where TSV outputs are written (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def iter_shell_records(root: Path) -> Iterator[ShellRecord]:
    if not root.exists():
        return iter(())
    jsonl_paths = sorted(root.rglob("*.jsonl"))
    for jsonl_path in jsonl_paths:
        try:
            with jsonl_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "response_item":
                        continue
                    payload = obj.get("payload") or {}
                    if payload.get("type") != "function_call" or payload.get("name") != "shell":
                        continue
                    args_raw = payload.get("arguments") or "{}"
                    try:
                        args = json.loads(args_raw)
                    except json.JSONDecodeError:
                        continue
                    command = args.get("command")
                    if not isinstance(command, list):
                        continue
                    workdir = args.get("workdir") or ""
                    ts_raw = obj.get("timestamp")
                    yield ShellRecord(
                        timestamp_raw=ts_raw,
                        timestamp=parse_timestamp(ts_raw),
                        command=command,
                        workdir=workdir,
                        source_log=str(jsonl_path),
                    )
        except OSError:
            continue


def parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def tokenize_script(script: str) -> List[str]:
    try:
        return shlex.split(script)
    except ValueError:
        return script.split()


def extract_inner_command(record: ShellRecord) -> str:
    cmd = record.command
    if len(cmd) >= 3 and cmd[0] == "bash" and cmd[1] == "-lc":
        return cmd[2]
    if len(cmd) >= 3 and cmd[0] == "/bin/zsh" and cmd[1] == "-lc":
        return cmd[2]
    return record.command_str


def extract_part2_token(record: ShellRecord) -> str:
    cmd = record.command
    if len(cmd) >= 3 and cmd[0] == "bash" and cmd[1] == "-lc":
        tokens = tokenize_script(cmd[2])
        return tokens[0] if tokens else ""
    if len(cmd) >= 3 and cmd[0] == "/bin/zsh" and cmd[1] == "-lc":
        tokens = tokenize_script(cmd[2])
        return tokens[0] if tokens else ""
    tokens = tokenize_script(record.command_str)
    if tokens:
        return tokens[0]
    return ""


def extract_main_command(record: ShellRecord) -> str:
    cmd = record.command
    if len(cmd) >= 3 and cmd[0] in {"bash", "/bin/bash", "/usr/bin/bash"} and cmd[1] == "-lc":
        tokens = tokenize_script(cmd[2])
        return tokens[0] if tokens else ""
    if len(cmd) >= 3 and cmd[0] in {"zsh", "/bin/zsh"} and cmd[1] == "-lc":
        tokens = tokenize_script(cmd[2])
        return tokens[0] if tokens else ""
    tokens = tokenize_script(record.command_str)
    return tokens[0] if tokens else ""


def write_tsv(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")


def format_ts(ts: datetime | None) -> str:
    return ts.isoformat() if ts else ""


def build_history(records: Sequence[ShellRecord]) -> List[List[str]]:
    return [
        [rec.timestamp_raw or "", rec.command_str, rec.workdir, rec.source_log]
        for rec in records
    ]


def aggregate_by_key(
    records: Sequence[ShellRecord],
    key_fn,
) -> List[List[str]]:
    buckets: Dict[str, Dict[str, object]] = {}

    for rec in records:
        key = key_fn(rec)
        bucket = buckets.setdefault(
            key,
            {
                "count": 0,
                "first": None,
                "last": None,
                "workdirs": set(),
                "sources": set(),
                "examples": set(),
            },
        )
        bucket["count"] = bucket["count"] + 1  # type: ignore[operator]
        ts = rec.timestamp
        if ts is not None:
            if bucket["first"] is None or ts < bucket["first"]:  # type: ignore[operator]
                bucket["first"] = ts  # type: ignore[assignment]
            if bucket["last"] is None or ts > bucket["last"]:  # type: ignore[operator]
                bucket["last"] = ts  # type: ignore[assignment]
        bucket["workdirs"].add(rec.workdir)  # type: ignore[arg-type]
        bucket["sources"].add(rec.source_log)  # type: ignore[arg-type]
        bucket["examples"].add(rec.command_str)  # type: ignore[arg-type]

    rows: List[List[str]] = []
    for key, bucket in sorted(buckets.items(), key=lambda kv: (-kv[1]["count"], kv[0])):  # type: ignore[index]
        rows.append(
            [
                key,
                str(bucket["count"]),
                format_ts(bucket["first"]),
                format_ts(bucket["last"]),
                str(len(bucket["workdirs"])),
                str(len(bucket["sources"])),
                "; ".join(sorted(bucket["examples"])),
            ]
        )
    return rows


def format_counter(counter: Counter, limit: int) -> List[str]:
    return [f"{item} ({count})" for item, count in counter.most_common(limit)]


def build_summary_report(records: Sequence[ShellRecord]) -> str:
    total = len(records)
    timestamps = [rec.timestamp for rec in records if rec.timestamp]
    first = min(timestamps) if timestamps else None
    last = max(timestamps) if timestamps else None
    per_day = Counter(
        rec.timestamp.date() for rec in records if rec.timestamp
    )
    workdirs = Counter(rec.workdir or "." for rec in records)
    sources = Counter(rec.source_log for rec in records)
    main_cmds = Counter(extract_main_command(rec) for rec in records)
    inner_cmds = Counter(extract_inner_command(rec) for rec in records)

    lines = [
        "# Codex Shell Activity Report",
        "",
        f"- Total shell commands: **{total:,}**",
    ]
    if first and last:
        span_days = (last.date() - first.date()).days + 1
        lines.append(f"- Date range: **{first.isoformat()} → {last.isoformat()}** ({span_days} days)")
    if per_day:
        avg = total / max(len(per_day), 1)
        peak_day, peak_count = per_day.most_common(1)[0]
        lines.append(f"- Active days: **{len(per_day)}** (avg {avg:.1f} cmds/day, peak {peak_count} on {peak_day})")
    lines.append("")
    lines.append("## Top commands")
    lines.append(f"1. Main commands: {', '.join(format_counter(main_cmds, 10)) or 'n/a'}")
    lines.append(f"2. Inner commands: {', '.join(format_counter(inner_cmds, 5)) or 'n/a'}")
    lines.append("")
    lines.append("## Top workdirs & logs")
    lines.append(f"- Workdirs: {', '.join(format_counter(workdirs, 5)) or 'n/a'}")
    lines.append(f"- Rollout logs: {', '.join(format_counter(sources, 3)) or 'n/a'}")
    lines.append("")
    lines.append("## Daily activity")
    for day, count in per_day.most_common(7):
        lines.append(f"- {day}: {count} commands")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    records = list(iter_shell_records(args.sessions_root))
    if not records:
        raise SystemExit(f"No shell calls found under {args.sessions_root}")

    history_rows = build_history(records)
    write_tsv(
        args.output_dir / "codex_shell_history.tsv",
        ("timestamp_utc", "command", "workdir", "source_log"),
        history_rows,
    )

    full_command_rows = aggregate_by_key(records, lambda rec: rec.command_str)
    write_tsv(
        args.output_dir / "codex_shell_command_stats.tsv",
        (
            "command",
            "count",
            "first_seen_utc",
            "last_seen_utc",
            "workdir_count",
            "source_log_count",
            "examples",
        ),
        full_command_rows,
    )

    main_rows = aggregate_by_key(records, extract_main_command)
    write_tsv(
        args.output_dir / "codex_shell_command_main_stats.tsv",
        (
            "main_command",
            "count",
            "first_seen_utc",
            "last_seen_utc",
            "workdir_count",
            "source_log_count",
            "examples",
        ),
        main_rows,
    )

    summary = build_summary_report(records)
    summary_path = args.output_dir / "codex_shell_summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
