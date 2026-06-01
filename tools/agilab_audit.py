#!/usr/bin/env python3
"""Audit local AGILAB repository, release, docs, and PyPI robustness state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence

try:
    from pypi_project_preflight import build_report as pypi_preflight_report
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.pypi_project_preflight import build_report as pypi_preflight_report


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "agilab.audit.v1"


def _run(command: list[str], *, cwd: Path = ROOT, timeout: int = 60) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _git(args: list[str], *, cwd: Path = ROOT) -> tuple[int, str, str]:
    return _run(["git", *args], cwd=cwd)


def _is_expected_github_tag_checkout(*, detached: bool, head: str | None) -> bool:
    """GitHub release workflows check out tags as detached HEADs by design."""
    if not detached or not head:
        return False
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    if os.environ.get("GITHUB_REF_TYPE") != "tag":
        return False
    expected_sha = os.environ.get("GITHUB_SHA", "")
    return bool(expected_sha and head == expected_sha)


def _worktrees() -> list[dict[str, str]]:
    rc, out, err = _git(["worktree", "list", "--porcelain"])
    if rc:
        return [{"error": err or out}]
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in out.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


def _audit_worktree(path: Path, *, fetch: bool) -> dict[str, Any]:
    if fetch:
        _git(["fetch", "--prune", "origin"], cwd=path)
    rc, status, err = _git(["status", "--short", "--branch", "--untracked-files=no"], cwd=path)
    branch_rc, branch, _branch_err = _git(["branch", "--show-current"], cwd=path)
    head_rc, head, _head_err = _git(["rev-parse", "--short", "HEAD"], cwd=path)
    head_full_rc, head_full, _head_full_err = _git(["rev-parse", "HEAD"], cwd=path)
    upstream_rc, upstream, _upstream_err = _git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=path,
    )
    main_rc, main_counts, _main_err = _git(["rev-list", "--left-right", "--count", "HEAD...origin/main"], cwd=path)
    warnings: list[str] = []
    dirty_lines = [line for line in status.splitlines() if line and not line.startswith("## ")]
    detached = branch_rc == 0 and not branch
    expected_detached = _is_expected_github_tag_checkout(
        detached=detached,
        head=head_full if head_full_rc == 0 else None,
    )
    if dirty_lines:
        warnings.append("tracked changes present")
    if detached and not expected_detached:
        warnings.append("detached HEAD")
    if main_rc == 0:
        ahead, behind = (int(part) for part in main_counts.split())
        if behind:
            warnings.append(f"behind origin/main by {behind}")
        if ahead:
            warnings.append(f"ahead of origin/main by {ahead}")
    return {
        "path": str(path),
        "status": status if rc == 0 else err,
        "branch": branch if branch_rc == 0 and branch else None,
        "detached": detached,
        "detached_expected": expected_detached,
        "head": head if head_rc == 0 else None,
        "upstream": upstream if upstream_rc == 0 else None,
        "ahead_behind_origin_main": main_counts if main_rc == 0 else None,
        "warnings": warnings,
    }


def _command_check(name: str, command: list[str], *, timeout: int = 120) -> dict[str, Any]:
    rc, out, err = _run(command, timeout=timeout)
    return {
        "name": name,
        "status": "pass" if rc == 0 else "fail",
        "returncode": rc,
        "summary": (out or err).splitlines()[-1] if (out or err) else "",
    }


def build_report(*, fetch: bool = True, network: bool = True) -> dict[str, Any]:
    worktree_reports = [
        _audit_worktree(Path(entry["worktree"]), fetch=fetch)
        for entry in _worktrees()
        if "worktree" in entry
    ]
    checks = [
        _command_check(
            "docs-mirror-stamp",
            [sys.executable, "tools/sync_docs_source.py", "--verify-stamp"],
        ),
        _command_check(
            "release-proof",
            [sys.executable, "tools/release_proof_report.py", "--check", "--compact"],
        ),
        _command_check(
            "release-handoff-guard",
            [sys.executable, "tools/release_handoff_guard.py", "--compact"],
        ),
    ]
    pypi_report: dict[str, Any] | None = None
    if network:
        pypi_report = pypi_preflight_report(repo_root=ROOT)
    warnings = [
        f"{report['path']}: {warning}"
        for report in worktree_reports
        for warning in report["warnings"]
    ]
    failed_checks = [check for check in checks if check["status"] != "pass"]
    if pypi_report and pypi_report["status"] != "pass":
        warnings.append(f"PyPI preflight blockers: {pypi_report['summary']['blockers']}")
    status = "pass" if not warnings and not failed_checks else "warn"
    return {
        "schema": SCHEMA_VERSION,
        "status": status,
        "worktrees": worktree_reports,
        "checks": checks,
        "pypi_preflight": pypi_report,
        "warnings": warnings,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = ["AGILAB audit", f"status: {report['status']}", ""]
    lines.append("Worktrees:")
    for worktree in report["worktrees"]:
        label = worktree["branch"] or "detached"
        lines.append(f"- {worktree['path']}: {label} {worktree['head']}")
        if worktree.get("detached_expected"):
            lines.append("  info: expected GitHub Actions tag checkout")
        for warning in worktree["warnings"]:
            lines.append(f"  warning: {warning}")
    lines.append("")
    lines.append("Checks:")
    for check in report["checks"]:
        lines.append(f"- {check['name']}: {check['status']} {check['summary']}")
    if report.get("pypi_preflight"):
        summary = report["pypi_preflight"]["summary"]
        lines.append("")
        lines.append(
            "PyPI preflight: "
            f"{report['pypi_preflight']['status']} "
            f"({summary['current']}/{summary['checked']} current, {summary['blockers']} blockers)"
        )
    if report["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(fetch=not args.no_fetch, network=not args.no_network)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 2 if args.strict and report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
