#!/usr/bin/env python3
"""Validate AGILAB's root agent-instruction contract.

This guard covers the top-level files that coding agents read before they reach
repo-managed skills. Skill-specific checks live in ``agent_skill_quality_guard``;
this tool checks that the root runbooks, public agent docs, and capability
manifest still describe the same executable contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.agent_instruction_contract.v1"
CAPABILITY_COMMAND_ID = "agent-instruction-contract"
CATALOG_PATHS = (
    "AGENTS.md",
    "AGENT_CONVENTIONS.md",
    "tools/agent_workflows.md",
    "AGENT_SKILLS.md",
    "llms.txt",
    "llms-full.txt",
    "agilab-capabilities.json",
    "agenticweb.md",
)


@dataclass(frozen=True)
class RequiredTerm:
    label: str
    text: str


@dataclass(frozen=True)
class FileContract:
    path: str
    purpose: str
    required_terms: tuple[RequiredTerm, ...]
    max_lines: int | None = None


@dataclass(frozen=True)
class Issue:
    severity: str
    rule: str
    path: str
    message: str


CONTRACTS: tuple[FileContract, ...] = (
    FileContract(
        path="AGENTS.md",
        purpose="full operator runbook",
        required_terms=(
            RequiredTerm("uv", "uv --preview-features extra-build-dependencies"),
            RequiredTerm("dev-shortcuts", "./dev <shortcut>"),
            RequiredTerm("local-first", "Local-first validation"),
            RequiredTerm("pr-first", "PR-first publishing"),
            RequiredTerm("product-goal", "AGILAB product goal"),
            RequiredTerm("shared-core", "Shared core approval gate"),
            RequiredTerm("no-fallbacks", "No silent fallbacks"),
            RequiredTerm("bug-sweep", "Bug-class sweep"),
            RequiredTerm("docs-source", "Docs source of truth"),
            RequiredTerm("agent-contract", "Agent instruction contract"),
        ),
    ),
    FileContract(
        path="AGENT_CONVENTIONS.md",
        purpose="short local-agent contract",
        max_lines=120,
        required_terms=(
            RequiredTerm("core-rules", "## Core rules"),
            RequiredTerm("validation-defaults", "## Validation defaults"),
            RequiredTerm("review-defaults", "## Review defaults"),
            RequiredTerm("agilab-cautions", "## AGILAB-specific cautions"),
            RequiredTerm("capability-manifest", "agilab-capabilities.json"),
            RequiredTerm("agenticweb", "agenticweb.md"),
            RequiredTerm("contract-command", "python3 tools/agent_instruction_contract.py --check"),
        ),
    ),
    FileContract(
        path="tools/agent_workflows.md",
        purpose="repo agent workflow reference",
        required_terms=(
            RequiredTerm("schema", SCHEMA),
            RequiredTerm("contract-command", "python3 tools/agent_instruction_contract.py --check"),
            RequiredTerm("short-runbook", "AGENT_CONVENTIONS.md"),
            RequiredTerm("full-runbook", "AGENTS.md"),
            RequiredTerm("capability-manifest", "agilab-capabilities.json"),
            RequiredTerm("agenticweb", "agenticweb.md"),
        ),
    ),
    FileContract(
        path="docs/source/agent-workflows.rst",
        purpose="public agent workflow docs mirror",
        required_terms=(
            RequiredTerm("schema", SCHEMA),
            RequiredTerm("contract-command", "python3 tools/agent_instruction_contract.py --check"),
            RequiredTerm("short-runbook", "AGENT_CONVENTIONS.md"),
            RequiredTerm("full-runbook", "AGENTS.md"),
            RequiredTerm("capability-manifest", "agilab-capabilities.json"),
            RequiredTerm("agenticweb", "agenticweb.md"),
        ),
    ),
)


def _rel(path: Path, *, root: Path = REPO_ROOT) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON file: {_rel(path)}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {_rel(path)}: {exc}") from exc


def _check_file_contract(root: Path, contract: FileContract) -> list[Issue]:
    path = root / contract.path
    if not path.exists():
        return [
            Issue(
                "error",
                "agent-instruction-file-exists",
                contract.path,
                f"missing {contract.purpose}: {contract.path}",
            )
        ]
    text = _read_text(path)
    issues: list[Issue] = []
    for term in contract.required_terms:
        if term.text not in text:
            issues.append(
                Issue(
                    "error",
                    "agent-instruction-required-term",
                    contract.path,
                    f"missing required {term.label!r} marker: {term.text}",
                )
            )
    if contract.max_lines is not None:
        line_count = len(text.splitlines())
        if line_count > contract.max_lines:
            issues.append(
                Issue(
                    "warning",
                    "agent-instruction-too-long",
                    contract.path,
                    f"{contract.path} has {line_count} lines; keep the short contract under {contract.max_lines}",
                )
            )
    return issues


def _expect_mapping(value: Any, *, path: str, issues: list[Issue]) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    issues.append(Issue("error", "agent-instruction-json-object", path, "expected a JSON object"))
    return {}


def _iter_mapping_rows(value: Any, *, path: str, issues: list[Issue]) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        issues.append(Issue("error", "agent-instruction-json-list", path, "expected a JSON list"))
        return []
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if isinstance(row, Mapping):
            rows.append(row)
        else:
            issues.append(
                Issue(
                    "error",
                    "agent-instruction-json-object",
                    f"{path}[{index}]",
                    "expected a JSON object",
                )
            )
    return rows


def _check_capability_manifest(root: Path) -> list[Issue]:
    path = root / "agilab-capabilities.json"
    issues: list[Issue] = []
    payload = _expect_mapping(_load_json(path), path="agilab-capabilities.json", issues=issues)
    commands = {
        str(row.get("id")): row
        for row in _iter_mapping_rows(payload.get("cli_commands"), path="cli_commands", issues=issues)
    }
    command = commands.get(CAPABILITY_COMMAND_ID)
    if command is None:
        issues.append(
            Issue(
                "error",
                "agent-instruction-capability-command",
                "agilab-capabilities.json.cli_commands",
                f"missing CLI command id {CAPABILITY_COMMAND_ID!r}",
            )
        )
    else:
        command_text = command.get("command")
        if command_text != "python3 tools/agent_instruction_contract.py --check":
            issues.append(
                Issue(
                    "error",
                    "agent-instruction-capability-command",
                    "agilab-capabilities.json.cli_commands.agent-instruction-contract.command",
                    "capability command must match the documented local guard",
                )
            )
        evidence_outputs = command.get("evidence_outputs")
        if not isinstance(evidence_outputs, list) or SCHEMA not in evidence_outputs:
            issues.append(
                Issue(
                    "error",
                    "agent-instruction-capability-evidence",
                    "agilab-capabilities.json.cli_commands.agent-instruction-contract.evidence_outputs",
                    f"capability evidence outputs must include {SCHEMA}",
                )
            )
        docs = command.get("docs")
        if not isinstance(docs, list) or "docs/source/agent-workflows.rst" not in docs:
            issues.append(
                Issue(
                    "error",
                    "agent-instruction-capability-docs",
                    "agilab-capabilities.json.cli_commands.agent-instruction-contract.docs",
                    "capability command must point to docs/source/agent-workflows.rst",
                )
            )

    catalog_paths = {
        str(row.get("path"))
        for row in _iter_mapping_rows(payload.get("catalog_files"), path="catalog_files", issues=issues)
    }
    for required_path in CATALOG_PATHS:
        if required_path not in catalog_paths:
            issues.append(
                Issue(
                    "error",
                    "agent-instruction-catalog-path",
                    "agilab-capabilities.json.catalog_files",
                    f"catalog files must list {required_path}",
                )
            )
    return issues


def build_report(root: Path = REPO_ROOT) -> dict[str, Any]:
    root = root.resolve()
    issues: list[Issue] = []
    for contract in CONTRACTS:
        issues.extend(_check_file_contract(root, contract))
    try:
        issues.extend(_check_capability_manifest(root))
    except ValueError as exc:
        issues.append(
            Issue(
                "error",
                "agent-instruction-capability-json",
                "agilab-capabilities.json",
                str(exc),
            )
        )
    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    return {
        "schema": SCHEMA,
        "status": "fail" if errors else "pass",
        "root": _rel(root),
        "files": [asdict(contract) for contract in CONTRACTS],
        "summary": {
            "file_contract_count": len(CONTRACTS),
            "catalog_path_count": len(CATALOG_PATHS),
            "issue_count": len(issues),
            "error_count": errors,
            "warning_count": warnings,
        },
        "issues": [asdict(issue) for issue in issues],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Agent Instruction Contract",
        "",
        f"Schema: `{report['schema']}`",
        f"Status: **{report['status']}**",
        f"Issues: {report['summary']['issue_count']}",
        "",
    ]
    issues = report.get("issues", [])
    if not issues:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"
    lines.extend(["| Severity | Rule | Path | Message |", "|---|---|---|---|"])
    for raw in issues:
        issue = _expect_mapping(raw, path="issues[]", issues=[])
        lines.append(
            f"| {issue.get('severity')} | `{issue.get('rule')}` | `{issue.get('path')}` | {issue.get('message')} |"
        )
    return "\n".join(lines) + "\n"


def _write_optional(path: Path | None, text: str) -> None:
    if path is not None:
        path.write_text(text, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check", action="store_true", help="exit non-zero when the contract fails")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.root)
    json_text = json.dumps(report, indent=2) + "\n"
    markdown = render_markdown(report)
    _write_optional(args.json_output, json_text)
    _write_optional(args.markdown_output, markdown)
    if args.json:
        print(json_text, end="")
    elif args.markdown_output is None:
        print(markdown, end="")
    if args.check and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
