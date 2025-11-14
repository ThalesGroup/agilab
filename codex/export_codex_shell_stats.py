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
import re
import shlex
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence


DEFAULT_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
DEFAULT_OUTPUT_DIR = Path.cwd() / "codex"
FILE_PATTERN = re.compile(
    r"([A-Za-z0-9_./\-]+(?:/[A-Za-z0-9_./\-]+)*\.(?:py|rst|md|sh|txt|toml|ini|html|cfg))"
)
COMMAND_USAGE = {
    "rg": ("ripgrep search over tracked files", "`rg <pattern> [path]`"),
    "sed": ("text slicing/substitution", "`sed -n 'start,endp' file`"),
    "python3": ("run Python tooling/scripts", "`python3 path/to/script.py`"),
    "ls": ("list directory contents", "`ls -al path`"),
    "git": ("inspect repo state/history", "`git status -sb`"),
    "uv": ("manage envs or run tools", "`uv run python script.py`"),
    "ssh": ("check remote hosts", "`ssh user@host`"),
    "nl": ("print files with line numbers", "`nl -ba file`"),
    "cat": ("show file contents", "`cat file`"),
    "cd": ("change directory before chained commands", "`bash -lc \"cd path && …\"`"),
    "perl": ("run perl one-liners/in-place edits", "`perl -pi -e 's/old/new/' file`"),
}


def get_command_help(command: str) -> tuple[str, str]:
    if command in COMMAND_USAGE:
        return COMMAND_USAGE[command]

    if not command:
        return ("shell dispatcher", "n/a")

    if command.startswith("./") or command.endswith(".sh"):
        return ("execute project script", "`./script.sh`")
    if command.startswith("python"):
        return ("call python interpreter", "`python <script>`")
    head = command.split()[0]
    if head.startswith("PYTHONPATH=") or head.startswith("AGILAB_") or "=" in head:
        return ("inline environment assignment", "`VAR=value command`")
    if command.startswith("/Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project/.venv/bin/python") or command.startswith("/Users/example/PycharmProjects/agilab/src/agilab/apps/example_app_project/.venv/bin/python"):
        return ("call project virtualenv python", "`<app>/.venv/bin/python script.py`")
    if command.startswith("/"):
        return ("execute absolute-path binary/script", "`/path/to/binary`")
    if command.endswith(".py"):
        return ("run python module/script", "`python path/to/file.py`")
    return ("shell command/snippet", f"`{head}`")


def is_env_assignment_command(command: str) -> bool:
    return is_env_assignment(command)


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


@dataclass
class SessionFileStat:
    session: str
    file_count: int
    docs_count: int
    tests_count: int
    install_count: int
    sample_paths: List[str]


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


def is_env_assignment(token: str | None) -> bool:
    if not token:
        return False
    if "=" not in token:
        return False
    if token.startswith((">", "<", "|")):
        return False
    if token.endswith("="):
        return False
    return True


def strip_env_assignments(tokens: List[str]) -> List[str]:
    idx = 0
    while idx < len(tokens) and is_env_assignment(tokens[idx]):
        idx += 1
    return tokens[idx:]


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
        tokens = strip_env_assignments(tokenize_script(cmd[2]))
        return tokens[0] if tokens else ""
    if len(cmd) >= 3 and cmd[0] == "/bin/zsh" and cmd[1] == "-lc":
        tokens = strip_env_assignments(tokenize_script(cmd[2]))
        return tokens[0] if tokens else ""
    tokens = strip_env_assignments(tokenize_script(record.command_str))
    if tokens:
        return tokens[0]
    return ""


def extract_main_command(record: ShellRecord) -> str:
    cmd = record.command
    if len(cmd) >= 3 and cmd[0] in {"bash", "/bin/bash", "/usr/bin/bash"} and cmd[1] == "-lc":
        tokens = tokenize_script(cmd[2])
        stripped = strip_env_assignments(tokens)
        if stripped:
            return stripped[0]
        for token in reversed(tokens):
            if is_env_assignment(token):
                return token
        return tokens[0] if tokens else ""
    if len(cmd) >= 3 and cmd[0] in {"zsh", "/bin/zsh"} and cmd[1] == "-lc":
        tokens = tokenize_script(cmd[2])
        stripped = strip_env_assignments(tokens)
        if stripped:
            return stripped[0]
        for token in reversed(tokens):
            if is_env_assignment(token):
                return token
        return tokens[0] if tokens else ""
    tokens = tokenize_script(record.command_str)
    stripped = strip_env_assignments(tokens)
    if stripped:
        return stripped[0]
    for token in reversed(tokens):
        if is_env_assignment(token):
            return token
    return tokens[0] if tokens else ""


