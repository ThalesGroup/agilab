#!/usr/bin/env python3
"""Summarize AGILAB browser page-load timing artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_PATTERN = "test-results/*page-load*.json"
CORE_PAGE_ORDER = ("ABOUT", "PROJECT", "WORKFLOW", "ANALYSIS", "TOTAL")


@dataclass(frozen=True)
class PageLoadSample:
    page: str
    seconds: float
    artifact: str
    mtime_ns: int


@dataclass(frozen=True)
class PageLoadTrend:
    page: str
    latest_seconds: float
    previous_seconds: float | None
    delta_seconds: float | None
    best_seconds: float
    worst_seconds: float
    samples: int
    artifact: str


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_samples(path: Path) -> list[PageLoadSample]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return []

    stat = path.stat()
    samples: list[PageLoadSample] = []
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            label = step.get("label")
            if not isinstance(label, str) or not label.endswith(" first visible render"):
                continue
            if step.get("success") is not True:
                continue
            duration = step.get("duration_seconds")
            if not isinstance(duration, (float, int)):
                continue
            page = label.removesuffix(" first visible render")
            samples.append(
                PageLoadSample(
                    page=page,
                    seconds=float(duration),
                    artifact=path.as_posix(),
                    mtime_ns=stat.st_mtime_ns,
                )
            )

    if samples:
        samples.append(
            PageLoadSample(
                page="TOTAL",
                seconds=sum(sample.seconds for sample in samples),
                artifact=path.as_posix(),
                mtime_ns=stat.st_mtime_ns,
            )
        )
    return samples


def _sort_key(sample: PageLoadSample) -> tuple[int, str]:
    return (sample.mtime_ns, sample.artifact)


def collect_trends(paths: Iterable[Path]) -> list[PageLoadTrend]:
    grouped: dict[str, list[PageLoadSample]] = {}
    for path in paths:
        if not path.is_file():
            continue
        for sample in _extract_samples(path):
            grouped.setdefault(sample.page, []).append(sample)

    trends: list[PageLoadTrend] = []
    for page, samples in grouped.items():
        ordered = sorted(samples, key=_sort_key)
        latest = ordered[-1]
        previous = ordered[-2] if len(ordered) >= 2 else None
        best = min(ordered, key=lambda sample: sample.seconds)
        worst = max(ordered, key=lambda sample: sample.seconds)
        trends.append(
            PageLoadTrend(
                page=page,
                latest_seconds=latest.seconds,
                previous_seconds=previous.seconds if previous else None,
                delta_seconds=(
                    latest.seconds - previous.seconds
                    if previous is not None
                    else None
                ),
                best_seconds=best.seconds,
                worst_seconds=worst.seconds,
                samples=len(ordered),
                artifact=latest.artifact,
            )
        )

    page_rank = {page: index for index, page in enumerate(CORE_PAGE_ORDER)}
    return sorted(
        trends,
        key=lambda trend: (page_rank.get(trend.page, len(page_rank)), trend.page),
    )


def discover_artifacts(pattern: str, *, limit: int | None = None) -> list[Path]:
    paths = sorted(
        Path().glob(pattern),
        key=lambda path: (path.stat().st_mtime_ns if path.exists() else 0, path.as_posix()),
    )
    if limit is not None and limit > 0:
        return paths[-limit:]
    return paths


def _fmt_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}s"


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.4f}s"


def _find_regressions(
    trends: Sequence[PageLoadTrend], max_regression_seconds: float | None
) -> list[PageLoadTrend]:
    if max_regression_seconds is None:
        return []
    return [
        trend
        for trend in trends
        if trend.delta_seconds is not None
        and trend.delta_seconds > max_regression_seconds
    ]


def render_markdown(trends: Sequence[PageLoadTrend], *, pattern: str) -> str:
    if not trends:
        return f"No browser page-load artifacts matched `{pattern}`."

    lines = [
        "# Browser page-load trend",
        "",
        f"Artifacts: `{pattern}`",
        "",
        "| Page | Latest | Previous | Delta | Best | Worst | Samples | Latest artifact |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for trend in trends:
        lines.append(
            "| "
            f"{trend.page} | "
            f"{_fmt_seconds(trend.latest_seconds)} | "
            f"{_fmt_seconds(trend.previous_seconds)} | "
            f"{_fmt_delta(trend.delta_seconds)} | "
            f"{_fmt_seconds(trend.best_seconds)} | "
            f"{_fmt_seconds(trend.worst_seconds)} | "
            f"{trend.samples} | "
            f"`{trend.artifact}` |"
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize AGILAB browser page-load JSON artifacts and show latest, "
            "previous, delta, best, and worst timings."
        )
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"Glob pattern for page-load artifacts. Default: {DEFAULT_PATTERN}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of most-recent artifacts to include. Use 0 for all.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit successfully even when no matching timing samples are found.",
    )
    parser.add_argument(
        "--max-regression-seconds",
        type=float,
        default=None,
        help=(
            "Fail when any latest page timing is slower than the previous sample "
            "by more than this many seconds. Pages with only one sample are ignored."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.max_regression_seconds is not None and args.max_regression_seconds < 0:
        parser.error("--max-regression-seconds must be >= 0")

    paths = discover_artifacts(args.pattern, limit=args.limit or None)
    trends = collect_trends(paths)
    regressions = _find_regressions(trends, args.max_regression_seconds)
    if args.json:
        payload = {
            "pattern": args.pattern,
            "trends": [asdict(trend) for trend in trends],
        }
        if args.max_regression_seconds is not None:
            payload["max_regression_seconds"] = args.max_regression_seconds
            payload["regressions"] = [asdict(trend) for trend in regressions]
        print(json.dumps(payload, indent=2))
    else:
        print(render_markdown(trends, pattern=args.pattern))

    if regressions:
        details = ", ".join(
            f"{trend.page} {_fmt_delta(trend.delta_seconds)}"
            for trend in regressions
        )
        print(
            f"Browser page-load regression gate failed: {details}",
            file=sys.stderr,
        )
        return 2
    if not trends and not args.allow_empty:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
