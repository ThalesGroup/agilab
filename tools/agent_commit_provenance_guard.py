#!/usr/bin/env python3
"""Guard agent branch commits from using human Git identities."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.agent_commit_provenance.v1"
ZERO_SHA = "0" * 40
FIELD_SEP = "\x1f"

AGENT_BRANCH_RE = re.compile(r"^(codex|claude|aider|opencode|agent)(?:[-/].*)?$", re.I)
AGENT_IDENTITY_TERMS = (
    "agent",
    "aider",
    "bot",
    "claude",
    "codex",
    "github-actions[bot]",
    "opencode",
)
HUMAN_IDENTITY_TERMS = (
    "118378788+guillaumedemets@users.noreply.github.com",
    "203319130+jpmorard@users.noreply.github.com",
    "focus@thalesgroup.com",
    "g.demets02@gmail.com",
    "guilaumedemets",
    "guillaume demets",
    "guillaumedemets",
    "jean-pierre morard",
    "jean-pierre.morard@thalesgroup.com",
    "jpmorard",
)
DEFAULT_AGENT_NAME = "AGILAB Codex Agent"
DEFAULT_AGENT_EMAIL = "codex-agent@users.noreply.github.com"


@dataclass(frozen=True)
class Identity:
    name: str
    email: str


@dataclass(frozen=True)
class Issue:
    severity: str
    rule: str
    message: str
    branch: str = ""
    commit: str = ""
    field: str = ""
    name: str = ""
    email: str = ""


@dataclass(frozen=True)
class CommitEvidence:
    sha: str
    subject: str
    author: Identity
    committer: Identity
    issues: tuple[Issue, ...]


@dataclass(frozen=True)
class PushSpec:
    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str


def _run_git(root: Path, args: Sequence[str], *, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _identity_blob(identity: Identity) -> str:
    return f"{identity.name}\n{identity.email}".lower()


def is_agent_branch(branch: str) -> bool:
    return bool(AGENT_BRANCH_RE.match(branch.strip()))


def is_human_identity(identity: Identity) -> bool:
    blob = _identity_blob(identity)
    return any(term in blob for term in HUMAN_IDENTITY_TERMS)


def is_agent_identity(identity: Identity) -> bool:
    blob = _identity_blob(identity)
    return any(term in blob for term in AGENT_IDENTITY_TERMS)


def _identity_issues(*, branch: str, commit: str, field: str, identity: Identity) -> list[Issue]:
    if is_human_identity(identity):
        return [
            Issue(
                severity="error",
                rule="agent-branch-human-identity",
                branch=branch,
                commit=commit,
                field=field,
                name=identity.name,
                email=identity.email,
                message=(
                    "agent-prefixed branches must not use a human Git identity; "
                    f"configure {DEFAULT_AGENT_NAME!r} <{DEFAULT_AGENT_EMAIL}> instead"
                ),
            )
        ]
    if not is_agent_identity(identity):
        return [
            Issue(
                severity="error",
                rule="agent-branch-ambiguous-identity",
                branch=branch,
                commit=commit,
                field=field,
                name=identity.name,
                email=identity.email,
                message=(
                    "agent-prefixed branches require an explicit agent/bot Git identity; "
                    f"configure {DEFAULT_AGENT_NAME!r} <{DEFAULT_AGENT_EMAIL}> instead"
                ),
            )
        ]
    return []


def _branch_from_ref(ref: str) -> str:
    if ref.startswith("refs/heads/"):
        return ref.removeprefix("refs/heads/")
    return ref


def _current_branch(root: Path) -> str:
    return _run_git(root, ["branch", "--show-current"], check=False)


def check_current_config(root: Path = REPO_ROOT) -> dict[str, Any]:
    branch = _current_branch(root)
    identity = Identity(
        name=_run_git(root, ["config", "--get", "user.name"], check=False),
        email=_run_git(root, ["config", "--get", "user.email"], check=False),
    )
    issues: list[Issue] = []
    if is_agent_branch(branch):
        issues.extend(_identity_issues(branch=branch, commit="", field="git-config", identity=identity))
    return _build_report(
        action="check-config",
        issues=issues,
        evidence={
            "branch": branch,
            "git_config": asdict(identity),
            "default_agent_identity": {
                "name": DEFAULT_AGENT_NAME,
                "email": DEFAULT_AGENT_EMAIL,
            },
        },
    )


def _commit_evidence(root: Path, branch: str, sha: str) -> CommitEvidence:
    fmt = FIELD_SEP.join(["%H", "%s", "%an", "%ae", "%cn", "%ce"])
    raw = _run_git(root, ["show", "-s", f"--format={fmt}", sha])
    full_sha, subject, author_name, author_email, committer_name, committer_email = raw.split(FIELD_SEP)
    author = Identity(author_name, author_email)
    committer = Identity(committer_name, committer_email)
    issues: list[Issue] = []
    issues.extend(_identity_issues(branch=branch, commit=full_sha, field="author", identity=author))
    issues.extend(_identity_issues(branch=branch, commit=full_sha, field="committer", identity=committer))
    return CommitEvidence(
        sha=full_sha,
        subject=subject,
        author=author,
        committer=committer,
        issues=tuple(issues),
    )


def _rev_list(root: Path, rev_range: str) -> tuple[str, ...]:
    output = _run_git(root, ["rev-list", "--reverse", rev_range], check=False)
    return tuple(line for line in output.splitlines() if line.strip())


def _merge_base(root: Path, local_sha: str, base_ref: str) -> str:
    return _run_git(root, ["merge-base", local_sha, base_ref], check=False)


def _rev_range_for_spec(root: Path, spec: PushSpec, *, base_ref: str) -> str | None:
    if not spec.local_sha or spec.local_sha == ZERO_SHA:
        return None
    if spec.remote_sha and spec.remote_sha != ZERO_SHA:
        return f"{spec.remote_sha}..{spec.local_sha}"
    base = _merge_base(root, spec.local_sha, base_ref)
    if base:
        return f"{base}..{spec.local_sha}"
    return spec.local_sha


def parse_pre_push_spec(text: str) -> tuple[PushSpec, ...]:
    specs: list[PushSpec] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        specs.append(PushSpec(*parts))
    return tuple(specs)


def check_pre_push_specs(
    root: Path = REPO_ROOT,
    specs: Iterable[PushSpec] = (),
    *,
    base_ref: str = "origin/main",
) -> dict[str, Any]:
    issues: list[Issue] = []
    commits: list[CommitEvidence] = []
    spec_rows: list[dict[str, str]] = []
    for spec in specs:
        branch = _branch_from_ref(spec.local_ref) or _branch_from_ref(spec.remote_ref)
        spec_rows.append(asdict(spec))
        if not is_agent_branch(branch):
            continue
        rev_range = _rev_range_for_spec(root, spec, base_ref=base_ref)
        if not rev_range:
            continue
        for sha in _rev_list(root, rev_range):
            evidence = _commit_evidence(root, branch, sha)
            commits.append(evidence)
            issues.extend(evidence.issues)
    return _build_report(
        action="pre-push",
        issues=issues,
        evidence={
            "base_ref": base_ref,
            "push_specs": spec_rows,
            "commits": [asdict(commit) for commit in commits],
        },
    )


def check_rev_ranges(
    root: Path = REPO_ROOT,
    ranges: Iterable[str] = (),
    *,
    branch: str,
) -> dict[str, Any]:
    issues: list[Issue] = []
    commits: list[CommitEvidence] = []
    for rev_range in ranges:
        for sha in _rev_list(root, rev_range):
            evidence = _commit_evidence(root, branch, sha)
            commits.append(evidence)
            issues.extend(evidence.issues)
    return _build_report(
        action="rev-range",
        issues=issues,
        evidence={"branch": branch, "commits": [asdict(commit) for commit in commits]},
    )


def _run_gh_json(args: Sequence[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        command = " ".join(["gh", *args])
        raise RuntimeError(f"{command} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return json.loads(completed.stdout)


def inventory_github_prs(
    *,
    repo: str,
    limit: int,
    prefixes: Sequence[str],
) -> dict[str, Any]:
    issues: list[Issue] = []
    prs: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for prefix in prefixes:
        rows = _run_gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "merged",
                "--search",
                f"head:{prefix}",
                "--limit",
                str(limit),
                "--json",
                "number,title,headRefName,mergedAt,url",
            ]
        )
        for row in rows:
            number = int(row.get("number") or 0)
            if number in seen:
                continue
            seen.add(number)
            commit_payload = _run_gh_json(
                [
                    "pr",
                    "view",
                    str(number),
                    "--repo",
                    repo,
                    "--json",
                    "commits",
                ]
            )
            row = {**row, "commits": commit_payload.get("commits") or []}
            prs.append(row)
            branch = str(row.get("headRefName") or "")
            for commit in row.get("commits") or []:
                commit_sha = str(commit.get("oid") or "")
                for author in commit.get("authors") or []:
                    identity = Identity(
                        name=str(author.get("name") or ""),
                        email=str(author.get("email") or ""),
                    )
                    if is_human_identity(identity) or not is_agent_identity(identity):
                        issues.extend(
                            _identity_issues(
                                branch=branch,
                                commit=commit_sha,
                                field="github-pr-author",
                                identity=identity,
                            )
                        )
    return _build_report(
        action="github-inventory",
        issues=issues,
        evidence={
            "repo": repo,
            "prefixes": list(prefixes),
            "pull_request_count": len(prs),
            "pull_requests": prs,
        },
    )


def _build_report(*, action: str, issues: Sequence[Issue], evidence: Mapping[str, Any]) -> dict[str, Any]:
    error_count = sum(1 for issue in issues if issue.severity == "error")
    return {
        "schema": SCHEMA,
        "status": "fail" if error_count else "pass",
        "action": action,
        "summary": {
            "issue_count": len(issues),
            "error_count": error_count,
        },
        "issues": [asdict(issue) for issue in issues],
        "evidence": evidence,
    }


def render_text(report: Mapping[str, Any]) -> str:
    lines = [
        "Agent commit provenance guard",
        f"Schema: {report['schema']}",
        f"Status: {report['status']}",
        f"Action: {report['action']}",
        f"Issues: {report['summary']['issue_count']}",
    ]
    for issue in report.get("issues", []):
        commit = issue.get("commit") or "(config)"
        branch = issue.get("branch") or "(unknown branch)"
        identity = f"{issue.get('name')} <{issue.get('email')}>"
        lines.append(f"- {issue.get('rule')}: {branch} {commit} {issue.get('field')} {identity}")
    if report["status"] == "fail":
        lines.extend(
            [
                "",
                "Use an explicit agent identity on agent-prefixed branches:",
                f"  git config user.name {DEFAULT_AGENT_NAME!r}",
                f"  git config user.email {DEFAULT_AGENT_EMAIL!r}",
            ]
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check-config", action="store_true", help="Check current branch git identity.")
    parser.add_argument("--pre-push-spec", type=Path, help="Read git pre-push stdin lines from this file.")
    parser.add_argument("--base-ref", default="origin/main", help="Base ref for new branch push ranges.")
    parser.add_argument("--rev-range", action="append", default=[], help="Explicit revision range to inspect.")
    parser.add_argument("--branch", default="", help="Agent branch label for --rev-range checks.")
    parser.add_argument("--inventory-github", action="store_true", help="Inventory merged agent PR identities via gh.")
    parser.add_argument("--repo", default="ThalesGroup/agilab", help="GitHub repo for --inventory-github.")
    parser.add_argument("--limit", type=int, default=200, help="Per-prefix PR inventory limit.")
    parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="Agent branch prefix for GitHub inventory; default covers codex, claude, aider, opencode, agent.",
    )
    parser.add_argument("--fail-on-findings", action="store_true", help="Make inventory findings exit non-zero.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if args.pre_push_spec:
        report = check_pre_push_specs(
            root,
            parse_pre_push_spec(args.pre_push_spec.read_text(encoding="utf-8")),
            base_ref=args.base_ref,
        )
        should_fail = True
    elif args.rev_range:
        branch = args.branch or _current_branch(root)
        report = check_rev_ranges(root, args.rev_range, branch=branch)
        should_fail = True
    elif args.inventory_github:
        prefixes = tuple(args.prefix or ["codex", "claude", "aider", "opencode", "agent"])
        report = inventory_github_prs(repo=args.repo, limit=args.limit, prefixes=prefixes)
        should_fail = args.fail_on_findings
    else:
        report = check_current_config(root)
        should_fail = True

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 1 if should_fail and report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
