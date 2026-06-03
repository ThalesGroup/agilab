#!/usr/bin/env python3
"""Fail on deprecated public wording in AGILAB diagram assets."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_SOURCE = REPO_ROOT / "docs" / "source"
DIAGRAM_SUFFIXES = {".svg", ".dot", ".mmd"}

GENERIC_TOUR_DIAGRAMS = {
    "diagrams/agilab_readme_tour.svg",
    "diagrams/agilab_social_card.svg",
}

GLOBAL_DEPRECATED_PHRASES = {
    "Mission Decision AGILAB demo card": "Decision Evidence AGILAB demo card",
    "Mission Decision Demo": "Decision Evidence Demo",
    "to Decision Engine": "to Decision Evidence",
    "agi-pages provider": "agi-pages umbrella/provider package",
    "wheel-only": "wheel and source distribution, or source-only when explicitly documented",
    "wheel only": "wheel and source distribution, or source-only when explicitly documented",
}

GENERIC_TOUR_DEPRECATED_PHRASES = {
    "UAV Relay Queue": "built-in full-tour demo",
    "uav_relay_queue_project": "built-in full-tour demo",
    "flight_telemetry_project": "built-in first-proof demo",
}


@dataclass(frozen=True)
class DiagramWordingViolation:
    path: str
    line: int
    phrase: str
    suggestion: str
    rule: str


def _diagram_paths(docs_source: Path) -> list[Path]:
    if not docs_source.exists():
        return []
    return sorted(
        path
        for path in docs_source.rglob("*")
        if path.is_file() and path.suffix.lower() in DIAGRAM_SUFFIXES
    )


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _scan_phrases(
    *,
    text: str,
    relative_path: str,
    phrases: dict[str, str],
    rule: str,
) -> list[DiagramWordingViolation]:
    violations: list[DiagramWordingViolation] = []
    for phrase, suggestion in phrases.items():
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            violations.append(
                DiagramWordingViolation(
                    path=relative_path,
                    line=_line_number(text, index),
                    phrase=phrase,
                    suggestion=suggestion,
                    rule=rule,
                )
            )
            start = index + len(phrase)
    return violations


def collect_violations(docs_source: Path = DEFAULT_DOCS_SOURCE) -> list[DiagramWordingViolation]:
    docs_source = docs_source.resolve()
    violations: list[DiagramWordingViolation] = []
    for path in _diagram_paths(docs_source):
        relative_path = path.relative_to(docs_source).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            violations.append(
                DiagramWordingViolation(
                    path=relative_path,
                    line=1,
                    phrase="<unreadable>",
                    suggestion=str(exc),
                    rule="readable-diagram-source",
                )
            )
            continue
        violations.extend(
            _scan_phrases(
                text=text,
                relative_path=relative_path,
                phrases=GLOBAL_DEPRECATED_PHRASES,
                rule="global-deprecated-diagram-wording",
            )
        )
        if relative_path in GENERIC_TOUR_DIAGRAMS:
            violations.extend(
                _scan_phrases(
                    text=text,
                    relative_path=relative_path,
                    phrases=GENERIC_TOUR_DEPRECATED_PHRASES,
                    rule="generic-tour-diagrams-must-stay-app-agnostic",
                )
            )
    return violations


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-source",
        type=Path,
        default=DEFAULT_DOCS_SOURCE,
        help="Docs source directory to scan. Defaults to docs/source.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def _render_text(violations: Sequence[DiagramWordingViolation]) -> str:
    if not violations:
        return "diagram wording check passed"
    lines = ["diagram wording check failed:"]
    for violation in violations:
        lines.append(
            f"- {violation.path}:{violation.line}: {violation.rule}: "
            f"{violation.phrase!r} -> {violation.suggestion!r}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    violations = collect_violations(args.docs_source)
    if args.json:
        print(json.dumps([asdict(violation) for violation in violations], indent=2))
    else:
        print(_render_text(violations))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
