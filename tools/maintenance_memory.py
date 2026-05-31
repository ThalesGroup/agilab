#!/usr/bin/env python3
"""Check AGILAB path-scoped maintenance memory notes for source drift."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_ROOT = REPO_ROOT / "maintenance" / "memory" / "by-path"
SCHEMA = "agilab.maintenance_memory.check.v1"
NOTE_SCHEMA = "agilab.maintenance_memory.v1"


@dataclass(frozen=True)
class MemoryCheck:
    source: str
    note: str | None
    status: str
    title: str = ""
    message: str = ""
    expected_sha256: str | None = None
    actual_sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalize_paths(paths: Iterable[str], *, repo_root: Path = REPO_ROOT) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        value = str(raw).strip()
        if not value:
            continue
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                value = candidate.resolve(strict=False).relative_to(repo_root).as_posix()
            except ValueError:
                continue
        else:
            value = candidate.as_posix()
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return sorted(normalized)


def memory_note_path(source: str | Path, *, memory_root: Path = DEFAULT_MEMORY_ROOT) -> Path:
    """Return the path-derived maintenance-memory note for a repo source path."""
    encoded = quote(Path(source).as_posix(), safe="")
    return memory_root / f"{encoded}.md"


def _source_path_from_note(note: Path, *, memory_root: Path = DEFAULT_MEMORY_ROOT) -> str | None:
    try:
        metadata, _body = _parse_front_matter(note.read_text(encoding="utf-8"))
    except OSError:
        return None
    source = metadata.get("source")
    return Path(source).as_posix() if source else None


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    raw_header = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    metadata: dict[str, str] = {}
    for raw_line in raw_header.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        cleaned = value.strip().strip('"').strip("'")
        metadata[key.strip()] = cleaned
    return metadata, body


def _body_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _sha256(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def check_source(
    source: str,
    *,
    repo_root: Path = REPO_ROOT,
    memory_root: Path = DEFAULT_MEMORY_ROOT,
    include_uncovered: bool = False,
) -> MemoryCheck | None:
    source = Path(source).as_posix()
    note = memory_note_path(source, memory_root=memory_root)
    if not note.is_file():
        if include_uncovered:
            return MemoryCheck(source=source, note=None, status="not-covered")
        return None

    note_rel = note.relative_to(repo_root).as_posix() if note.is_relative_to(repo_root) else note.as_posix()
    try:
        note_text = note.read_text(encoding="utf-8")
    except OSError as exc:
        return MemoryCheck(source=source, note=note_rel, status="unreadable-note", message=str(exc))

    metadata, body = _parse_front_matter(note_text)
    title = metadata.get("title") or _body_title(body)
    if metadata.get("schema") != NOTE_SCHEMA:
        return MemoryCheck(
            source=source,
            note=note_rel,
            status="metadata-error",
            title=title,
            message=f"expected schema {NOTE_SCHEMA}",
        )
    if metadata.get("source") != source:
        return MemoryCheck(
            source=source,
            note=note_rel,
            status="source-mismatch",
            title=title,
            message=f"note source is {metadata.get('source')!r}",
        )

    expected = metadata.get("source_sha256")
    if not expected:
        return MemoryCheck(
            source=source,
            note=note_rel,
            status="missing-hash",
            title=title,
            message="source_sha256 is required",
        )

    actual = _sha256(repo_root / source)
    if actual is None:
        return MemoryCheck(
            source=source,
            note=note_rel,
            status="missing-source",
            title=title,
            expected_sha256=expected,
        )
    if actual != expected:
        return MemoryCheck(
            source=source,
            note=note_rel,
            status="drifted",
            title=title,
            message="source file changed since this memory note was verified",
            expected_sha256=expected,
            actual_sha256=actual,
        )
    return MemoryCheck(
        source=source,
        note=note_rel,
        status="up-to-date",
        title=title,
        expected_sha256=expected,
        actual_sha256=actual,
    )


def _run_git(args: Sequence[str], *, repo_root: Path = REPO_ROOT) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _sources_from_notes(memory_root: Path) -> list[str]:
    if not memory_root.exists():
        return []
    sources: list[str] = []
    for note in sorted(memory_root.rglob("*.md")):
        source = _source_path_from_note(note, memory_root=memory_root)
        if source:
            sources.append(source)
    return sources


def _collect_sources(args: argparse.Namespace) -> list[str]:
    memory_root = Path(args.memory_root)
    if args.all:
        return _sources_from_notes(memory_root)
    if args.staged:
        return _normalize_paths(
            _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        )
    return _normalize_paths(args.files or [])


def check_sources(
    sources: Sequence[str],
    *,
    repo_root: Path = REPO_ROOT,
    memory_root: Path = DEFAULT_MEMORY_ROOT,
    include_uncovered: bool = False,
) -> list[MemoryCheck]:
    checks: list[MemoryCheck] = []
    for source in _normalize_paths(sources, repo_root=repo_root):
        result = check_source(
            source,
            repo_root=repo_root,
            memory_root=memory_root,
            include_uncovered=include_uncovered,
        )
        if result is not None:
            checks.append(result)
    return checks


def _has_failure(checks: Sequence[MemoryCheck]) -> bool:
    return any(check.status not in {"up-to-date", "not-covered"} for check in checks)


def _render_human(checks: Sequence[MemoryCheck]) -> str:
    lines = ["Maintenance memory:"]
    if not checks:
        lines.append("- no path-scoped maintenance notes matched")
        return "\n".join(lines)
    for check in checks:
        note = f" -> {check.note}" if check.note else ""
        title = f" ({check.title})" if check.title else ""
        lines.append(f"- {check.status}: {check.source}{note}{title}")
        if check.message:
            lines.append(f"  - {check.message}")
    return "\n".join(lines)


def _render_context(
    checks: Sequence[MemoryCheck],
    *,
    repo_root: Path = REPO_ROOT,
) -> str:
    lines = [_render_human(checks)]
    for check in checks:
        if check.note is None or check.status == "not-covered":
            continue
        note_path = repo_root / check.note
        try:
            text = note_path.read_text(encoding="utf-8")
        except OSError:
            continue
        _metadata, body = _parse_front_matter(text)
        lines.append("")
        lines.append(f"## {check.source}")
        lines.append(body.strip())
    return "\n".join(lines).rstrip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check AGILAB path-scoped maintenance memory notes for drift."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("check", "context"),
        default="check",
        help="Use check for a compact status report or context to print matching note bodies.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--files", nargs="+", help="Repo-relative source files to check.")
    group.add_argument("--staged", action="store_true", help="Check staged source files.")
    group.add_argument("--all", action="store_true", help="Check every maintenance memory note.")
    parser.add_argument(
        "--memory-root",
        default=str(DEFAULT_MEMORY_ROOT),
        help="Path to the maintenance memory root.",
    )
    parser.add_argument(
        "--include-uncovered",
        action="store_true",
        help="Include files without maintenance notes as not-covered instead of omitting them.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        sources = _collect_sources(args)
    except RuntimeError as exc:
        parser.exit(2, f"maintenance_memory: {exc}\n")
    checks = check_sources(
        sources,
        memory_root=Path(args.memory_root),
        include_uncovered=args.include_uncovered,
    )
    payload = {
        "schema": SCHEMA,
        "success": not _has_failure(checks),
        "checks": [check.to_dict() for check in checks],
        "matched_count": len(checks),
        "failed_count": sum(check.status not in {"up-to-date", "not-covered"} for check in checks),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.command == "context":
        print(_render_context(checks), end="")
    else:
        print(_render_human(checks))
    return 1 if _has_failure(checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