def extract_text_chunks(obj: dict) -> List[str]:
    chunks: List[str] = []
    payload = obj.get("payload")
    if isinstance(payload, dict):
        for key in ("message", "output", "content"):
            val = payload.get(key)
            if isinstance(val, str):
                chunks.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
    for key in ("message", "output"):
        val = obj.get(key)
        if isinstance(val, str):
            chunks.append(val)
    return chunks


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


def collect_session_file_stats(root: Path) -> List[SessionFileStat]:
    if not root.exists():
        return []

    stats: List[SessionFileStat] = []
    jsonl_paths = sorted(root.rglob("*.jsonl"))
    for jsonl_path in jsonl_paths:
        files: set[str] = set()
        try:
            with jsonl_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for chunk in extract_text_chunks(obj):
                        for match in FILE_PATTERN.findall(chunk):
                            files.add(match)
        except OSError:
            continue

        if not files:
            continue

        docs = {path for path in files if path.startswith("docs/") or "/docs/" in path}
        tests = {path for path in files if "test" in path.lower()}
        installs = {
            path
            for path in files
            if "install" in path.lower() or "setup" in path.lower()
        }
        samples = sorted(files)[:3]
        try:
            session_label = str(jsonl_path.relative_to(root))
        except ValueError:
            session_label = jsonl_path.name
        stats.append(
            SessionFileStat(
                session=session_label,
                file_count=len(files),
                docs_count=len(docs),
                tests_count=len(tests),
                install_count=len(installs),
                sample_paths=samples,
            )
        )

    stats.sort(key=lambda item: item.file_count, reverse=True)
    return stats


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


def build_markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return ""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def build_summary_report(
    records: Sequence[ShellRecord],
    session_stats: Sequence[SessionFileStat],
) -> str:
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
    for day, count in sorted(per_day.items()):
        lines.append(f"- {day}: {count} commands")

    lines.append("")
    lines.append("## Heavy-hitter logs (all sessions)")
    heavy_rows = [
        [
            stat.session,
            str(stat.file_count),
            str(stat.docs_count),
            str(stat.tests_count),
            str(stat.install_count),
        ]
        for stat in session_stats
    ]
    if heavy_rows:
        lines.append(build_markdown_table(["Session", "Files", "Docs", "Tests", "Install"], heavy_rows))
    else:
        lines.append("_No session file references found._")

    lines.append("")
    lines.append("## Session file impact")
    impact_rows = [
        [
            stat.session,
            str(stat.file_count),
            str(stat.docs_count),
            str(stat.tests_count),
            str(stat.install_count),
            "; ".join(stat.sample_paths),
        ]
        for stat in session_stats
    ]
    if impact_rows:
        lines.append(
            build_markdown_table(
                ["Session", "Files", "Docs", "Tests", "Install", "Sample paths"],
                impact_rows,
            )
        )
    else:
        lines.append("_No file impact to report._")

    lines.append("")
    lines.append("## Annex: Command usage")
    annex_rows = []
    filtered_cmds = [(cmd, cnt) for cmd, cnt in main_cmds.most_common() if not is_env_assignment_command(cmd)]
    for command, count in filtered_cmds[:10]:
        description, usage = get_command_help(command)
        annex_rows.append(
            [
                command or "—",
                str(count),
                description or "—",
                usage or "—",
            ]
        )
    if annex_rows:
        lines.append(
            build_markdown_table(
                ["Command", "Count", "Purpose", "Typical usage"],
                annex_rows,
            )
        )
    else:
        lines.append("_No commands recorded._")

    lines.append("")
    lines.append("## Command reference")
    reference_rows = []
    for command, count in sorted(filtered_cmds, key=lambda kv: (-kv[1], kv[0])):
        if not command:
            continue
        description, usage = get_command_help(command)
        reference_rows.append(
            [
                command,
                str(count),
                description or "—",
                usage or "—",
            ]
        )
    if reference_rows:
        lines.append(
            build_markdown_table(
                ["Command", "Count", "Purpose", "Typical usage"],
                reference_rows,
            )
        )
    else:
        lines.append("_No commands recorded._")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    records = list(iter_shell_records(args.sessions_root))
    if not records:
        raise SystemExit(f"No shell calls found under {args.sessions_root}")
    session_stats = collect_session_file_stats(args.sessions_root)

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

    summary = build_summary_report(records, session_stats)
    summary_path = args.output_dir / "codex_shell_summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary + "\n", encoding="utf-8")

    summary_tsv = args.output_dir / "codex_shell_summary.tsv"
    write_tsv(
        summary_tsv,
        ("session", "files", "docs", "tests", "installs", "sample_paths"),
        (
            (
                stat.session,
                str(stat.file_count),
                str(stat.docs_count),
                str(stat.tests_count),
                str(stat.install_count),
                "; ".join(stat.sample_paths),
            )
            for stat in session_stats
        ),
    )


if __name__ == "__main__":
    main()
