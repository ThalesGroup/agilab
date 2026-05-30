#!/usr/bin/env python3
"""Detect mixed-scope dirty worktrees before an agent keeps adding changes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_SCOPES = 2
DEFAULT_ALLOWED_SCOPES = (
    "agent-runbook",
    "agent-skills",
    "badges",
    "docs",
    "git-hooks",
    "github-workflows",
    "repo-tools",
    "tests",
)

APP_HINTS = {
    "flight_telemetry": "flight_telemetry_project",
    "mission_decision": "mission_decision_project",
    "multi_app_dag": "multi_app_dag_project",
    "multi_dag": "multi_app_dag_project",
    "pytorch_playground": "pytorch_playground_project",
    "sklearn_pipeline": "sklearn_pipeline_project",
    "tescia_diagnostic": "tescia_diagnostic_project",
    "uav_relay_queue": "uav_relay_queue_project",
    "uav_queue": "uav_queue_project",
    "weather_forecast": "weather_forecast_project",
}


GitRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class ScopeReport:
    changed_files: tuple[str, ...]
    groups: dict[str, tuple[str, ...]]
    max_scopes: int
    allowed_scopes: tuple[str, ...] = ()

    @property
    def counted_scopes(self) -> tuple[str, ...]:
        allowed = set(self.allowed_scopes)
        return tuple(scope for scope in sorted(self.groups) if scope not in allowed)

    @property
    def mixed(self) -> bool:
        return len(self.counted_scopes) > self.max_scopes


def _run_git(args: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _split_lines(value: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def changed_files(
    *,
    staged: bool = False,
    include_untracked: bool = False,
    git: GitRunner = _run_git,
) -> tuple[str, ...]:
    """Return changed paths from the local worktree, ignoring deleted-only noise."""
    paths: set[str] = set()
    if staged:
        paths.update(_split_lines(git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])))
    else:
        paths.update(_split_lines(git(["diff", "--name-only", "--diff-filter=ACMR"])))
        paths.update(_split_lines(git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])))
    if include_untracked:
        paths.update(_split_lines(git(["ls-files", "--others", "--exclude-standard"])))
    return tuple(sorted(paths))


def _app_hint_scope(path: str) -> str | None:
    normalized = path.replace("-", "_")
    for hint, project in sorted(APP_HINTS.items(), key=lambda item: len(item[0]), reverse=True):
        if hint in normalized:
            return f"app:{project}"
    return None


def scope_for_path(path: str) -> str:
    """Return the review scope used to spot unrelated local changes."""
    parts = Path(path).parts
    if len(parts) >= 5 and parts[:4] == ("src", "agilab", "apps", "builtin"):
        return f"app:{parts[4]}"
    if len(parts) >= 4 and parts[:3] == ("src", "agilab", "apps-pages"):
        return f"page:{parts[3]}"
    if len(parts) >= 4 and parts[:3] == ("src", "agilab", "lib"):
        package = parts[3]
        if package.startswith("agi-app-") and "project" in parts:
            index = parts.index("project")
            if index + 1 < len(parts):
                return f"app:{parts[index + 1]}"
        if package.startswith("agi-app-"):
            return f"package:{package}"
        if package.startswith("agi-page-"):
            return f"page:{package}"
        return f"lib:{package}"
    if len(parts) >= 4 and parts[:3] == ("src", "agilab", "core"):
        return f"core:{parts[3]}"
    if path == "AGENTS.md":
        return "agent-runbook"
    if path.startswith("docs/") or path in {"README.md", "CHANGELOG.md"}:
        return "docs"
    if path.startswith(".claude/skills/") or path.startswith(".codex/skills/"):
        return "agent-skills"
    if path.startswith(".github/"):
        return "github-workflows"
    if path.startswith(".githooks/"):
        return "git-hooks"
    if path.startswith("tools/"):
        hint = _app_hint_scope(path)
        return hint or "repo-tools"
    if path.startswith("test/"):
        hint = _app_hint_scope(path)
        return hint or "tests"
    if path.startswith("badges/"):
        return "badges"
    return parts[0] if parts else "root"


def analyze_scope(
    paths: Sequence[str],
    *,
    max_scopes: int = DEFAULT_MAX_SCOPES,
    allowed_scopes: Sequence[str] = (),
) -> ScopeReport:
    groups: dict[str, list[str]] = defaultdict(list)
    for path in sorted(set(paths)):
        groups[scope_for_path(path)].append(path)
    return ScopeReport(
        changed_files=tuple(sorted(set(paths))),
        groups={scope: tuple(files) for scope, files in sorted(groups.items())},
        max_scopes=max(0, int(max_scopes)),
        allowed_scopes=tuple(sorted(set(allowed_scopes))),
    )


def render_text(report: ScopeReport, *, sample_limit: int = 6) -> str:
    if not report.changed_files:
        return "worktree scope: clean"
    lines = [
        (
            "worktree scope: "
            f"{len(report.changed_files)} changed file(s), "
            f"{len(report.counted_scopes)} counted scope(s), "
            f"max={report.max_scopes}"
        )
    ]
    status = "MIXED" if report.mixed else "ok"
    lines[0] += f" -> {status}"
    for scope, files in report.groups.items():
        suffix = " (allowed)" if scope in report.allowed_scopes else ""
        lines.append(f"- {scope}{suffix}: {len(files)} file(s)")
        for path in files[:sample_limit]:
            lines.append(f"  {path}")
        if len(files) > sample_limit:
            lines.append(f"  ... {len(files) - sample_limit} more")
    if report.mixed:
        lines.extend(
            [
                "",
                "Recommended fixes:",
                "  ./dev task-worktree <branch-name>",
                "  ./dev scope --allow-scope <scope>",
                "  git add <only-the-files-for-this-task>",
            ]
        )
    return "\n".join(lines)


def report_to_json(report: ScopeReport) -> dict[str, object]:
    return {
        "schema": "agilab.worktree_scope_guard.v1",
        "changed_count": len(report.changed_files),
        "max_scopes": report.max_scopes,
        "allowed_scopes": list(report.allowed_scopes),
        "counted_scopes": list(report.counted_scopes),
        "mixed": report.mixed,
        "groups": {scope: list(files) for scope, files in report.groups.items()},
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-scopes", type=int, default=DEFAULT_MAX_SCOPES)
    parser.add_argument("--allow-scope", action="append", default=[])
    parser.add_argument("--strict", action="store_true", help="Count infrastructure scopes too.")
    parser.add_argument("--staged", action="store_true", help="Inspect only staged changes.")
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="Include untracked non-ignored files. This is already the default unless --staged or --tracked-only is used.",
    )
    parser.add_argument("--tracked-only", action="store_true", help="Ignore untracked files in the full worktree check.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--changed-file", action="append", default=None, help="Use explicit paths instead of git.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    paths = (
        tuple(args.changed_file)
        if args.changed_file is not None
        else changed_files(
            staged=args.staged,
            include_untracked=args.include_untracked or (not args.staged and not args.tracked_only),
        )
    )
    allowed_scopes = (
        tuple(args.allow_scope)
        if args.strict
        else tuple(sorted({*DEFAULT_ALLOWED_SCOPES, *args.allow_scope}))
    )
    report = analyze_scope(paths, max_scopes=args.max_scopes, allowed_scopes=allowed_scopes)
    if args.json:
        print(json.dumps(report_to_json(report), indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 1 if report.mixed else 0


if __name__ == "__main__":
    raise SystemExit(main())
