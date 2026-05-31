#!/usr/bin/env python3
"""Validate local data/document artifact-lane handoff bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.data_artifact_lane_contract.v1"


@dataclass(frozen=True)
class RoleDir:
    id: str
    default_path: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class ArtifactRule:
    id: str
    role: str
    patterns: tuple[str, ...]
    description: str
    min_count: int = 1
    required: bool = True


@dataclass(frozen=True)
class Profile:
    id: str
    description: str
    proves: str
    does_not_prove: str
    roles: tuple[RoleDir, ...]
    artifacts: tuple[ArtifactRule, ...]


@dataclass(frozen=True)
class Issue:
    severity: str
    rule: str
    path: str
    message: str


PROFILES: Mapping[str, Profile] = {
    "data-analysis": Profile(
        id="data-analysis",
        description="Data-analyst style bundle with raw inputs, cleaned data, aggregates, plots, and a report.",
        proves="The expected local data-analysis handoff artifacts are present and hashable.",
        does_not_prove="It does not prove analytic correctness, business interpretation, privacy compliance, or production data freshness.",
        roles=(
            RoleDir("raw", "_in", "raw input files"),
            RoleDir("clean", "_out/clean", "cleaned tabular outputs"),
            RoleDir("aggregate", "_out/aggregates", "aggregate tables and human report"),
            RoleDir("visualization", "_out/viz", "visualization artifacts"),
        ),
        artifacts=(
            ArtifactRule("raw-inputs", "raw", ("*.csv", "*.xlsx", "*.xls", "*.parquet", "*.json"), "raw input tables"),
            ArtifactRule("cleaned-data", "clean", ("*.csv", "*.parquet", "*.json"), "cleaned data files"),
            ArtifactRule("aggregate-data", "aggregate", ("*.csv", "*.parquet", "*.json"), "aggregate output tables"),
            ArtifactRule("human-report", "aggregate", ("REPORT.md", "*.md"), "human-readable Markdown report"),
            ArtifactRule("visualizations", "visualization", ("*.png", "*.svg", "*.html"), "visual evidence files"),
        ),
    ),
    "document-ingestion": Profile(
        id="document-ingestion",
        description="Document-ingestion lane with source documents, Markdown outputs, and processed originals.",
        proves="The expected local document-ingestion handoff artifacts are present and hashable.",
        does_not_prove="It does not prove OCR accuracy, semantic completeness, model quality, or background-service liveness.",
        roles=(
            RoleDir("input", "input", "incoming source documents"),
            RoleDir("output", "output", "converted Markdown outputs"),
            RoleDir("done", "done", "processed source documents"),
            RoleDir("error", "error", "failed source documents", required=False),
            RoleDir("logs", "logs", "operational logs", required=False),
        ),
        artifacts=(
            ArtifactRule("markdown-outputs", "output", ("*.md",), "converted Markdown outputs"),
            ArtifactRule("processed-documents", "done", ("*.pdf",), "processed source PDFs"),
            ArtifactRule("pending-documents", "input", ("*.pdf",), "pending source PDFs", min_count=0, required=False),
            ArtifactRule("failed-documents", "error", ("*.pdf",), "failed source PDFs", min_count=0, required=False),
            ArtifactRule("logs", "logs", ("*.log", "*.txt"), "optional operational logs", min_count=0, required=False),
        ),
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path, *, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_path(raw: str, *, root: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def parse_role_overrides(values: list[str], *, root: Path) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--dir must use role=path syntax, got: {value}")
        role, raw_path = value.split("=", 1)
        role = role.strip()
        raw_path = raw_path.strip()
        if not role or not raw_path:
            raise ValueError(f"--dir must use non-empty role=path syntax, got: {value}")
        overrides[role] = _resolve_path(raw_path, root=root)
    return overrides


def _role_paths(profile: Profile, *, root: Path, overrides: Mapping[str, Path]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for role in profile.roles:
        paths[role.id] = overrides.get(role.id) or _resolve_path(role.default_path, root=root)
    return paths


def _match_files(directory: Path, patterns: tuple[str, ...]) -> list[Path]:
    if not directory.is_dir():
        return []
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(path for path in directory.glob(pattern) if path.is_file())
    return sorted(set(matches))


def _artifact_record(path: Path, *, root: Path, role: str, rule_id: str) -> dict[str, Any]:
    return {
        "role": role,
        "rule": rule_id,
        "path": _rel(path, root=root),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def build_contract_report(
    *,
    root: Path,
    profile_id: str,
    role_overrides: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    if profile_id not in PROFILES:
        raise ValueError(f"unknown profile {profile_id!r}; expected one of {sorted(PROFILES)}")
    profile = PROFILES[profile_id]
    overrides = role_overrides or {}
    known_roles = {role.id for role in profile.roles}
    unknown_roles = sorted(set(overrides) - known_roles)
    issues: list[Issue] = []
    for role in unknown_roles:
        issues.append(
            Issue(
                "error",
                "unknown-role-override",
                role,
                f"profile {profile_id!r} has no role {role!r}",
            )
        )

    role_paths = _role_paths(profile, root=root, overrides=overrides)
    role_rows: list[dict[str, Any]] = []
    for role in profile.roles:
        path = role_paths[role.id]
        exists = path.is_dir()
        role_rows.append(
            {
                "id": role.id,
                "description": role.description,
                "path": _rel(path, root=root),
                "required": role.required,
                "exists": exists,
            }
        )
        if role.required and not exists:
            issues.append(
                Issue(
                    "error",
                    "required-directory-missing",
                    role.id,
                    f"required {role.description} directory is missing: {_rel(path, root=root)}",
                )
            )

    artifact_rows: list[dict[str, Any]] = []
    rule_rows: list[dict[str, Any]] = []
    for rule in profile.artifacts:
        directory = role_paths.get(rule.role, root / rule.role)
        matches = _match_files(directory, rule.patterns)
        rule_rows.append(
            {
                "id": rule.id,
                "role": rule.role,
                "description": rule.description,
                "patterns": list(rule.patterns),
                "required": rule.required,
                "min_count": rule.min_count,
                "match_count": len(matches),
            }
        )
        for path in matches:
            artifact_rows.append(_artifact_record(path, root=root, role=rule.role, rule_id=rule.id))
        if rule.required and len(matches) < rule.min_count:
            issues.append(
                Issue(
                    "error",
                    "required-artifact-missing",
                    rule.id,
                    (
                        f"expected at least {rule.min_count} artifact(s) for {rule.description} "
                        f"in role {rule.role!r}; patterns={list(rule.patterns)!r}"
                    ),
                )
            )

    artifact_rows = sorted(artifact_rows, key=lambda row: (str(row["role"]), str(row["path"])))
    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    return {
        "schema": SCHEMA,
        "status": "fail" if errors else "pass",
        "generated_at_utc": _utc_now(),
        "root": str(root),
        "profile": {
            "id": profile.id,
            "description": profile.description,
            "proves": profile.proves,
            "does_not_prove": profile.does_not_prove,
        },
        "summary": {
            "role_count": len(role_rows),
            "artifact_rule_count": len(rule_rows),
            "artifact_count": len(artifact_rows),
            "hashed_artifact_count": sum(1 for row in artifact_rows if row.get("sha256")),
            "issue_count": len(issues),
            "error_count": errors,
            "warning_count": warnings,
        },
        "roles": role_rows,
        "artifact_rules": rule_rows,
        "artifacts": artifact_rows,
        "issues": [asdict(issue) for issue in issues],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Data Artifact Lane Contract",
        "",
        f"Schema: `{report['schema']}`",
        f"Status: **{report['status']}**",
        f"Profile: `{report['profile']['id']}`",
        f"Artifacts: {report['summary']['artifact_count']}",
        f"Issues: {report['summary']['issue_count']}",
        "",
        f"Proves: {report['profile']['proves']}",
        f"Does not prove: {report['profile']['does_not_prove']}",
        "",
    ]
    if report.get("issues"):
        lines.extend(["## Issues", "", "| Severity | Rule | Path | Message |", "|---|---|---|---|"])
        for issue in report["issues"]:
            lines.append(
                f"| {issue['severity']} | `{issue['rule']}` | `{issue['path']}` | {issue['message']} |"
            )
        lines.append("")
    lines.extend(["## Artifact Rules", "", "| Rule | Role | Matches | Required |", "|---|---|---:|---|"])
    for rule in report["artifact_rules"]:
        lines.append(
            f"| `{rule['id']}` | `{rule['role']}` | {rule['match_count']} | {str(rule['required']).lower()} |"
        )
    return "\n".join(lines) + "\n"


def _write_optional(path: Path | None, text: str) -> None:
    if path is not None:
        path.expanduser().parent.mkdir(parents=True, exist_ok=True)
        path.expanduser().write_text(text, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="artifact lane root")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="data-analysis")
    parser.add_argument(
        "--dir",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="override a profile role directory; relative paths resolve under --root",
    )
    parser.add_argument("--check", action="store_true", help="exit non-zero when required contract checks fail")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    parser.add_argument("--markdown-output", type=Path, help="optional Markdown output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        overrides = parse_role_overrides(args.dir, root=root)
        report = build_contract_report(root=root, profile_id=args.profile, role_overrides=overrides)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(report)
    _write_optional(args.output, json_text)
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
