"""Shared native controls and provenance for academic question banks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from ..domain.education import (
    build_education_coverage_report,
    load_course_registry,
    resolve_academic_assessment,
)


def render_academic_answer(
    case: Mapping[str, Any],
    key_prefix: str,
    initial_answer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep blank choices and caller-scoped learner state across native rerenders."""
    from agi_web import python_ui as st

    _, _, questions = resolve_academic_assessment(case)
    initial = (initial_answer or {}).get("academic_answers", {})
    selected: dict[str, str] = {}
    for number, question in enumerate(questions, start=1):
        choices = question["choices"]
        options = list(choices)
        default = initial.get(question["id"])
        option = st.radio(
            f"{number}. {question['prompt']}",
            options,
            index=options.index(default) if default in options else None,
            format_func=choices.__getitem__,
            key=f"academic_answer_{key_prefix}_{question['id']}",
        )
        if option is not None:
            selected[question["id"]] = option
    return {"academic_answers": selected}


def academic_reference(case: Mapping[str, Any]) -> str:
    """Build a correction from the same bound questions used for grading."""
    _, _, questions = resolve_academic_assessment(case)
    return "\n\n".join(
        f"**{question['prompt']}**\n\n"
        f"{question['choices'][question['correct_choice']]}\n\n"
        f"{question['explanation']}"
        for question in questions
    )


def render_education_trace(catalog: Mapping[str, Any]) -> None:
    from agi_web import python_ui as st

    trace = catalog.get("education_trace")
    if not isinstance(trace, Mapping):
        return
    st.caption(
        " › ".join(
            str(value)
            for value in (
                trace["stage_label"],
                trace["course_title"],
                trace["section_title"],
            )
            if value
        )
    )
    if trace["assessment_kind"] == "curriculum_audit":
        st.info(
            "Ce scénario évalue un audit de programme ; sa note ne mesure pas la maîtrise mathématique de l'élève."
        )
    if trace.get("course_kind") == "extra":
        st.info("Extra — complément aux syllabus ENSAE.")
    if trace.get("prerequisite_course_ids"):
        titles = {
            course["id"]: course["title"]
            for course in load_course_registry()["courses"]
        }
        st.caption(
            "Prérequis : "
            + " ; ".join(
                titles[identity] for identity in trace["prerequisite_course_ids"]
            )
        )
    st.caption(
        "Notions : " + " ; ".join(notion["label"] for notion in trace["notions"])
    )
    for source in trace["sources"]:
        st.markdown(f"[{source['title']}]({source['url']})")
        st.caption(
            f"Référence revue le {source['reviewed_on']}. {source.get('scope', '')}"
        )


def render_education_coverage(cases: Sequence[Mapping[str, Any]], key_prefix: str) -> None:
    """Display and export the same material report for this bank's academic cases."""
    from agi_web import python_ui as st

    if not any("academic_assessment" in case for case in cases):
        return
    report = build_education_coverage_report(cases)
    st.subheader("Couverture des cours et Extra")
    st.caption(report["scope"])
    st.info(
        "Ce rapport compare les exercices de cette banque au référentiel livré. "
        "Il mesure la présence de supports ; aucune maîtrise d'un apprenant n'en est déduite."
    )
    columns = st.columns(3)
    with columns[0]:
        st.metric("Cours / Extra du référentiel", report["course_count"])
    with columns[1]:
        st.metric(
            "Chapitres avec exercices",
            report["section_count"] - len(report["missing_sections"]),
        )
    with columns[2]:
        st.metric("Questions présentes", report["question_count"])
    st.dataframe(
        [
            {
                "Cours": row["course_title"],
                "Chapitre": row["section_title"],
                "Exercices": row["exercise_count"],
                "Questions": row["question_count"],
                "Questions absentes": ", ".join(row["missing_questions"]),
                "Notions absentes": "; ".join(row["missing_notions"]),
            }
            for row in report["sections"]
        ],
        hide_index=True,
        width="stretch",
    )
    st.download_button(
        "Exporter la couverture des cours et Extra",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        file_name="learning_assessment_engineering_course_coverage_fr.json",
        mime="application/json",
        key=key_prefix + "_education_coverage_download",
    )
