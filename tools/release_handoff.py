#!/usr/bin/env python3
"""Generate a release handoff from current AGILAB release preflight state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

try:
    from pypi_project_preflight import build_report
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.pypi_project_preflight import build_report


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "agilab.release_handoff.v1"


def _run_text(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _safe_filename(tag: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", tag.strip()).strip("-")


def default_output_path(tag: str) -> Path:
    return ROOT / "tools" / "release_handoffs" / f"{_safe_filename(tag)}-handoff.md"


def render_handoff(tag: str, preflight: dict[str, Any]) -> str:
    head = _run_text(["git", "rev-parse", "HEAD"]) or "unknown"
    guardrails = _run_text(
        [
            "gh",
            "run",
            "list",
            "--repo",
            "ThalesGroup/agilab",
            "--workflow",
            "repo-guardrails",
            "--branch",
            "main",
            "--limit",
            "1",
            "--json",
            "databaseId,status,conclusion,headSha,url",
        ]
    )
    blockers = preflight["blockers"]
    lines = [
        f"# AGILAB release handoff for {tag}",
        "",
        "Status: current",
        "",
        "Generated from repository state. Do not reuse old PyPI confirmation URLs.",
        "",
        "## Prepared repository state",
        "",
        f"- Current HEAD: `{head}`",
        f"- PyPI preflight status: `{preflight['status']}`",
        f"- PyPI projects checked: `{preflight['summary']['checked']}`",
        f"- PyPI blockers: `{preflight['summary']['blockers']}`",
    ]
    if guardrails:
        lines.extend(["- Latest main guardrail run JSON:", "", "```json", guardrails, "```"])
    lines.extend(["", "## Pending trusted publishers", ""])
    if not blockers:
        lines.append("No missing PyPI projects were detected. Dispatch the release workflow directly.")
    else:
        for blocker in blockers:
            command = blocker.get("pending_publisher_command") or (
                "gh workflow run pypi-pending-trusted-publisher.yaml "
                "-R ThalesGroup/agilab --ref main "
                f"-f project_name={blocker['pypi_project']} "
                f"-f pypi_environment={blocker['pypi_environment']}"
            )
            lines.extend(
                [
                    f"### {blocker['pypi_project']}",
                    "",
                    f"- Status: `{blocker['status']}`",
                    f"- Expected version: `{blocker['version']}`",
                    f"- Environment: `{blocker['pypi_environment']}`",
                    "",
                    "```bash",
                    command,
                    "```",
                    "",
                ]
            )
    lines.extend(
        [
            "## Release dispatch",
            "",
            "```bash",
            "gh workflow run pypi-publish.yaml \\",
            "  -R ThalesGroup/agilab \\",
            "  --ref main \\",
            f"  -f release_tag={tag}",
            "```",
            "",
            "## Release watch",
            "",
            "```bash",
            "run_id=$(gh run list -R ThalesGroup/agilab \\",
            "  --workflow pypi-publish.yaml \\",
            "  --limit 1 \\",
            "  --json databaseId \\",
            "  --jq '.[0].databaseId')",
            "gh run watch -R ThalesGroup/agilab \"$run_id\" --exit-status",
            "```",
            "",
            "## Post-release truth check",
            "",
            "```bash",
            f"uv run python tools/release_status.py --tag {tag}",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    preflight = build_report(repo_root=ROOT)
    output = args.output or default_output_path(args.tag)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_handoff(args.tag, preflight), encoding="utf-8")
    result = {
        "schema": SCHEMA_VERSION,
        "tag": args.tag,
        "output": str(output),
        "preflight_status": preflight["status"],
        "blockers": preflight["summary"]["blockers"],
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
