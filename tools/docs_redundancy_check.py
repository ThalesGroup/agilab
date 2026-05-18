from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DOC_EXTENSIONS = {".md", ".rst", ".txt"}
GENERATED_DOC_PATTERNS = (
    re.compile(r".*-licenses\.md$"),
    re.compile(r"directory-structure\.txt$"),
)
MIN_PROSE_CHARS = 45
NEARBY_WINDOW_LINES = 5


@dataclass(frozen=True)
class RedundancyViolation:
    path: Path
    first_line: int
    second_line: int
    text: str

    def format(self, root: Path) -> str:
        rel = self.path.relative_to(root)
        return f"{rel}:{self.second_line}: repeated nearby prose from line {self.first_line}: {self.text}"


def _is_generated_doc(path: Path) -> bool:
    rel = path.as_posix()
    return any(pattern.search(rel) for pattern in GENERATED_DOC_PATTERNS)


def _iter_doc_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in DOC_EXTENSIONS and not _is_generated_doc(path):
            yield path


def _normalise_prose_line(line: str) -> str | None:
    stripped = line.strip()
    if len(stripped) < MIN_PROSE_CHARS:
        return None
    if stripped.startswith((".. ", "::", "#", "```", "<", "|")):
        return None
    if set(stripped.replace(" ", "")) <= {"=", "-", "~", "^", '"'}:
        return None
    if re.match(r"^[:][A-Za-z0-9_-]+:", stripped):
        return None
    if re.match(r"^\s*[-*+]\s*$", line):
        return None
    if re.match(r"^\s*\d+\.\s*$", line):
        return None

    stripped = re.sub(r"^\s*[-*+]\s+", "", stripped)
    stripped = re.sub(r"^\s*\d+\.\s+", "", stripped)
    stripped = re.sub(r"`+", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.casefold()


def collect_violations(root: Path) -> list[RedundancyViolation]:
    root = root.resolve()
    violations: list[RedundancyViolation] = []

    for path in _iter_doc_files(root):
        lines = path.read_text(encoding="utf-8").splitlines()
        recent: dict[str, tuple[int, str]] = {}
        in_fenced_code = False
        in_rst_literal = False
        literal_indent: int | None = None

        for line_no, line in enumerate(lines, start=1):
            stripped = line.strip()

            if stripped.startswith("```"):
                in_fenced_code = not in_fenced_code
                recent.clear()
                continue

            if in_fenced_code:
                continue

            indent = len(line) - len(line.lstrip(" "))
            if in_rst_literal:
                if not stripped:
                    continue
                if literal_indent is None and indent > 0:
                    literal_indent = indent
                if literal_indent is not None and indent >= literal_indent:
                    continue
                in_rst_literal = False
                literal_indent = None

            if line.rstrip().endswith("::"):
                in_rst_literal = True
                literal_indent = None
                recent.clear()
                continue

            normalised = _normalise_prose_line(line)
            if normalised is None:
                continue

            recent = {
                text: (seen_line, seen_raw)
                for text, (seen_line, seen_raw) in recent.items()
                if line_no - seen_line <= NEARBY_WINDOW_LINES
            }
            if normalised in recent:
                first_line, first_raw = recent[normalised]
                violations.append(
                    RedundancyViolation(
                        path=path,
                        first_line=first_line,
                        second_line=line_no,
                        text=first_raw.strip(),
                    )
                )
            recent[normalised] = (line_no, line)

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject accidental nearby duplicate prose in docs.")
    parser.add_argument("root", nargs="?", default="docs/source", type=Path)
    args = parser.parse_args(argv)

    violations = collect_violations(args.root)
    if violations:
        for violation in violations:
            print(violation.format(args.root.resolve()))
        return 1
    print("No nearby duplicate prose found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
