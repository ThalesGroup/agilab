#!/usr/bin/env python3
"""Run impact triage and the GA regression subset in one Python process."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import ga_regression_selector
import impact_validate


REPO_ROOT = Path(__file__).resolve().parents[1]
RESULT_CACHE_SCHEMA = "agilab-bugfix-validate-result-cache-v1"
DEFAULT_RESULT_CACHE_PATH = (
    REPO_ROOT / ".pytest_cache" / "agilab" / "bugfix_validate_results.json"
)
RESULT_CACHE_MAX_ENTRIES = 256
RESULT_CACHE_STATIC_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "pytest.ini",
    "test/conftest.py",
    "tools/agilab_dev.py",
    "tools/bugfix_validate.py",
    "tools/ga_regression_selector.py",
    "tools/impact_validate.py",
)


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
    parser.add_argument(
        "--result-cache-path",
        default=str(DEFAULT_RESULT_CACHE_PATH),
        help="Path for cached successful selected pytest runs.",
    )
    parser.add_argument(
        "--no-result-cache",
        action="store_true",
        help="Bypass cached successful selected pytest runs.",
    )
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
    cache_path = Path(args.cache_path)
    use_cache = not args.no_cache
    context = ga_regression_selector.build_validation_context(
        files,
        timing_paths=args.timings,
        cache_path=cache_path,
        use_cache=use_cache,
        impact_report=impact_report,
    )
    return ga_regression_selector.build_selection(
        context.files,
        context=context,
        budget_seconds=args.budget_seconds,
        population=args.population,
        generations=args.generations,
        seed=args.seed,
        max_candidates=args.max_candidates,
        cache_path=cache_path,
        use_cache=use_cache,
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


def _load_result_cache(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": RESULT_CACHE_SCHEMA, "entries": {}}
    if not isinstance(data, dict):
        return {"schema": RESULT_CACHE_SCHEMA, "entries": {}}
    entries = data.get("entries")
    if data.get("schema") != RESULT_CACHE_SCHEMA or not isinstance(entries, dict):
        return {"schema": RESULT_CACHE_SCHEMA, "entries": {}}
    return {"schema": RESULT_CACHE_SCHEMA, "entries": entries}


def _write_result_cache(path: Path, state: dict[str, object]) -> None:
    entries = state.get("entries")
    payload = {
        "schema": RESULT_CACHE_SCHEMA,
        "entries": entries if isinstance(entries, dict) else {},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        return


def _repo_file(path: str) -> tuple[str, Path]:
    file_part = path.split("::", 1)[0]
    raw_path = Path(file_part)
    if raw_path.is_absolute():
        try:
            label = raw_path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            label = raw_path.as_posix()
        return label, raw_path
    return file_part, REPO_ROOT / file_part


def _hash_file(hasher: Any, path: str) -> None:
    label, resolved = _repo_file(path)
    hasher.update(f"path:{label}\n".encode("utf-8"))
    try:
        if not resolved.exists():
            hasher.update(b"missing\n")
            return
        if not resolved.is_file():
            hasher.update(b"not-file\n")
            return
        hasher.update(b"file\n")
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        hasher.update(f"unreadable:{type(exc).__name__}\n".encode("utf-8"))


def _unique_paths(paths: Sequence[str]) -> list[str]:
    return sorted(dict.fromkeys(paths))


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _timing_inputs(args: argparse.Namespace) -> list[str]:
    if args.timings:
        return [str(path) for path in args.timings]
    timing_root = REPO_ROOT / "test-results"
    return [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted(timing_root.glob("junit-*.xml"))
    ]


def _frontdoor_cache_enabled(args: argparse.Namespace) -> bool:
    return (
        bool(args.run)
        and not args.no_result_cache
        and not args.json
        and not args.print_command
    )


def _frontdoor_cache_key(files: Sequence[str], args: argparse.Namespace) -> str:
    hasher = hashlib.sha256()
    timing_inputs = _timing_inputs(args)
    payload = {
        "schema": RESULT_CACHE_SCHEMA,
        "kind": "frontdoor",
        "python": list(sys.version_info[:3]),
        "git_head": _git_head(),
        "budget_seconds": args.budget_seconds,
        "population": args.population,
        "generations": args.generations,
        "seed": args.seed,
        "max_candidates": args.max_candidates,
        "selector_cache_path": args.cache_path,
        "selector_no_cache": bool(args.no_cache),
        "timings": timing_inputs,
    }
    hasher.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    for group, paths in (
        ("changed", files),
        ("timings", timing_inputs),
        ("static-inputs", RESULT_CACHE_STATIC_INPUTS),
    ):
        hasher.update(f"\n[{group}]\n".encode("utf-8"))
        for path in _unique_paths(paths):
            _hash_file(hasher, path)
    return "frontdoor:" + hasher.hexdigest()


def _result_cache_key(
    files: Sequence[str],
    selection: ga_regression_selector.SelectionResult,
) -> str:
    hasher = hashlib.sha256()
    payload = {
        "schema": RESULT_CACHE_SCHEMA,
        "python": list(sys.version_info[:3]),
        "command": list(selection.command),
        "selected_tests": list(selection.selected_tests),
        "required_tests": list(selection.required_tests),
        "budget_seconds": selection.budget_seconds,
    }
    hasher.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    for group, paths in (
        ("changed", files),
        ("selected-tests", selection.selected_tests),
        ("static-inputs", RESULT_CACHE_STATIC_INPUTS),
    ):
        hasher.update(f"\n[{group}]\n".encode("utf-8"))
        for path in _unique_paths(paths):
            _hash_file(hasher, path)
    return hasher.hexdigest()


def _has_cached_success(path: Path, key: str) -> bool:
    entries = _load_result_cache(path).get("entries")
    if not isinstance(entries, dict):
        return False
    entry = entries.get(key)
    return isinstance(entry, dict) and entry.get("status") == "passed"


def _cached_frontdoor_success(path: Path, key: str) -> dict[str, object] | None:
    entries = _load_result_cache(path).get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(key)
    if (
        isinstance(entry, dict)
        and entry.get("status") == "passed"
        and entry.get("kind") == "frontdoor"
    ):
        return entry
    return None


def _trim_result_cache_entries(entries: dict[str, object]) -> None:
    while len(entries) > RESULT_CACHE_MAX_ENTRIES:
        oldest_key = min(
            entries,
            key=lambda entry_key: (
                float(entries[entry_key]["stored_at"])
                if isinstance(entries[entry_key], dict)
                and isinstance(entries[entry_key].get("stored_at"), (int, float))
                else 0.0
            ),
        )
        entries.pop(oldest_key, None)


def _record_cached_success(
    path: Path,
    key: str,
    files: Sequence[str],
    selection: ga_regression_selector.SelectionResult,
) -> None:
    state = _load_result_cache(path)
    entries = state.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    entries[key] = {
        "status": "passed",
        "stored_at": round(time.time(), 3),
        "files": list(files),
        "selected_tests": list(selection.selected_tests),
        "command": list(selection.command),
    }
    _trim_result_cache_entries(entries)
    state["entries"] = entries
    _write_result_cache(path, state)


def _record_frontdoor_success(
    path: Path,
    key: str,
    files: Sequence[str],
    selection: ga_regression_selector.SelectionResult,
    stdout: str,
) -> None:
    state = _load_result_cache(path)
    entries = state.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    entries[key] = {
        "status": "passed",
        "kind": "frontdoor",
        "stored_at": round(time.time(), 3),
        "files": list(files),
        "selected_tests": list(selection.selected_tests),
        "command": list(selection.command),
        "stdout": stdout,
    }
    _trim_result_cache_entries(entries)
    state["entries"] = entries
    _write_result_cache(path, state)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        files = _collect_changed_files(args)
    except RuntimeError as exc:
        parser.exit(2, f"bugfix_validate: {exc}\n")

    cache_path = Path(args.result_cache_path)
    frontdoor_key = (
        _frontdoor_cache_key(files, args) if _frontdoor_cache_enabled(args) else ""
    )
    if frontdoor_key:
        frontdoor_entry = _cached_frontdoor_success(cache_path, frontdoor_key)
        if frontdoor_entry is not None:
            cached_stdout = frontdoor_entry.get("stdout")
            if isinstance(cached_stdout, str) and cached_stdout:
                print(cached_stdout.rstrip("\n"), flush=True)
            print(
                "bugfix_validate: front-door cached pass; skipped impact, selection, and pytest",
                file=sys.stderr,
                flush=True,
            )
            return 0

    impact_report = impact_validate.analyze_paths(files)
    selection = build_selection_for_args(files, args, impact_report=impact_report)
    rendered_stdout = ""
    if args.json:
        rendered_stdout = json.dumps(
            {
                "impact": impact_report.to_dict(),
                "selection": selection.to_dict(),
            },
            indent=2,
        )
        print(rendered_stdout, flush=True)
    elif args.print_command:
        rendered_stdout = shlex.join(selection.command)
        print(rendered_stdout, flush=True)
    else:
        rendered_stdout = _render_human(impact_report, selection)
        print(rendered_stdout, flush=True)

    if args.run and selection.selected_tests:
        cache_key = _result_cache_key(files, selection)
        if not args.no_result_cache and _has_cached_success(cache_path, cache_key):
            if frontdoor_key:
                _record_frontdoor_success(
                    cache_path,
                    frontdoor_key,
                    files,
                    selection,
                    rendered_stdout,
                )
            print(
                "bugfix_validate: cached pass for selected pytest subset",
                file=sys.stderr,
                flush=True,
            )
            return 0
        completed = subprocess.run(selection.command, cwd=REPO_ROOT, check=False)
        if completed.returncode == 0 and not args.no_result_cache:
            _record_cached_success(cache_path, cache_key, files, selection)
            if frontdoor_key:
                _record_frontdoor_success(
                    cache_path,
                    frontdoor_key,
                    files,
                    selection,
                    rendered_stdout,
                )
        return completed.returncode
    if args.run and not selection.selected_tests and frontdoor_key:
        _record_frontdoor_success(
            cache_path,
            frontdoor_key,
            files,
            selection,
            rendered_stdout,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
