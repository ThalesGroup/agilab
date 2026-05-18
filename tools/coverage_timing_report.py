#!/usr/bin/env python3
"""Summarize AGI-GUI coverage JUnit timings by chunk and test file."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATTERN = "test-results/junit-agi-gui-*.xml"
JUNIT_CHUNK_PREFIX = "junit-agi-gui-"
KNOWN_CHUNKS = ("support", "pipeline", "robots", "pages", "views", "reports")


@dataclass(frozen=True)
class TestTiming:
    chunk: str
    test_path: str
    test_name: str
    classname: str
    seconds: float
    source: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["seconds"] = round(self.seconds, 3)
        return payload


@dataclass(frozen=True)
class FileTiming:
    chunk: str
    test_path: str
    tests: int
    seconds: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["seconds"] = round(self.seconds, 3)
        return payload


@dataclass(frozen=True)
class ChunkTiming:
    chunk: str
    files: int
    tests: int
    seconds: float
    percentage: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["seconds"] = round(self.seconds, 3)
        payload["percentage"] = round(self.percentage, 1)
        return payload


@dataclass(frozen=True)
class TimingReport:
    sources: tuple[str, ...]
    chunks: tuple[ChunkTiming, ...]
    files: tuple[FileTiming, ...]
    slow_tests: tuple[TestTiming, ...]
    total_tests: int
    total_seconds: float
    slowest_chunk: str | None
    imbalance_ratio: float

    def to_dict(self) -> dict[str, object]:
        return {
            "sources": list(self.sources),
            "total_tests": self.total_tests,
            "total_seconds": round(self.total_seconds, 3),
            "slowest_chunk": self.slowest_chunk,
            "imbalance_ratio": round(self.imbalance_ratio, 2),
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "files": [file.to_dict() for file in self.files],
            "slow_tests": [test.to_dict() for test in self.slow_tests],
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a concise timing report from AGI-GUI coverage JUnit XML files. "
            "The report uses summed pytest testcase times, not GitHub job wall time."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=f"JUnit XML files or globs. Defaults to {DEFAULT_PATTERN!r}.",
    )
    parser.add_argument("--top-files", type=int, default=10, help="Number of slow files to report.")
    parser.add_argument("--top-tests", type=int, default=10, help="Number of slow test cases to report.")
    parser.add_argument("--json-output", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown output path.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Stdout format.",
    )
    return parser


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _expand_paths(raw_paths: Sequence[str]) -> list[Path]:
    patterns = list(raw_paths) or [DEFAULT_PATTERN]
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in patterns:
        raw_path = Path(raw)
        if raw_path.is_absolute():
            matches = sorted(raw_path.parent.glob(raw_path.name)) if any(token in raw for token in "*?[") else [raw_path]
        else:
            matches = sorted(REPO_ROOT.glob(raw)) if any(token in raw for token in "*?[") else [REPO_ROOT / raw]
        for match in matches:
            resolved = match.resolve()
            if resolved in seen or not match.is_file():
                continue
            paths.append(match)
            seen.add(resolved)
    return sorted(paths, key=lambda path: _repo_relative(path))


def _chunk_from_path(path: Path) -> str:
    stem = path.stem
    if stem.startswith(JUNIT_CHUNK_PREFIX):
        chunk = stem.removeprefix(JUNIT_CHUNK_PREFIX)
        if chunk:
            return chunk
    for part in path.parts:
        if part.startswith("coverage-gui-junit-"):
            chunk = part.removeprefix("coverage-gui-junit-")
            if chunk:
                return chunk
    return "unknown"


def _module_to_test_path(classname: str) -> str:
    module = classname.split("[", 1)[0].strip()
    if not module:
        return "unknown"

    candidates: list[str] = []
    module_path = module.replace(".", "/") + ".py"
    candidates.append(module_path)
    if "/" not in module_path and module.startswith("test_"):
        candidates.append(f"test/{module}.py")

    parts = module.split(".")
    for index, part in enumerate(parts):
        if part.startswith("test_"):
            candidates.append("/".join(parts[:index] + [part]) + ".py")

    for candidate in dict.fromkeys(candidates):
        if (REPO_ROOT / candidate).is_file():
            return candidate

    for candidate in dict.fromkeys(candidates):
        if candidate.startswith("test/"):
            return candidate
    return module_path


def _case_seconds(testcase: ET.Element) -> float:
    try:
        return max(0.0, float(testcase.attrib.get("time", "0") or 0))
    except ValueError:
        return 0.0


def _load_junit(path: Path) -> list[TestTiming]:
    root = ET.parse(path).getroot()
    chunk = _chunk_from_path(path)
    source = _repo_relative(path)
    records: list[TestTiming] = []
    for testcase in root.iter("testcase"):
        classname = testcase.attrib.get("classname", "")
        records.append(
            TestTiming(
                chunk=chunk,
                test_path=_module_to_test_path(classname),
                test_name=testcase.attrib.get("name", ""),
                classname=classname,
                seconds=_case_seconds(testcase),
                source=source,
            )
        )
    return records


def load_records(paths: Sequence[str] = ()) -> tuple[TestTiming, ...]:
    records: list[TestTiming] = []
    for path in _expand_paths(paths):
        try:
            records.extend(_load_junit(path))
        except (OSError, ET.ParseError) as exc:
            print(f"coverage_timing_report: ignoring unreadable JUnit {path}: {exc}", file=sys.stderr)
    return tuple(records)


def _chunk_sort_key(item: ChunkTiming) -> tuple[int, float, str]:
    try:
        known_index = KNOWN_CHUNKS.index(item.chunk)
    except ValueError:
        known_index = len(KNOWN_CHUNKS)
    return (-int(item.seconds * 1000), -item.tests, f"{known_index:02d}-{item.chunk}")


def build_report(
    paths: Sequence[str] = (),
    *,
    top_files: int = 10,
    top_tests: int = 10,
) -> TimingReport:
    records = load_records(paths)
    sources = tuple(dict.fromkeys(record.source for record in records))
    total_seconds = sum(record.seconds for record in records)

    chunk_records: dict[str, list[TestTiming]] = {}
    file_records: dict[tuple[str, str], list[TestTiming]] = {}
    for record in records:
        chunk_records.setdefault(record.chunk, []).append(record)
        file_records.setdefault((record.chunk, record.test_path), []).append(record)

    chunks = tuple(
        sorted(
            (
                ChunkTiming(
                    chunk=chunk,
                    files=len({record.test_path for record in chunk_items}),
                    tests=len(chunk_items),
                    seconds=sum(record.seconds for record in chunk_items),
                    percentage=(sum(record.seconds for record in chunk_items) / total_seconds * 100.0)
                    if total_seconds
                    else 0.0,
                )
                for chunk, chunk_items in chunk_records.items()
            ),
            key=_chunk_sort_key,
        )
    )
    files = tuple(
        sorted(
            (
                FileTiming(
                    chunk=chunk,
                    test_path=test_path,
                    tests=len(file_items),
                    seconds=sum(record.seconds for record in file_items),
                )
                for (chunk, test_path), file_items in file_records.items()
            ),
            key=lambda item: (-item.seconds, item.chunk, item.test_path),
        )[: max(0, top_files)]
    )
    slow_tests = tuple(
        sorted(records, key=lambda item: (-item.seconds, item.chunk, item.test_path, item.test_name))[
            : max(0, top_tests)
        ]
    )

    nonzero_chunk_seconds = [chunk.seconds for chunk in chunks if chunk.seconds > 0]
    if nonzero_chunk_seconds:
        median_seconds = statistics.median(nonzero_chunk_seconds)
        slowest_seconds = max(nonzero_chunk_seconds)
        imbalance_ratio = slowest_seconds / median_seconds if median_seconds else 0.0
    else:
        imbalance_ratio = 0.0

    return TimingReport(
        sources=sources,
        chunks=chunks,
        files=files,
        slow_tests=slow_tests,
        total_tests=len(records),
        total_seconds=total_seconds,
        slowest_chunk=chunks[0].chunk if chunks else None,
        imbalance_ratio=imbalance_ratio,
    )


def _seconds(value: float) -> str:
    if value >= 60:
        minutes = int(value // 60)
        seconds = value - minutes * 60
        return f"{minutes}m {seconds:.1f}s"
    return f"{value:.2f}s"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render_markdown(report: TimingReport) -> str:
    if not report.total_tests:
        return "\n".join(
            [
                "# AGI-GUI Coverage Timing",
                "",
                "No AGI-GUI JUnit timing files were found.",
                "",
            ]
        )

    lines = [
        "# AGI-GUI Coverage Timing",
        "",
        (
            f"Total pytest testcase time: {_seconds(report.total_seconds)} "
            f"across {report.total_tests} tests."
        ),
    ]
    if report.slowest_chunk:
        lines.append(
            f"Slowest chunk: `{report.slowest_chunk}` "
            f"({report.imbalance_ratio:.2f}x median non-empty chunk)."
        )
    lines.extend(["", "## Chunks"])
    lines.extend(
        _table(
            ("Chunk", "Test time", "Share", "Files", "Tests"),
            (
                (
                    f"`{chunk.chunk}`",
                    _seconds(chunk.seconds),
                    f"{chunk.percentage:.1f}%",
                    str(chunk.files),
                    str(chunk.tests),
                )
                for chunk in report.chunks
            ),
        )
    )
    lines.extend(["", "## Slowest Files"])
    lines.extend(
        _table(
            ("Chunk", "File", "Test time", "Tests"),
            (
                (f"`{item.chunk}`", f"`{item.test_path}`", _seconds(item.seconds), str(item.tests))
                for item in report.files
            ),
        )
    )
    lines.extend(["", "## Slowest Tests"])
    lines.extend(
        _table(
            ("Chunk", "Test", "Time"),
            (
                (
                    f"`{item.chunk}`",
                    f"`{item.test_path}::{item.test_name}`",
                    _seconds(item.seconds),
                )
                for item in report.slow_tests
            ),
        )
    )
    lines.append("")
    return "\n".join(lines)


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_report(args.paths, top_files=args.top_files, top_tests=args.top_tests)
    markdown = render_markdown(report)
    json_text = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"

    _write_text(args.markdown_output, markdown)
    _write_text(args.json_output, json_text)
    if args.format == "json":
        print(json_text, end="")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
