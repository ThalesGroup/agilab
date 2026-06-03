#!/usr/bin/env python3
"""Scan repo-managed agent skills for review-worthy security and scope risks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = (REPO_ROOT / ".claude" / "skills", REPO_ROOT / ".codex" / "skills")
SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")
NETWORK_RE = re.compile(r"\b(https?://|requests\.|httpx\.|urllib\.request|curl\s+|wget\s+|gradio_client|socket\.)")
ENV_RE = re.compile(r"\b(os\.environ|os\.getenv|load_dotenv|[A-Z][A-Z0-9_]*(TOKEN|KEY|SECRET|PASSWORD))\b")
SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]"
    r"(?!(?:<|\$|sk-test|example|dummy|your-|your_|xxx|\\.\\.\\.))[^'\"\n]{12,}"
)
ABSOLUTE_PRIVATE_PATH_RE = re.compile(r"(/Users/[^/\s]+|/home/[^/\s]+|C:\\Users\\[^\\\s]+)")
RISKY_ALLOWED_TOOL_RE = re.compile(r"^allowed-tools:\s*(?P<tools>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    skill: str
    severity: str
    rule: str
    message: str
    path: str


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.index(severity)


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


def _text_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pptx", ".docx"}:
            continue
        files.append(path)
    return files


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _front_matter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def scan_skill(skill_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    skill_name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8", errors="ignore")
    front_matter = _front_matter(text)

    if "license:" not in front_matter:
        findings.append(
            Finding(skill_name, "high", "missing-license", "SKILL.md is missing required license front matter.", _rel(skill_md))
        )
    allowed = RISKY_ALLOWED_TOOL_RE.search(text)
    has_powerful_tools = bool(allowed and any(token in allowed.group("tools") for token in ("Bash", "Write", "Edit")))
    if has_powerful_tools:
        findings.append(
            Finding(
                skill_name,
                "low",
                "powerful-allowed-tools",
                "Skill declares powerful allowed-tools; review the workflow before installing elsewhere.",
                _rel(skill_md),
            )
        )

    saw_env = False
    saw_network = False
    for path in _text_files(skill_dir):
        content = path.read_text(encoding="utf-8", errors="ignore")
        if SECRET_VALUE_RE.search(content):
            findings.append(
                Finding(skill_name, "critical", "literal-secret", "Possible literal secret or token value committed.", _rel(path))
            )
        if ABSOLUTE_PRIVATE_PATH_RE.search(content):
            findings.append(
                Finding(skill_name, "high", "private-absolute-path", "Machine-local absolute path appears in skill content.", _rel(path))
            )
        saw_env = saw_env or bool(ENV_RE.search(content))
        saw_network = saw_network or bool(NETWORK_RE.search(content))

    if saw_env and saw_network:
        findings.append(
            Finding(
                skill_name,
                "medium",
                "env-and-network",
                "Skill content references both environment variables/secrets and network access; review data flow.",
                _rel(skill_md),
            )
        )
    elif saw_network:
        findings.append(
            Finding(skill_name, "low", "network-access", "Skill content references network access or external URLs.", _rel(skill_md))
        )
    elif saw_env:
        findings.append(
            Finding(skill_name, "low", "environment-access", "Skill content references environment variables or local secrets.", _rel(skill_md))
        )
    if "compatibility:" not in front_matter and (saw_env or saw_network or has_powerful_tools):
        findings.append(
            Finding(
                skill_name,
                "info",
                "missing-compatibility",
                "Consider adding compatibility metadata when a skill uses network, shell, or local services.",
                _rel(skill_md),
            )
        )

    return findings


def scan(skill_dirs_to_scan: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for skill_dir in sorted(skill_dirs_to_scan):
        findings.extend(scan_skill(skill_dir))
    return sorted(findings, key=lambda item: (-severity_rank(item.severity), item.skill, item.rule, item.path))


def render_markdown(findings: list[Finding], scanned: list[Path]) -> str:
    lines = [
        "# Agent Skill Security Scan",
        "",
        f"Skills scanned: {len(scanned)}",
        f"Findings: {len(findings)}",
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
        default="critical",
        help="Exit non-zero when a finding has this severity or higher.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    roots = [path if path.is_absolute() else REPO_ROOT / path for path in args.roots]
    explicit = [path if path.is_absolute() else REPO_ROOT / path for path in args.skill_dir]
    scanned = changed_skill_dirs(args.base_ref, roots) if args.changed_only else skill_dirs(roots, explicit)
    findings = scan(scanned)

    payload = {
        "schema": "agilab.agent_skill_security_scan.v1",
        "skills_scanned": [_rel(path) for path in scanned],
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    if args.json_output:
        args.json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(findings, scanned)
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
