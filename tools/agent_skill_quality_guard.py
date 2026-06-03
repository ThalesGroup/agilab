#!/usr/bin/env python3
"""Quality guard for repo-managed agent skills.

This complements the repo's security scan with spec-adjacent checks inspired by
`agent-ecosystem/skill-validator`: portable structure, broken local links,
oversized activation content, and optional external validator execution when the
CLI is installed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = (REPO_ROOT / ".claude" / "skills", REPO_ROOT / ".codex" / "skills")
SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")
ALLOWED_ROOT_FILES = {"SKILL.md", "LICENSE", "LICENSE.txt", "LICENCE", "LICENCE.txt"}
FORBIDDEN_ROOT_FILES = {"AGENTS.md", "CHANGELOG.md", "README.md"}
STANDARD_DIRS = {"agents", "assets", "references", "scripts", "templates"}
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".dot",
    ".html",
    ".ipynb",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\((?P<target>[^)]+)\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Finding:
    skill: str
    severity: str
    rule: str
    message: str
    path: str


@dataclass(frozen=True)
class ExternalValidatorStatus:
    mode: str
    command: str
    available: bool
    executed: bool


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.index(severity)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _strip_front_matter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    parts = text.split("---", 2)
    return parts[2].lstrip("\n") if len(parts) >= 3 else text


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def skill_dirs(roots: Iterable[Path], explicit: Iterable[Path]) -> list[Path]:
    selected = [path for path in explicit if (path / "SKILL.md").exists()]
    if selected:
        return sorted({path.resolve() for path in selected})
    dirs: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        dirs.extend(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))
    return sorted({path.resolve() for path in dirs})


def changed_skill_dirs(base_ref: str, roots: Iterable[Path]) -> list[Path]:
    root_args = [root.relative_to(REPO_ROOT).as_posix() for root in roots if root.exists()]
    if not root_args:
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD", "--", *root_args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git diff failed")
    dirs: set[Path] = set()
    for raw in result.stdout.splitlines():
        rel = Path(raw)
        if len(rel.parts) >= 3 and rel.parts[1] == "skills":
            candidate = REPO_ROOT / rel.parts[0] / rel.parts[1] / rel.parts[2]
            if (candidate / "SKILL.md").exists():
                dirs.add(candidate.resolve())
    return sorted(dirs)


def _markdown_link_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in LINK_RE.finditer(text):
        target = match.group("target").strip()
        if not target:
            continue
        if target[0] in {"'", '"'} and target[-1:] == target[0]:
            target = target[1:-1]
        if " " in target:
            target = target.split(" ", 1)[0]
        targets.append(target)
    return targets


def _is_external_target(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith("#")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("mailto:")
        or "://" in lowered
    )


def _target_path(target: str) -> str:
    return unquote(target.split("#", 1)[0].split("?", 1)[0].strip())


def _check_internal_links(skill_dir: Path, path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    skill_name = skill_dir.name
    for target in _markdown_link_targets(text):
        if _is_external_target(target):
            continue
        clean_target = _target_path(target)
        if not clean_target:
            continue
        resolved = (path.parent / clean_target).resolve()
        if not resolved.exists():
            findings.append(
                Finding(
                    skill_name,
                    "high",
                    "broken-internal-link",
                    f"Internal skill link does not resolve: {target}",
                    _rel(path),
                )
            )
            continue
        try:
            resolved.relative_to(skill_dir.resolve())
        except ValueError:
            findings.append(
                Finding(
                    skill_name,
                    "medium",
                    "external-skill-reference",
                    f"Internal link points outside the self-contained skill directory: {target}",
                    _rel(path),
                )
            )
    return findings


def _has_unclosed_code_fence(text: str) -> bool:
    fence: str | None = None
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if not match:
            continue
        marker = match.group(1)
        if fence is None:
            fence = marker
        elif marker == fence:
            fence = None
    return fence is not None


def _standard_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for dirname in STANDARD_DIRS - {"agents"}:
        base = skill_dir / dirname
        if not base.exists():
            continue
        files.extend(path for path in base.rglob("*") if path.is_file())
    return sorted(files)


def _referenced_resource_names(skill_dir: Path) -> set[str]:
    references: set[str] = set()
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or not _is_text_file(path):
            continue
        content = _read_text(path)
        for candidate in _standard_files(skill_dir):
            rel = candidate.relative_to(skill_dir).as_posix()
            if rel in content:
                references.add(rel)
    return references


def scan_skill(skill_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    skill_name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return [
            Finding(
                skill_name,
                "critical",
                "missing-skill-md",
                "Skill directory is missing SKILL.md.",
                _rel(skill_dir),
            )
        ]

    skill_text = _read_text(skill_md)
    body = _strip_front_matter(skill_text)
    body_lines = body.splitlines()
    body_words = body.split()

    if len(body_lines) > 500:
        findings.append(
            Finding(
                skill_name,
                "medium",
                "activation-too-long",
                f"SKILL.md body has {len(body_lines)} lines; move detail into references/.",
                _rel(skill_md),
            )
        )
    if len(body_words) > 6000:
        findings.append(
            Finding(
                skill_name,
                "high",
                "activation-word-budget",
                f"SKILL.md body has {len(body_words)} words; activation context is too large.",
                _rel(skill_md),
            )
        )
    if _has_unclosed_code_fence(skill_text):
        findings.append(
            Finding(
                skill_name,
                "high",
                "unclosed-code-fence",
                "SKILL.md has an unclosed Markdown code fence.",
                _rel(skill_md),
            )
        )

    for child in sorted(skill_dir.iterdir()):
        if child.name in ALLOWED_ROOT_FILES or child.name.startswith("."):
            continue
        if child.is_dir():
            if child.name not in STANDARD_DIRS:
                findings.append(
                    Finding(
                        skill_name,
                        "medium",
                        "unknown-root-directory",
                        f"Unexpected skill root directory: {child.name}/.",
                        _rel(child),
                    )
                )
            continue
        severity = "high" if child.name in FORBIDDEN_ROOT_FILES else "low"
        findings.append(
            Finding(
                skill_name,
                severity,
                "nonstandard-root-file",
                f"Unexpected skill root file: {child.name}.",
                _rel(child),
            )
        )

    text_files = [skill_md]
    text_files.extend(path for path in _standard_files(skill_dir) if _is_text_file(path))
    for path in text_files:
        text = _read_text(path)
        findings.extend(_check_internal_links(skill_dir, path, text))
        if path != skill_md and _has_unclosed_code_fence(text):
            findings.append(
                Finding(
                    skill_name,
                    "high",
                    "unclosed-code-fence",
                    "Reference or script file has an unclosed Markdown code fence.",
                    _rel(path),
                )
            )
        if path != skill_md and len(text.split()) > 25000:
            findings.append(
                Finding(
                    skill_name,
                    "high",
                    "reference-word-budget",
                    f"Skill support file has {len(text.split())} words; split or shorten it.",
                    _rel(path),
                )
            )

    referenced = _referenced_resource_names(skill_dir)
    for path in _standard_files(skill_dir):
        if not _is_text_file(path):
            continue
        rel = path.relative_to(skill_dir).as_posix()
        if rel not in referenced:
            findings.append(
                Finding(
                    skill_name,
                    "low",
                    "unreferenced-support-file",
                    f"Support file is not referenced by path from any skill text: {rel}.",
                    _rel(path),
                )
            )

    return findings


def scan(skill_dirs_to_scan: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for skill_dir in sorted(skill_dirs_to_scan):
        findings.extend(scan_skill(skill_dir))
    return sorted(findings, key=lambda item: (-severity_rank(item.severity), item.skill, item.rule, item.path))


def run_external_validator(
    roots: Iterable[Path], *, mode: str, command: str
) -> tuple[ExternalValidatorStatus, list[Finding]]:
    executable = shutil.which(command)
    available = executable is not None
    if mode == "off":
        return ExternalValidatorStatus(mode, command, available, False), []
    if not available:
        severity = "critical" if mode == "require" else "info"
        finding = Finding(
            "external-skill-validator",
            severity,
            "external-validator-unavailable",
            f"External CLI '{command}' is not installed; install agent-ecosystem/skill-validator to enable this check.",
            "tools/agent_skill_quality_guard.py",
        )
        return ExternalValidatorStatus(mode, command, False, False), ([finding] if mode == "require" else [])

    findings: list[Finding] = []
    for root in roots:
        if not root.exists():
            continue
        result = subprocess.run(
            [
                executable,
                "check",
                "--allow-extra-frontmatter",
                "--allow-dirs=agents,templates",
                str(root),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            continue
        severity = "medium" if result.returncode == 2 else "high"
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        first_line = output.splitlines()[0] if output else "skill-validator reported an issue"
        findings.append(
            Finding(
                "external-skill-validator",
                severity,
                "external-validator-failed",
                f"{root.relative_to(REPO_ROOT).as_posix()}: {first_line[:220]}",
                "tools/agent_skill_quality_guard.py",
            )
        )
    return ExternalValidatorStatus(mode, command, True, True), findings


def render_markdown(
    findings: list[Finding], scanned: list[Path], external_status: ExternalValidatorStatus
) -> str:
    lines = [
        "# Agent Skill Quality Guard",
        "",
        f"Skills scanned: {len(scanned)}",
        f"Findings: {len(findings)}",
        (
            "External skill-validator: "
            f"{'executed' if external_status.executed else 'not executed'} "
            f"({external_status.mode}, available={str(external_status.available).lower()})"
        ),
        "",
    ]
    if not findings:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"
    lines.extend(["| Skill | Severity | Rule | Path | Message |", "|---|---|---|---|---|"])
    for finding in findings:
        lines.append(
            f"| `{finding.skill}` | {finding.severity} | `{finding.rule}` | `{finding.path}` | {finding.message} |"
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roots", nargs="+", type=Path, default=list(DEFAULT_ROOTS))
    parser.add_argument("--skill-dir", action="append", type=Path, default=[])
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument(
        "--fail-on",
        choices=[*SEVERITY_ORDER, "never"],
        default="high",
        help="Exit non-zero when a finding has this severity or higher.",
    )
    parser.add_argument(
        "--external-validator",
        choices=("off", "if-available", "require"),
        default="if-available",
        help="Run agent-ecosystem/skill-validator when installed, or require it explicitly.",
    )
    parser.add_argument("--external-validator-command", default="skill-validator")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    roots = [path if path.is_absolute() else REPO_ROOT / path for path in args.roots]
    explicit = [path if path.is_absolute() else REPO_ROOT / path for path in args.skill_dir]
    scanned = changed_skill_dirs(args.base_ref, roots) if args.changed_only else skill_dirs(roots, explicit)
    local_findings = scan(scanned)
    external_status, external_findings = run_external_validator(
        roots,
        mode=args.external_validator,
        command=args.external_validator_command,
    )
    findings = sorted(
        [*local_findings, *external_findings],
        key=lambda item: (-severity_rank(item.severity), item.skill, item.rule, item.path),
    )

    payload = {
        "schema": "agilab.agent_skill_quality_guard.v1",
        "skills_scanned": [_rel(path) for path in scanned],
        "external_validator": asdict(external_status),
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    if args.json_output:
        args.json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(findings, scanned, external_status)
    if args.markdown_output:
        args.markdown_output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")

    if args.fail_on != "never":
        threshold = severity_rank(args.fail_on)
        blocking = [finding for finding in findings if severity_rank(finding.severity) >= threshold]
        if blocking:
            print(
                f"ERROR: {len(blocking)} finding(s) at {args.fail_on} or above in agent skills.",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
