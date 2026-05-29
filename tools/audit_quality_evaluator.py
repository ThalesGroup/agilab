#!/usr/bin/env python3
"""Score AGILAB audit/review Markdown artifacts against a quality rubric."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Callable, Sequence


SCHEMA = "agilab.audit_quality_evaluator.v1"
DEFAULT_MIN_SCORE = 80


@dataclass(frozen=True)
class RubricResult:
    id: str
    label: str
    weight: int
    score: int
    evidence: tuple[str, ...]
    guidance: str


@dataclass(frozen=True)
class RubricItem:
    id: str
    label: str
    weight: int
    scorer: Callable[[str], tuple[float, tuple[str, ...]]]
    guidance: str


@dataclass(frozen=True)
class ArchitectureCheck:
    id: str
    label: str
    patterns: tuple[str, ...]
    guidance: str


ARCHITECTURE_CHECKS: tuple[ArchitectureCheck, ...] = (
    ArchitectureCheck(
        "product_boundary",
        "Product boundary",
        (r"\btrusted-operator\b", r"\breproducibility workbench\b", r"\bproduction MLOps\b"),
        "State AGILAB's trusted-operator workbench role and non-production-MLOps boundary.",
    ),
    ArchitectureCheck(
        "architecture_planes",
        "Architecture planes",
        (r"\bcontrol plane\b", r"\bpayload plane\b", r"\bevidence plane\b"),
        "Name the control, payload, and evidence planes involved.",
    ),
    ArchitectureCheck(
        "app_page_dependency_boundary",
        "App/page dependency boundary",
        (r"\bapps-pages\b", r"\bagi-pages\b", r"\bapp-agnostic\b", r"\bproject-specific dependenc"),
        "Explain that app-specific dependencies belong in app/page packages, not generic apps-pages or agi-pages.",
    ),
    ArchitectureCheck(
        "cross_platform_boundary",
        "Cross-platform boundary",
        (r"\bLinux\b", r"\bmacOS\b", r"\bWindows\b"),
        "State which Linux/macOS/Windows assumptions were checked or remain residual risk.",
    ),
    ArchitectureCheck(
        "release_truth_boundary",
        "Release truth boundary",
        (r"\brelease proof\b", r"\bpackage split\b", r"\bdocs mirror\b", r"\bpublic claims?\b"),
        "Tie shipped claims to release proof, package split, docs mirror, and public evidence.",
    ),
)


PREFLIGHT_LINES = (
    "AGILAB deep-audit preflight",
    "",
    "Before writing a final audit, inspect enough current evidence to explain:",
    "- product boundary: trusted-operator reproducibility workbench, not standalone production MLOps",
    "- architecture planes: control plane, payload plane, evidence plane",
    "- package boundary: lean base, optional extras, split apps/pages",
    "- app/page dependency boundary: project-specific dependencies stay out of generic apps-pages and agi-pages",
    "- cross-platform boundary: Linux, macOS, and Windows assumptions",
    "- execution trust boundary: generated code, notebooks, external apps, workers, page bundles, cluster execution",
    "- release truth: docs mirror, package split, changelog, release proof, PyPI/GitHub/HF evidence",
    "",
    "Useful first-read anchors:",
    "- pyproject.toml",
    "- tools/package_split_contract.py",
    "- src/agilab/lib/agi-pages/src/agi_pages/__init__.py",
    "- src/agilab/apps-pages/README.md",
    "- README.md",
    "- SECURITY.md",
    "- ADOPTION.md",
    "- CHANGELOG.md",
    "- docs/source/release-proof.rst",
    "- .github/workflows/pypi-publish.yaml",
    "",
    "Useful commands:",
    "- git status --short --branch --untracked-files=no",
    "- git log --oneline -5",
    "- find src/agilab/core -maxdepth 3 -name pyproject.toml -print",
    "- rg -n \"AGILAB_PUBLIC_BIND|pickle\\\\.load|subprocess|create_subprocess|shell=True|apps-pages|agi-pages|release proof|package split|Windows|macOS|Linux\" src/agilab tools docs test",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _headings(text: str) -> list[str]:
    return [match.group(1).strip().lower() for match in re.finditer(r"(?m)^#{1,4}\s+(.+?)\s*$", text)]


def _has_heading(text: str, *needles: str) -> bool:
    headings = _headings(text)
    return any(any(needle in heading for needle in needles) for heading in headings)


def _count_patterns(text: str, patterns: Sequence[str], *, flags: int = re.IGNORECASE) -> int:
    return sum(len(re.findall(pattern, text, flags)) for pattern in patterns)


def _ratio(count: int, target: int) -> float:
    if target <= 0:
        return 1.0
    return min(1.0, count / target)


def _score_from_booleans(*values: bool) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def architecture_evidence(text: str) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for check in ARCHITECTURE_CHECKS:
        matched = [pattern for pattern in check.patterns if re.search(pattern, text, re.IGNORECASE)]
        checks.append(
            {
                "id": check.id,
                "label": check.label,
                "status": "pass" if len(matched) == len(check.patterns) else "fail",
                "matched": len(matched),
                "required": len(check.patterns),
                "guidance": check.guidance,
            }
        )
    passed = sum(1 for check in checks if check["status"] == "pass")
    return {
        "passed": passed,
        "required": len(checks),
        "status": "pass" if passed == len(checks) else "fail",
        "checks": checks,
    }


def _scope_score(text: str) -> tuple[float, tuple[str, ...]]:
    evidence: list[str] = []
    has_scope = _has_heading(text, "scope") or re.search(r"\bscope\b", text, re.IGNORECASE)
    has_limits = re.search(r"\b(out of scope|limits?|sampled|not inspected|residual risk)", text, re.IGNORECASE)
    has_method = re.search(r"\b(method|commands?|evidence used|inspected|read pass)", text, re.IGNORECASE)
    if has_scope:
        evidence.append("scope is stated")
    if has_limits:
        evidence.append("limits or sampling are stated")
    if has_method:
        evidence.append("method/evidence collection is stated")
    return _score_from_booleans(bool(has_scope), bool(has_limits), bool(has_method)), tuple(evidence)


def _executive_score(text: str) -> tuple[float, tuple[str, ...]]:
    verdict_terms = _count_patterns(text, (r"\bverdict\b", r"\bgo\b", r"\bconditional go\b", r"\bno-go\b"))
    summary = _has_heading(text, "executive summary", "summary", "verdict")
    thesis = bool(re.search(r"\b(thesis|dominant|root cause|bottom line)\b", text, re.IGNORECASE))
    evidence = []
    if summary:
        evidence.append("executive/verdict section found")
    if verdict_terms:
        evidence.append(f"{verdict_terms} verdict/go-no-go terms")
    if thesis:
        evidence.append("thesis/root-cause language found")
    return _score_from_booleans(summary, verdict_terms > 0, thesis), tuple(evidence)


def _evidence_score(text: str) -> tuple[float, tuple[str, ...]]:
    file_refs = re.findall(
        r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\:\d+(?::\d+)?)?",
        text,
    )
    command_refs = re.findall(
        r"\b(?:uv --preview-features|pytest|python tools/|./dev|workflow_parity\.py|git status|rg -n)\b",
        text,
    )
    line_refs = [ref for ref in file_refs if re.search(r":\d+", ref)]
    evidence = []
    if file_refs:
        evidence.append(f"{len(file_refs)} file references")
    if line_refs:
        evidence.append(f"{len(line_refs)} line references")
    if command_refs:
        evidence.append(f"{len(command_refs)} command references")
    score = 0.5 * _ratio(len(file_refs), 6) + 0.3 * _ratio(len(line_refs), 3) + 0.2 * _ratio(len(command_refs), 2)
    return score, tuple(evidence)


def _severity_score(text: str) -> tuple[float, tuple[str, ...]]:
    severities = re.findall(r"\b(CRITICAL|HIGH|MED-HIGH|MED|LOW|P0|P1|P2|P3)\b", text)
    has_findings = _has_heading(text, "finding", "findings") or bool(re.search(r"\bfinding\s+\d+", text, re.IGNORECASE))
    has_priority_table = bool(re.search(r"\|\s*#\s*\|\s*Severity\s*\|", text, re.IGNORECASE))
    evidence = []
    if severities:
        evidence.append(f"{len(severities)} severity markers")
    if has_findings:
        evidence.append("findings section found")
    if has_priority_table:
        evidence.append("prioritized severity table found")
    return _score_from_booleans(bool(severities), has_findings, has_priority_table), tuple(evidence)


def _mechanism_score(text: str) -> tuple[float, tuple[str, ...]]:
    terms = {
        "mechanism": r"\bmechanism\b",
        "impact": r"\bimpact\b",
        "blast radius": r"\bblast radius\b",
        "recommendation": r"\brecommendation\b",
    }
    present = {name: bool(re.search(pattern, text, re.IGNORECASE)) for name, pattern in terms.items()}
    evidence = tuple(f"{name} covered" for name, value in present.items() if value)
    return _score_from_booleans(*present.values()), evidence


def _architecture_score(text: str) -> tuple[float, tuple[str, ...]]:
    architecture = _has_heading(text, "architecture", "topology", "module")
    package_terms = _count_patterns(text, (r"\bpackage\b", r"\bmodule\b", r"\bcontrol plane\b", r"\bpayload plane\b", r"\bevidence plane\b"))
    boundary_terms = _count_patterns(text, (r"\bboundar", r"\bhandoff\b", r"\bruntime\b", r"\bworkflow\b"))
    foundation = architecture_evidence(text)
    evidence = []
    if architecture:
        evidence.append("architecture/topology section found")
    if package_terms:
        evidence.append(f"{package_terms} package/module/plane terms")
    if boundary_terms:
        evidence.append(f"{boundary_terms} boundary/runtime terms")
    evidence.append(f"{foundation['passed']}/{foundation['required']} architecture-foundation checks")
    return _score_from_booleans(
        architecture,
        package_terms >= 3,
        boundary_terms >= 3,
        foundation["status"] == "pass",
    ), tuple(evidence)


def _security_release_score(text: str) -> tuple[float, tuple[str, ...]]:
    security = _has_heading(text, "security")
    release = _has_heading(text, "release", "packaging", "supply")
    risk_terms = _count_patterns(
        text,
        (
            r"\bsecret",
            r"\bcredential",
            r"\bshell",
            r"\bsubprocess",
            r"\bpickle",
            r"\bpublic bind",
            r"\bMCP\b",
            r"\bprovenance",
            r"\bSBOM\b",
            r"\bPyPI\b",
        ),
    )
    evidence = []
    if security:
        evidence.append("security section found")
    if release:
        evidence.append("release/packaging section found")
    if risk_terms:
        evidence.append(f"{risk_terms} security/release risk terms")
    return _score_from_booleans(security, release, risk_terms >= 4), tuple(evidence)


def _validation_score(text: str) -> tuple[float, tuple[str, ...]]:
    validation = _has_heading(text, "testing", "validation", "regression")
    commands = _count_patterns(text, (r"\bpytest\b", r"\bworkflow_parity\.py\b", r"\b./dev\b", r"\buv --preview-features\b"))
    gaps = bool(re.search(r"\b(gap|missing test|residual risk|unverified|not run)\b", text, re.IGNORECASE))
    evidence = []
    if validation:
        evidence.append("testing/validation section found")
    if commands:
        evidence.append(f"{commands} validation command references")
    if gaps:
        evidence.append("gaps/residual risk are stated")
    return _score_from_booleans(validation, commands > 0, gaps), tuple(evidence)


def _recommendation_score(text: str) -> tuple[float, tuple[str, ...]]:
    recommendations = _has_heading(text, "prioritized recommendations", "recommendations", "next steps")
    action_terms = _count_patterns(text, (r"\bfix\b", r"\badd\b", r"\bcentralize\b", r"\breplace\b", r"\brequire\b", r"\bvalidate\b"))
    table = bool(re.search(r"\|\s*#\s*\|.*\|\s*Action\s*\|", text, re.IGNORECASE))
    evidence = []
    if recommendations:
        evidence.append("recommendations section found")
    if action_terms:
        evidence.append(f"{action_terms} action verbs")
    if table:
        evidence.append("action table found")
    return _score_from_booleans(recommendations, action_terms >= 4, table), tuple(evidence)


def _bottom_line_score(text: str) -> tuple[float, tuple[str, ...]]:
    bottom = _has_heading(text, "bottom line", "conclusion")
    adoption = bool(re.search(r"\b(local|shared|cluster|production|multi-tenant|adoption boundary|go|no-go)\b", text, re.IGNORECASE))
    evidence = []
    if bottom:
        evidence.append("bottom-line/conclusion section found")
    if adoption:
        evidence.append("adoption boundary language found")
    return _score_from_booleans(bottom, adoption), tuple(evidence)


RUBRIC: tuple[RubricItem, ...] = (
    RubricItem("scope", "Scope, method, and limits", 10, _scope_score, "State what was inspected, sampled, and out of scope."),
    RubricItem("executive", "Executive verdict and thesis", 10, _executive_score, "Start with a verdict, thesis, and go/no-go boundary."),
    RubricItem("evidence", "Concrete evidence and references", 15, _evidence_score, "Cite files, lines, commands, logs, or public evidence."),
    RubricItem("severity", "Severity and prioritization", 10, _severity_score, "Use severity labels and a prioritized finding/action structure."),
    RubricItem("mechanism", "Mechanism, impact, and blast radius", 12, _mechanism_score, "Explain how the issue works, impact, affected surfaces, and fix."),
    RubricItem("architecture", "Architecture and founding principles", 10, _architecture_score, "Explain package/module topology, runtime boundaries, app/page dependency boundaries, and cross-platform assumptions."),
    RubricItem("security_release", "Security, packaging, and release posture", 10, _security_release_score, "Cover security boundaries plus packaging/release evidence."),
    RubricItem("validation", "Testing and regression posture", 10, _validation_score, "Name validation commands, missing tests, and residual risks."),
    RubricItem("recommendations", "Prioritized recommendations", 9, _recommendation_score, "Provide concrete next actions and validation per action."),
    RubricItem("bottom_line", "Bottom line", 4, _bottom_line_score, "Close with a concise adoption-boundary judgement."),
)


def evaluate_text(text: str) -> dict[str, object]:
    results: list[RubricResult] = []
    for item in RUBRIC:
        ratio, evidence = item.scorer(text)
        ratio = max(0.0, min(1.0, ratio))
        results.append(
            RubricResult(
                id=item.id,
                label=item.label,
                weight=item.weight,
                score=round(item.weight * ratio),
                evidence=evidence,
                guidance=item.guidance,
            )
        )
    total = sum(result.score for result in results)
    max_score = sum(item.weight for item in RUBRIC)
    missing = [
        {
            "id": result.id,
            "label": result.label,
            "score": result.score,
            "weight": result.weight,
            "guidance": result.guidance,
        }
        for result in results
        if result.score < result.weight
    ]
    architecture = architecture_evidence(text)
    return {
        "schema": SCHEMA,
        "generated_at": _utc_now(),
        "score": total,
        "max_score": max_score,
        "grade": _grade(total),
        "status": "pass" if total >= DEFAULT_MIN_SCORE else "review",
        "rubric": [
            {
                "id": result.id,
                "label": result.label,
                "score": result.score,
                "weight": result.weight,
                "evidence": list(result.evidence),
                "guidance": result.guidance,
            }
            for result in results
        ],
        "missing_or_partial": missing,
        "architecture_evidence": architecture,
    }


def _grade(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 80:
        return "strong"
    if score >= 65:
        return "adequate"
    if score >= 50:
        return "weak"
    return "poor"


def _text_report(payload: dict[str, object], *, min_score: int) -> str:
    lines = [
        f"Audit quality score: {payload['score']}/{payload['max_score']} ({payload['grade']})",
        f"Threshold: {min_score}",
    ]
    for item in payload["rubric"]:  # type: ignore[index]
        row = item  # type: ignore[assignment]
        lines.append(f"- {row['label']}: {row['score']}/{row['weight']}")
        evidence = row.get("evidence", [])
        if evidence:
            lines.append(f"  evidence: {', '.join(evidence)}")
        if row["score"] < row["weight"]:
            lines.append(f"  improve: {row['guidance']}")
    architecture = payload.get("architecture_evidence", {})
    if isinstance(architecture, dict):
        lines.append(
            f"Architecture evidence: {architecture.get('passed')}/{architecture.get('required')} "
            f"({architecture.get('status')})"
        )
        for check in architecture.get("checks", []):
            if isinstance(check, dict) and check.get("status") != "pass":
                lines.append(f"  missing: {check.get('label')} - {check.get('guidance')}")
    return "\n".join(lines)


def _preflight_report() -> str:
    return "\n".join(PREFLIGHT_LINES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_markdown", type=Path, nargs="?", help="Markdown audit/review document to score.")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE, help="Fail when score is below this value.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a text report.")
    parser.add_argument("--output", type=Path, help="Optional path to write the JSON report.")
    parser.add_argument("--preflight", action="store_true", help="Print the AGILAB deep-audit architecture preflight checklist.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.preflight:
        print(_preflight_report())
        return 0
    if args.audit_markdown is None:
        raise SystemExit("audit_markdown is required unless --preflight is used")
    text = args.audit_markdown.read_text(encoding="utf-8")
    payload = evaluate_text(text)
    payload["source"] = str(args.audit_markdown)
    payload["threshold"] = args.min_score
    payload["status"] = "pass" if int(payload["score"]) >= args.min_score else "fail"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_text_report(payload, min_score=args.min_score))

    return 0 if int(payload["score"]) >= args.min_score else 1


if __name__ == "__main__":
    raise SystemExit(main())
