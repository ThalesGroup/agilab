#!/usr/bin/env python3
"""Static audit for pandas 3 / Copy-on-Write migration risks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_ROOTS = ("src", "test", "tools")
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "reports/dev-logs",
}
PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "inplace",
        re.compile(r"\binplace\s*=\s*True\b"),
        "Pandas inplace operations become harder to reason about with Copy-on-Write; prefer assignment.",
    ),
    (
        "chained-assignment",
        re.compile(r"\][ \t]*\[[^\n\]]+\][ \t]*=(?!=)"),
        "Chained assignment may stop mutating the original object under Copy-on-Write.",
    ),
    (
        "copy-deep-false",
        re.compile(r"\.copy\s*\([^\n)]*deep\s*=\s*False"),
        "Shallow copies share data more visibly under Copy-on-Write; check mutation assumptions.",
    ),
    (
        "copy-on-write-option",
        re.compile(r"mode\.copy_on_write"),
        "Copy-on-Write option is already being managed here; verify behavior under pandas 3 defaults.",
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    detail: str
    text: str


def _iter_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel_parts = set(path.relative_to(root).parts[:-1]) if path.is_relative_to(root) else set()
            if rel_parts & SKIP_DIRS:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            yield path


def audit(paths: Sequence[str]) -> list[Finding]:
    findings: list[Finding] = []
    roots = [Path(path) for path in paths]
    for path in sorted(_iter_files(roots)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            if "pandas" not in line and "pd." not in line and "inplace" not in line and "][" not in line:
                continue
            for kind, pattern, detail in PATTERNS:
                if kind == "chained-assignment" and not re.search(
                    r"\b(df|dataframe|frame)\b|\.loc\b|\.iloc\b",
                    line,
                    flags=re.IGNORECASE,
                ):
                    continue
                if pattern.search(line):
                    findings.append(
                        Finding(
                            path=str(path),
                            line=number,
                            kind=kind,
                            detail=detail,
                            text=line.strip(),
                        )
                    )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_ROOTS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when findings are present")
    args = parser.parse_args(argv)

    findings = audit(args.paths)
    if args.json:
        print(json.dumps([asdict(finding) for finding in findings], indent=2, sort_keys=True))
    else:
        if not findings:
            print("No pandas compatibility risk patterns found.")
            return 0
        for finding in findings:
            print(f"{finding.path}:{finding.line}: {finding.kind}: {finding.text}")
            print(f"  {finding.detail}")
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
