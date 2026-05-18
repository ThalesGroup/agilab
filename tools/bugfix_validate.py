#!/usr/bin/env python3
"""Run impact triage and the GA regression subset in one Python process."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import ga_regression_selector
import impact_validate


REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze changed files once, print impact triage, then select and "
            "optionally run the GA regression subset."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--files", nargs="+", help="Explicit repo-relative files to analyze.")
    group.add_argument("--staged", action="store_true", help="Analyze staged files.")
    parser.add_argument("--base", default="origin/main", help="Base ref for unstaged diff analysis.")
    parser.add_argument(
        "--timings",
        nargs="*",
        default=(),
        help="Optional JUnit XML or JSON timing files. Defaults to test-results/junit-*.xml when present.",
    )
    parser.add_argument("--budget-seconds", type=float, default=45.0)
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--generations", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260505)
    parser.add_argument("--max-candidates", type=int, default=96)
    parser.add_argument(
        "--cache-path",
        default=str(ga_regression_selector.DEFAULT_TEST_INDEX_CACHE_PATH),
        help="Path for cached GA selector test metadata.",
    )
    parser.add_argument("--no-cache", action="store_true", help="Bypass the GA selector cache.")
    parser.add_argument("--json", action="store_true", help="Emit combined JSON.")
    parser.add_argument("--print-command", action="store_true", help="Print only the selected pytest command.")
    parser.add_argument("--run", action="store_true", help="Run the selected pytest command.")
    return parser


def _collect_changed_files(args: argparse.Namespace) -> list[str]:
    selector_args = argparse.Namespace(
        files=args.files,
        staged=args.staged,
        base=args.base,
    )
    return ga_regression_selector.collect_changed_files(selector_args)


def build_selection_for_args(
    files: Sequence[str],
    args: argparse.Namespace,
    *,
    impact_report: impact_validate.ImpactReport,
) -> ga_regression_selector.SelectionResult:
    timings = ga_regression_selector.load_timings(args.timings)
    return ga_regression_selector.build_selection(
        files,
        timings=timings,
        budget_seconds=args.budget_seconds,
        population=args.population,
        generations=args.generations,
        seed=args.seed,
        max_candidates=args.max_candidates,
        cache_path=Path(args.cache_path),
        use_cache=not args.no_cache,
        impact_report=impact_report,
    )


def _render_human(
    impact_report: impact_validate.ImpactReport,
    selection: ga_regression_selector.SelectionResult,
) -> str:
    return "\n\n".join(
        (
            impact_validate._render_human(impact_report),
            ga_regression_selector._render_human(selection),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        files = _collect_changed_files(args)
    except RuntimeError as exc:
        parser.exit(2, f"bugfix_validate: {exc}\n")

    impact_report = impact_validate.analyze_paths(files)
    selection = build_selection_for_args(files, args, impact_report=impact_report)
    if args.json:
        print(
            json.dumps(
                {
                    "impact": impact_report.to_dict(),
                    "selection": selection.to_dict(),
                },
                indent=2,
            ),
            flush=True,
        )
    elif args.print_command:
        print(shlex.join(selection.command), flush=True)
    else:
        print(_render_human(impact_report, selection), flush=True)

    if args.run and selection.selected_tests:
        completed = subprocess.run(selection.command, cwd=REPO_ROOT, check=False)
        return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
