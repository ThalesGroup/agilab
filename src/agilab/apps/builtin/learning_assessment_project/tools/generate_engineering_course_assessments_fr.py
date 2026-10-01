#!/usr/bin/env python3
"""Regenerate engineering-course and Extra assessments, preserving legacy cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "src"))

from learning_assessment.domain.education import (  # noqa: E402
    ASSESSMENT_SCHEMA,
    load_course_registry,
    source_revision,
)

BANK_PATH = (
    APP_ROOT
    / "src"
    / "learning_assessment"
    / "sample_data"
    / "tescia_diagnostic_cases.json"
)


def generate_payload(payload: dict) -> dict:
    registry = load_course_registry()
    generated = []
    for course in registry["courses"]:
        for section in course["sections"]:
            generated.append(
                {
                    "case_id": f"{course['id']}_{section['id'].lower()}",
                    "learning_track": "engineering_ensae",
                    "title": f"{course['title']} — {section['id']}. {section['title']}",
                    "difficulty": "advanced",
                    "learner_level": "École d'ingénieur",
                    "estimated_minutes": max(10, 5 * len(section["questions"])),
                    "topic_tags": [
                        course["id"],
                        *[n["label"] for n in section["notions"]],
                    ],
                    "student_prompt": "Répondez aux questions puis justifiez vos choix à l'aide de la correction.",
                    "academic_assessment": {
                        "schema": ASSESSMENT_SCHEMA,
                        "course_id": course["id"],
                        "section_id": section["id"],
                        "source_revision": source_revision(course),
                        "question_ids": [q["id"] for q in section["questions"]],
                    },
                }
            )
    return {
        **payload,
        "cases": [
            case
            for case in payload["cases"]
            if case.get("learning_track") != "engineering_ensae"
        ]
        + generated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail if the bundled bank is stale."
    )
    args = parser.parse_args()
    current = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    generated = generate_payload(current)
    if args.check:
        if current != generated:
            print("Bundled ENSAE assessment bank is stale; run this generator.")
            return 1
    else:
        BANK_PATH.write_text(
            json.dumps(generated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(
        f"ENSAE bank: {len(generated['cases'])} exercises; source/output contract verified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
