#!/usr/bin/env python3
"""Generate a non-legal regulatory readiness screening report from AGILAB evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.regulatory_readiness.v1"
DEFAULT_PROFILE = "eu-ai-act-screening"
SOURCE_REVIEWED_ON = date(2026, 5, 31)
SOURCE_STALE_AFTER_DAYS = 90
DISCLAIMER = (
    "This is an engineering readiness screen for review planning. It is not "
    "legal advice, a compliance certification, a conformity assessment, or a "
    "production governance approval."
)


@dataclass(frozen=True)
class SourceReference:
    id: str
    title: str
    url: str
    publisher: str
    reviewed_on: str


@dataclass(frozen=True)
class ReadinessControl:
    id: str
    title: str
    area: str
    article_refs: tuple[str, ...]
    description: str
    evidence_terms: tuple[str, ...]
    gap: str
    next_step: str
    required: bool = True


@dataclass(frozen=True)
class Issue:
    severity: str
    rule: str
    path: str
    message: str


OFFICIAL_SOURCES: tuple[SourceReference, ...] = (
    SourceReference(
        id="ec-ai-act-overview",
        title="European Commission AI Act overview",
        url="https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
        publisher="European Commission",
        reviewed_on=SOURCE_REVIEWED_ON.isoformat(),
    ),
    SourceReference(
        id="ai-act-service-desk-timeline",
        title="AI Act Service Desk implementation timeline",
        url="https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act",
        publisher="European Commission AI Act Service Desk",
        reviewed_on=SOURCE_REVIEWED_ON.isoformat(),
    ),
    SourceReference(
        id="eurlex-2024-1689",
        title="Regulation (EU) 2024/1689 on EUR-Lex",
        url="https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
        publisher="EUR-Lex",
        reviewed_on=SOURCE_REVIEWED_ON.isoformat(),
    ),
)


CONTROLS: tuple[ReadinessControl, ...] = (
    ReadinessControl(
        id="system-purpose-context",
        title="System purpose and deployment context",
        area="scope",
        article_refs=("risk-based approach", "Article 3 definitions"),
        description="The reviewed AI system has a purpose, context, and AGILAB run target.",
        evidence_terms=("purpose", "system", "description", "project", "app", "intended_use"),
        gap="No system purpose or deployment context was found.",
        next_step="Provide --system-description or include purpose/context in the run evidence.",
    ),
    ReadinessControl(
        id="risk-screening-input",
        title="Risk-screening input",
        area="risk-classification",
        article_refs=("Article 5", "Article 6", "Annex III", "Article 50"),
        description="A human-readable system description is available for initial risk triage.",
        evidence_terms=(),
        gap="No system description was provided for risk screening.",
        next_step="Rerun with --system-description '<what the AI system does and where it is used>'.",
    ),
    ReadinessControl(
        id="run-traceability",
        title="Run traceability",
        area="record-keeping",
        article_refs=("Article 12", "Article 26", "Article 72"),
        description="AGILAB run evidence exists and can be hashed for review.",
        evidence_terms=("run_manifest", "command", "status", "duration", "timestamp", "started_at", "finished_at"),
        gap="No parseable run manifest was provided.",
        next_step="Provide --run-manifest <run_manifest.json> from the AGILAB run under review.",
    ),
    ReadinessControl(
        id="artifact-lineage",
        title="Artifact and lineage inventory",
        area="technical-documentation",
        article_refs=("Article 11", "Annex IV"),
        description="Produced artifacts, outputs, or lineage files are present and hashable.",
        evidence_terms=("artifact", "artifacts", "output", "outputs", "lineage", "manifest", "result"),
        gap="No artifact or lineage evidence was found.",
        next_step="Attach output artifacts, lineage exports, proof capsules, or reducer summaries with --evidence.",
    ),
    ReadinessControl(
        id="data-governance-evidence",
        title="Data governance evidence",
        area="data-governance",
        article_refs=("Article 10",),
        description="Data source, dataset, lineage, or validation notes are available for review.",
        evidence_terms=("data", "dataset", "lineage", "input", "training", "validation", "test", "datasheet"),
        gap="No data governance or dataset evidence was found.",
        next_step="Attach data-lineage notes, dataset cards, validation summaries, or data-artifact lane reports.",
    ),
    ReadinessControl(
        id="technical-documentation",
        title="Technical documentation evidence",
        area="technical-documentation",
        article_refs=("Article 11", "Annex IV"),
        description="Technical documentation, reports, or README-style run context is present.",
        evidence_terms=("technical", "documentation", "readme", "report", "architecture", "model-card", "model_card"),
        gap="No technical documentation evidence was found.",
        next_step="Attach the run report, technical notes, architecture summary, or model card.",
    ),
    ReadinessControl(
        id="human-oversight-evidence",
        title="Human oversight evidence",
        area="human-oversight",
        article_refs=("Article 14",),
        description="Human review, approval, oversight, or decision evidence is present.",
        evidence_terms=("human", "oversight", "review", "approval", "approver", "decision", "operator"),
        gap="No human oversight evidence was found.",
        next_step="Attach review notes, approval records, operator decision logs, or promotion dossier evidence.",
    ),
    ReadinessControl(
        id="transparency-instructions",
        title="Transparency and instructions evidence",
        area="transparency",
        article_refs=("Article 13", "Article 50"),
        description="User-facing instructions, disclosure, or transparency notes are available.",
        evidence_terms=("transparency", "instructions", "disclosure", "user-guide", "user_guide", "usage"),
        gap="No transparency or instructions-for-use evidence was found.",
        next_step="Attach deployer instructions, user notices, AI disclosure text, or transparency notes.",
    ),
    ReadinessControl(
        id="security-posture-evidence",
        title="Security posture evidence",
        area="security",
        article_refs=("Article 15",),
        description="Security, SBOM, vulnerability, or AGILAB security-check evidence is present.",
        evidence_terms=("security", "sbom", "pip-audit", "vulnerability", "cybersecurity", "dependency"),
        gap="No security posture evidence was found.",
        next_step="Attach security-check output, SBOM, pip-audit report, or dependency policy evidence.",
    ),
    ReadinessControl(
        id="source-freshness",
        title="Regulatory source freshness",
        area="source-control",
        article_refs=("official sources",),
        description="The built-in regulatory source references have been reviewed recently enough for screening.",
        evidence_terms=(),
        gap="Built-in source references are stale.",
        next_step="Verify the official sources again and rerun with --source-review-date YYYY-MM-DD.",
        required=False,
    ),
)


PROHIBITED_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "harmful manipulation or deception": ("subliminal", "manipulat", "deceiv", "dark pattern"),
    "social scoring": ("social scoring", "social score", "social credit"),
    "criminal-risk profiling": ("criminal prediction", "recidivism", "predictive policing"),
    "untargeted facial scraping": ("facial scraping", "scrape facial", "facial recognition database"),
    "workplace or education emotion recognition": (
        "emotion recognition workplace",
        "emotion recognition school",
        "emotion detection employee",
    ),
    "sensitive biometric categorisation": ("biometric categorisation", "infer sensitive", "religion classification"),
}

HIGH_RISK_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "biometrics": ("biometric", "facial recognition", "fingerprint", "iris"),
    "critical infrastructure": ("critical infrastructure", "power grid", "water supply", "traffic control"),
    "education": ("education", "school", "student", "exam", "grading", "proctoring"),
    "employment": (
        "recruit",
        "hiring",
        "job applicant",
        "applicant",
        "candidate",
        "cv",
        "resume",
        "employee monitor",
        "promotion",
    ),
    "essential services": ("credit scoring", "loan", "insurance", "benefit eligibility", "public service"),
    "law enforcement": ("law enforcement", "police", "crime", "evidence reliability"),
    "migration and border control": ("migration", "asylum", "visa", "border control", "immigration"),
    "justice and democratic processes": ("judicial", "court", "election", "voting", "democratic process"),
}

TRANSPARENCY_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "chatbot or virtual assistant": ("chatbot", "chat bot", "virtual assistant", "conversational ai"),
    "generated content": ("generative ai", "generated content", "generated image", "generated video", "generated text"),
    "deepfake or synthetic media": ("deepfake", "synthetic media"),
    "large language model": ("llm", "large language model", "foundation model"),
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


def _resolve_path(raw: str | Path, *, root: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_text(value: Any, *, limit: int = 500) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if len(parts) >= limit:
            return
        if isinstance(item, Mapping):
            for key, nested in item.items():
                parts.append(str(key))
                visit(nested)
        elif isinstance(item, list | tuple | set):
            for nested in item:
                visit(nested)
        elif item is not None:
            parts.append(str(item))

    visit(value)
    return " ".join(parts).lower()


def _match_keyword_groups(text: str, groups: Mapping[str, tuple[str, ...]]) -> list[dict[str, Any]]:
    haystack = text.lower()
    matches: list[dict[str, Any]] = []
    for label, keywords in groups.items():
        matched = sorted(keyword for keyword in keywords if keyword in haystack)
        if matched:
            matches.append({"label": label, "matched_keywords": matched})
    return matches


def screen_description(description: str) -> dict[str, Any]:
    if not description.strip():
        return {
            "risk_bucket": "unknown",
            "method": "keyword screen for review triage; not legal classification",
            "description_provided": False,
            "flags": [],
        }
    prohibited = _match_keyword_groups(description, PROHIBITED_KEYWORDS)
    high_risk = _match_keyword_groups(description, HIGH_RISK_KEYWORDS)
    transparency = _match_keyword_groups(description, TRANSPARENCY_KEYWORDS)
    if prohibited:
        bucket = "potential-prohibited-review"
    elif high_risk:
        bucket = "potential-high-risk-review"
    elif transparency:
        bucket = "potential-transparency-obligation-review"
    else:
        bucket = "minimal-or-no-risk-keyword-screen"
    return {
        "risk_bucket": bucket,
        "method": "keyword screen for review triage; not legal classification",
        "description_provided": True,
        "flags": [
            {"category": "prohibited-practice-review", "matches": prohibited},
            {"category": "high-risk-review", "matches": high_risk},
            {"category": "transparency-obligation-review", "matches": transparency},
        ],
    }


def _parse_source_review_date(raw: str | None) -> date:
    if not raw:
        return SOURCE_REVIEWED_ON
    return date.fromisoformat(raw)


def _source_review_state(reviewed_on: date, *, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    age_days = max(0, (today - reviewed_on).days)
    stale = age_days > SOURCE_STALE_AFTER_DAYS
    return {
        "reviewed_on": reviewed_on.isoformat(),
        "age_days": age_days,
        "stale_after_days": SOURCE_STALE_AFTER_DAYS,
        "status": "stale" if stale else "current",
        "references": [asdict(source) for source in OFFICIAL_SOURCES],
    }


def _parse_evidence_args(values: Iterable[str], *, root: Path) -> tuple[list[dict[str, Any]], list[Issue]]:
    known_controls = {control.id for control in CONTROLS}
    rows: list[dict[str, Any]] = []
    issues: list[Issue] = []
    for raw in values:
        control_hint = ""
        raw_path = raw
        if "=" in raw:
            maybe_control, maybe_path = raw.split("=", 1)
            if maybe_control in known_controls:
                control_hint = maybe_control
                raw_path = maybe_path
            else:
                issues.append(
                    Issue(
                        "warning",
                        "unknown-evidence-control",
                        maybe_control,
                        f"unknown readiness control {maybe_control!r}; evidence kept without explicit control mapping",
                    )
                )
        rows.append({"path": _resolve_path(raw_path, root=root), "control_hints": [control_hint] if control_hint else []})
    return rows, issues


def _scan_evidence_dirs(values: Iterable[Path], *, root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in values:
        directory = _resolve_path(raw, root=root)
        if not directory.is_dir():
            rows.append({"path": directory, "control_hints": []})
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file() and not item.name.startswith(".")):
            rows.append({"path": path, "control_hints": []})
    return rows


def _evidence_records(rows: Iterable[dict[str, Any]], *, root: Path) -> list[dict[str, Any]]:
    merged: dict[Path, set[str]] = {}
    for row in rows:
        path = Path(row["path"]).expanduser().resolve()
        merged.setdefault(path, set()).update(str(hint) for hint in row.get("control_hints", []) if hint)
    records: list[dict[str, Any]] = []
    for path, hints in sorted(merged.items(), key=lambda item: _rel(item[0], root=root)):
        exists = path.is_file()
        records.append(
            {
                "path": _rel(path, root=root),
                "exists": exists,
                "bytes": path.stat().st_size if exists else None,
                "sha256": _sha256_file(path) if exists else None,
                "control_hints": sorted(hints),
            }
        )
    return records


def _record_blob(records: Iterable[Mapping[str, Any]]) -> str:
    return " ".join(str(record.get("path", "")) for record in records).lower()


def _control_has_explicit_evidence(control: ReadinessControl, records: Iterable[Mapping[str, Any]]) -> list[str]:
    matches = []
    for record in records:
        if control.id in record.get("control_hints", []) and record.get("exists"):
            matches.append(str(record.get("path")))
    return matches


def _control_has_term_evidence(control: ReadinessControl, records: Iterable[Mapping[str, Any]], manifest_text: str) -> list[str]:
    matches: list[str] = []
    record_blob = _record_blob(records)
    for term in control.evidence_terms:
        if term and term.lower() in manifest_text:
            matches.append(f"run_manifest:{term}")
        if term and term.lower() in record_blob:
            matches.append(f"evidence_path:{term}")
    return sorted(set(matches))


def _evaluate_controls(
    *,
    system_description: str,
    run_manifest_path: Path | None,
    run_manifest_payload: Any,
    run_manifest_error: str,
    evidence: list[dict[str, Any]],
    source_state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[Issue]]:
    issues: list[Issue] = []
    manifest_text = _flatten_text(run_manifest_payload) if run_manifest_payload is not None else ""
    existing_evidence = [record for record in evidence if record.get("exists")]
    rows: list[dict[str, Any]] = []
    for control in CONTROLS:
        matched: list[str] = []
        status = "gap" if control.required else "warning"

        if control.id == "system-purpose-context":
            if system_description.strip():
                matched.append("system_description")
            matched.extend(_control_has_term_evidence(control, existing_evidence, manifest_text))
        elif control.id == "risk-screening-input":
            if system_description.strip():
                matched.append("system_description")
        elif control.id == "run-traceability":
            if run_manifest_path is not None and run_manifest_payload is not None and not run_manifest_error:
                matched.append(_rel(run_manifest_path.resolve(), root=REPO_ROOT))
            matched.extend(_control_has_term_evidence(control, existing_evidence, manifest_text))
        elif control.id == "artifact-lineage":
            if existing_evidence:
                matched.append("hashable_evidence_files")
            matched.extend(_control_has_term_evidence(control, existing_evidence, manifest_text))
        elif control.id == "source-freshness":
            status = "pass" if source_state.get("status") == "current" else "warning"
            if status == "pass":
                matched.append(f"source_reviewed_on:{source_state.get('reviewed_on')}")
        else:
            matched.extend(_control_has_explicit_evidence(control, existing_evidence))
            matched.extend(_control_has_term_evidence(control, existing_evidence, manifest_text))

        if control.id != "source-freshness":
            if matched:
                status = "pass"
            elif not control.required:
                status = "warning"

        if status != "pass":
            issues.append(
                Issue(
                    "warning" if status == "warning" else "gap",
                    f"regulatory-readiness-{status}",
                    control.id,
                    control.gap,
                )
            )
        rows.append(
            {
                "id": control.id,
                "title": control.title,
                "area": control.area,
                "article_refs": list(control.article_refs),
                "status": status,
                "required": control.required,
                "description": control.description,
                "matched_evidence": sorted(set(matched)),
                "gap": control.gap if status != "pass" else "",
                "next_step": control.next_step if status != "pass" else "",
            }
        )

    if run_manifest_error:
        issues.append(
            Issue(
                "gap",
                "regulatory-readiness-run-manifest-invalid",
                str(run_manifest_path or ""),
                run_manifest_error,
            )
        )
    return rows, issues


def build_report(
    *,
    root: Path = REPO_ROOT,
    profile_id: str = DEFAULT_PROFILE,
    run_manifest: Path | None = None,
    evidence_values: Iterable[str] = (),
    evidence_dirs: Iterable[Path] = (),
    system_description: str = "",
    source_review_date: str | None = None,
) -> dict[str, Any]:
    if profile_id != DEFAULT_PROFILE:
        raise ValueError(f"unknown profile {profile_id!r}; expected {DEFAULT_PROFILE!r}")
    root = root.expanduser().resolve()
    reviewed_on = _parse_source_review_date(source_review_date)
    source_state = _source_review_state(reviewed_on)
    run_manifest_path = _resolve_path(run_manifest, root=root) if run_manifest else None
    run_manifest_payload: Any = None
    run_manifest_error = ""
    evidence_rows, evidence_issues = _parse_evidence_args(evidence_values, root=root)
    if run_manifest_path is not None:
        evidence_rows.append({"path": run_manifest_path, "control_hints": ["run-traceability"]})
        try:
            run_manifest_payload = _load_json(run_manifest_path)
        except FileNotFoundError:
            run_manifest_error = f"run manifest does not exist: {_rel(run_manifest_path, root=root)}"
        except json.JSONDecodeError as exc:
            run_manifest_error = f"run manifest is not valid JSON: {exc}"
    evidence_rows.extend(_scan_evidence_dirs(evidence_dirs, root=root))
    evidence = _evidence_records(evidence_rows, root=root)
    controls, control_issues = _evaluate_controls(
        system_description=system_description,
        run_manifest_path=run_manifest_path,
        run_manifest_payload=run_manifest_payload,
        run_manifest_error=run_manifest_error,
        evidence=evidence,
        source_state=source_state,
    )
    issues = [*evidence_issues, *control_issues]
    gap_count = sum(1 for control in controls if control["status"] == "gap")
    warning_count = sum(1 for control in controls if control["status"] == "warning")
    status = "ready-for-review" if gap_count == 0 and warning_count == 0 else "needs-review"
    if gap_count:
        status = "needs-evidence"
    return {
        "schema": SCHEMA,
        "status": status,
        "generated_at_utc": _utc_now(),
        "profile": {
            "id": profile_id,
            "description": "EU AI Act-oriented engineering readiness screen for AGILAB run evidence.",
            "proves": "Evidence presence, hashability, and gap visibility for regulatory review planning.",
            "does_not_prove": DISCLAIMER,
        },
        "disclaimer": DISCLAIMER,
        "root": _rel(root, root=REPO_ROOT),
        "inputs": {
            "run_manifest": _rel(run_manifest_path, root=root) if run_manifest_path else "",
            "system_description_provided": bool(system_description.strip()),
            "evidence_file_count": len(evidence),
        },
        "source_review": source_state,
        "screening": screen_description(system_description),
        "evidence": evidence,
        "controls": controls,
        "summary": {
            "control_count": len(controls),
            "passed_count": sum(1 for control in controls if control["status"] == "pass"),
            "gap_count": gap_count,
            "warning_count": warning_count,
            "issue_count": len(issues),
            "hashable_evidence_count": sum(1 for item in evidence if item.get("sha256")),
        },
        "issues": [asdict(issue) for issue in issues],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Regulatory Readiness Report",
        "",
        f"Schema: `{report['schema']}`",
        f"Status: **{report['status']}**",
        f"Disclaimer: {report['disclaimer']}",
        "",
        "## Summary",
        "",
        f"- Controls: {summary['passed_count']}/{summary['control_count']} passed",
        f"- Gaps: {summary['gap_count']}",
        f"- Warnings: {summary['warning_count']}",
        f"- Hashable evidence files: {summary['hashable_evidence_count']}",
        "",
        "## Screening",
        "",
        f"- Risk bucket: `{report['screening']['risk_bucket']}`",
        f"- Method: {report['screening']['method']}",
        "",
        "## Controls",
        "",
        "| Status | Control | Area | Next step |",
        "|---|---|---|---|",
    ]
    for control in report["controls"]:
        lines.append(
            f"| `{control['status']}` | `{control['id']}` {control['title']} | "
            f"{control['area']} | {control['next_step'] or '-'} |"
        )
    lines.extend(["", "## Sources", ""])
    for source in report["source_review"]["references"]:
        lines.append(f"- {source['title']}: {source['url']}")
    return "\n".join(lines) + "\n"


def _write_optional(path: Path | None, text: str) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--profile", default=DEFAULT_PROFILE, choices=[DEFAULT_PROFILE])
    parser.add_argument("--run-manifest", type=Path)
    parser.add_argument("--system-description", default="")
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Evidence file path, optionally as control_id=path.",
    )
    parser.add_argument("--evidence-dir", type=Path, action="append", default=[])
    parser.add_argument("--source-review-date", help="YYYY-MM-DD date when official sources were last reviewed")
    parser.add_argument("--check", action="store_true", help="exit non-zero unless status is ready-for-review")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(
            root=args.root,
            profile_id=args.profile,
            run_manifest=args.run_manifest,
            evidence_values=args.evidence,
            evidence_dirs=args.evidence_dir,
            system_description=args.system_description,
            source_review_date=args.source_review_date,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json_text = json.dumps(report, indent=2) + "\n"
    markdown = render_markdown(report)
    _write_optional(args.json_output, json_text)
    _write_optional(args.markdown_output, markdown)
    if args.json:
        print(json_text, end="")
    elif args.markdown_output is None:
        print(markdown, end="")
    if args.check and report["status"] != "ready-for-review":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
