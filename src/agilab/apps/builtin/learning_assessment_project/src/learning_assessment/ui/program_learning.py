"""French programme surface using the same validated banks as the worker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain import assessment_session as sessions
from ..domain.assessment_program import build_program_coverage_report
from ..domain.diagnostic import CASE_SCHEMA, validate_case_payload
from ..domain.diagnostic import catalog_metadata
from .academic_assessment import (
    academic_reference,
    render_academic_answer,
    render_education_coverage,
    render_education_trace,
)


MAX_BANK_BYTES = 8 * 1024 * 1024
MODE_LABELS = {
    "practice": "Entraînement",
    "positioning": "Positionnement",
    "transfer": "Évaluation de transfert",
    "example": "Exemple commenté",
}


def read_bank_bytes(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_BANK_BYTES:
        raise ValueError("Le programme dépasse 8 Mio.")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("La banque doit être un objet JSON.")
    return validate_case_payload(payload)


def configured_banks(env: Any, args: Any) -> list[Path]:
    """Resolve only the configured worker input; no sibling-repository probing."""
    if (
        env is None
        or args is None
        or not hasattr(args, "data_in")
        or not hasattr(args, "files")
    ):
        return []
    root = Path(args.data_in)
    if not root.is_absolute():
        resolver = getattr(env, "resolve_share_input_path", None) or getattr(
            env, "resolve_share_path", None
        )
        if not callable(resolver):
            return []
        root = Path(resolver(root))
    result = []
    for path in sorted(root.glob(args.files)):
        if not path.is_file() or path.stat().st_size > MAX_BANK_BYTES:
            continue
        payload = json.loads(path.read_bytes())
        if isinstance(payload, dict) and payload.get("schema") == CASE_SCHEMA:
            result.append(path)
    return result


def select_bank(bundled_path: Path, env: Any, args: Any) -> dict[str, Any] | None:
    from agi_web import python_ui as st

    with st.expander("Programme / banque d'exercices"):
        uploaded = st.file_uploader(
            "Importer une banque de programme JSON",
            type=["json"],
            key="learning_program_upload",
        )
        try:
            if uploaded is not None:
                return read_bank_bytes(uploaded.getvalue())
            configured = configured_banks(env, args)
            if configured:
                selected = st.selectbox(
                    "Banque configurée pour les workers",
                    configured,
                    format_func=lambda p: p.name,
                    key="learning_program_file",
                )
                if Path(selected).resolve() != bundled_path.resolve():
                    return read_bank_bytes(Path(selected).read_bytes())
        except (ValueError, OSError, TypeError) as exc:
            st.error(f"Programme invalide : {exc}")
            st.stop()
        st.caption(
            "Les banques importées sont locales à cette session. Le dossier de tentatives permet ensuite le traitement par les workers."
        )
    return None


def _reference(case: dict[str, Any]) -> str:
    if "academic_assessment" in case:
        return academic_reference(case)
    question = case.get("question_assessment")
    if question:
        if question["kind"] == "open_response":
            return question["reference_answer"]
        if question["kind"] == "numeric":
            return f"{question['expected']} {question['unit']}\n\n{question['explanation']}"
        return (
            "\n".join(
                f"- {question['choices'][c]}" for c in question["correct_choices"]
            )
            + "\n\n"
            + question["explanation"]
        )
    return str(case.get("root_cause", ""))


def _answer_widgets(case: dict[str, Any], key: str) -> dict[str, Any]:
    from agi_web import python_ui as st

    if "academic_assessment" in case:
        return render_academic_answer(case, key)
    question = case.get("question_assessment")
    if question:
        if question["kind"] == "numeric":
            response = st.number_input(
                "Votre résultat", value=None, key=key + "_number"
            )
            unit = st.text_input("Unité du résultat", value="", key=key + "_unit")
            return {"response": response, "unit": unit}
        if question["kind"] == "multiple_choice":
            return {
                "response": st.multiselect(
                    "Vos choix",
                    list(question["choices"]),
                    format_func=question["choices"].__getitem__,
                    key=key + "_choices",
                )
            }
        return {
            "response": st.text_area(
                "Votre raisonnement", value="", key=key + "_response", height=160
            )
        }
    return {
        "diagnosis": st.text_area("Diagnostic proposé", key=key + "_diagnosis"),
        "root_cause": st.text_area("Cause et justification", key=key + "_cause"),
        "evidence_ids": st.multiselect(
            "Preuves retenues",
            [e["id"] for e in case["evidence"]],
            key=key + "_evidence",
        ),
        "selected_fix_id": st.selectbox(
            "Correction proposée",
            [""] + [f["id"] for f in case["candidate_fixes"]],
            key=key + "_fix",
        ),
        "regression_test_ids": st.multiselect(
            "Vérifications retenues",
            [t["id"] for t in case["regression_tests"]],
            key=key + "_tests",
        ),
        "confidence": st.slider(
            "Confiance déclarée", 0.0, 1.0, 0.5, key=key + "_confidence"
        ),
    }


def _render_learning(bank: dict[str, Any], session: dict[str, Any], key: str) -> None:
    from agi_web import python_ui as st

    mode = st.selectbox(
        "Mode de travail",
        list(MODE_LABELS),
        format_func=MODE_LABELS.__getitem__,
        key=key + "_mode",
    )
    cases = [
        c for c in bank["cases"] if ("transfer_variant" in c) == (mode == "transfer")
    ]
    if not cases:
        st.info(
            "Ce programme ne contient pas de variante de transfert. Le corrigé d'entraînement ne peut pas servir d'épreuve de transfert."
        )
        return
    by_id = {c["case_id"]: c for c in cases}
    selected = st.selectbox(
        "Exercice",
        list(by_id),
        format_func=lambda identity: by_id[identity]["title"],
        key=key + "_exercise_" + mode,
    )
    case = by_id[selected]
    st.markdown(case["student_prompt"])
    render_education_trace(catalog_metadata(case))
    if "transfer_variant" in case:
        st.caption(case["transfer_variant"]["changes"])
    context = sessions.case_context(bank, selected)
    competencies = [
        c
        for c in bank.get("assessment_program", {}).get("competencies", [])
        if c["competency_id"] in context["competency_ids"]
    ]
    for competency in competencies:
        st.caption(f"Objectif : {competency['outcome']}")
        if competency["prerequisites"]:
            st.caption(
                "Prérequis conseillés : " + ", ".join(competency["prerequisites"])
            )
    if mode == "example":
        st.info(
            "Exemple commenté : cette lecture ne produit ni note ni preuve de maîtrise."
        )
        st.markdown(_reference(case))
        return
    previous = [
        a for a in session["attempts"] if a["case_id"] == selected and a["mode"] == mode
    ]
    if previous:
        st.caption(
            "Une tentative précédente existe. Un nouvel envoi sera conservé séparément ; il ne constitue pas une évaluation indépendante si le corrigé a déjà été consulté."
        )
    answer_key = key + "_" + selected + "_" + mode + "_" + str(len(previous))
    with st.form(answer_key + "_form"):
        answer = _answer_widgets(case, answer_key)
        sent = st.form_submit_button("Enregistrer ma réponse", type="primary")
    if sent:
        try:
            sessions.submit_attempt(session, bank, selected, answer, mode=mode)
            st.rerun()
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
    if previous:
        latest = previous[-1]
        evaluation = latest["evaluation"]
        if evaluation["student_score"] is not None:
            st.metric(
                "Résultat des réponses vérifiables / 100", evaluation["student_score"]
            )
        else:
            st.info(
                "Raisonnement enregistré, en attente de revue. Aucune note de compréhension automatique."
            )
        for feedback in evaluation["feedback"]:
            st.write(feedback)
        if mode == "practice":
            with st.expander("Correction et travail conseillé"):
                st.markdown(_reference(case))
                st.markdown(
                    case.get("question_assessment", {}).get(
                        "remediation",
                        "Reprendre les hypothèses, les preuves et les contre-exemples.",
                    )
                )
                for ref in context["source_refs"]:
                    st.caption(
                        f"Source : {ref['source_id']} — section {ref['section']}"
                    )
        else:
            st.caption(
                "La correction reste réservée à la revue de cette tentative. Un programme local ne constitue pas un examen surveillé."
            )


def _render_reviews(bank: dict[str, Any], session: dict[str, Any], key: str) -> None:
    from agi_web import python_ui as st

    if not session["attempts"]:
        st.info("Aucune tentative enregistrée.")
        return
    st.dataframe(
        [
            {
                "exercice": a["case_id"],
                "tentative": a["attempt_number"],
                "mode": MODE_LABELS[a["mode"]],
                "date": a["submitted_at"],
                "statut": "revu"
                if any(r["attempt_id"] == a["attempt_id"] for r in session["reviews"])
                else a["evaluation"]["status"],
                "note automatique": a["evaluation"]["student_score"],
            }
            for a in session["attempts"]
        ],
        hide_index=True,
    )
    with st.expander("Revue pédagogique d'une tentative"):
        attempts = {a["attempt_id"]: a for a in session["attempts"]}
        identity = st.selectbox(
            "Tentative à revoir",
            list(attempts),
            format_func=lambda i: (
                f"{attempts[i]['case_id']} — essai {attempts[i]['attempt_number']}"
            ),
            key=key + "_review_attempt",
        )
        attempt = attempts[identity]
        case = next(c for c in bank["cases"] if c["case_id"] == attempt["case_id"])
        st.write(attempt["answer"])
        st.markdown(_reference(case))
        criteria = case.get("question_assessment", {}).get(
            "criteria",
            [
                "Exactitude du raisonnement",
                "Justification par les preuves",
                "Limites et contre-exemples",
            ],
        )
        with st.form(key + "_review_" + identity):
            reviewer = st.text_input("Évaluateur", key=key + "_reviewer_" + identity)
            scores = {
                c: st.number_input(
                    c, 0, 4, value=None, key=key + "_score_" + identity + "_" + str(i)
                )
                for i, c in enumerate(criteria)
            }
            rationale = st.text_area(
                "Justification et prochaine activité",
                key=key + "_review_reason_" + identity,
            )
            save = st.form_submit_button("Enregistrer la revue")
        if save:
            try:
                sessions.review_attempt(
                    session,
                    bank,
                    identity,
                    reviewer=reviewer,
                    rationale=rationale,
                    scores=scores,
                )
                st.success(
                    "Revue conservée ; les réponses et revues antérieures restent dans le dossier."
                )
            except ValueError as exc:
                st.error(str(exc))
        st.caption(
            "Revue humaine déclarée : l'application n'atteste pas l'identité du correcteur. La grille 0–4 reste distincte des notes automatiques."
        )


def _render_practical(bank: dict[str, Any], session: dict[str, Any], key: str) -> None:
    from agi_web import python_ui as st

    competencies = {
        c["competency_id"]: c
        for c in bank.get("assessment_program", {}).get("competencies", [])
        if "practical_assessment" in c
    }
    if not competencies:
        st.info("Aucune épreuve pratique déclarée.")
        return
    identity = st.selectbox(
        "Épreuve pratique",
        list(competencies),
        format_func=lambda i: competencies[i]["title"],
        key=key + "_practical",
    )
    assessment = competencies[identity]["practical_assessment"]
    st.markdown(assessment["instructions"])
    st.write("Livrables attendus : " + "; ".join(assessment["deliverables"]))
    if assessment["artifact_refs"]:
        st.caption("Supports à consulter : " + "; ".join(assessment["artifact_refs"]))
    st.caption(
        "0 : absent/non attribuable ; 1 : procédure sans compréhension stable ; 2 : nominal correct ; 3 : rejouable et limites explicites ; 4 : comparaison contradictoire et décision justifiée."
    )
    with st.form(key + "_practical_" + identity):
        uploads = st.file_uploader(
            "Pièces du travail réalisé (4 Mio par pièce)",
            accept_multiple_files=True,
            key=key + "_pieces_" + identity,
        )
        scores = {
            c["criterion_id"]: st.number_input(
                c["description"],
                0,
                4,
                value=None,
                key=key + "_practical_score_" + identity + "_" + c["criterion_id"],
            )
            for c in assessment["rubric"]
        }
        reviewer = st.text_input(
            "Évaluateur de la réalisation", key=key + "_practical_reviewer_" + identity
        )
        rationale = st.text_area(
            "Vérifications réalisées, résultats négatifs et limites",
            key=key + "_practical_reason_" + identity,
        )
        safety = st.checkbox(
            "Sécurité et autorisation vérifiées",
            value=False,
            key=key + "_safety_" + identity,
        )
        integrity = st.checkbox(
            "Intégrité et attribution des preuves vérifiées",
            value=False,
            key=key + "_integrity_" + identity,
        )
        save = st.form_submit_button("Enregistrer la revue pratique")
    if save:
        try:
            names = [u.name for u in uploads]
            if len(names) != len(set(names)):
                raise ValueError("Deux pièces portent le même nom.")
            review = sessions.review_practical(
                session,
                bank,
                identity,
                reviewer=reviewer,
                rationale=rationale,
                scores=scores,
                artifacts={u.name: u.getvalue() for u in uploads},
                safety_authorized=safety,
                integrity_verified=integrity,
            )
            if review["status"] == "blocked":
                st.warning(
                    "Revue conservée, validation bloquée par une porte sécurité ou intégrité."
                )
            else:
                st.success(
                    f"Réalisation revue : {review['rubric_score']}/4. La portée reste celle de cette épreuve."
                )
        except ValueError as exc:
            st.error(str(exc))
    st.caption(
        "Les pièces sont conservées avec leurs empreintes dans le dossier exporté. Aucun TP ni fichier joint n'est exécuté par l'application."
    )


def render_program(bank: dict[str, Any]) -> None:
    from agi_web import python_ui as st

    bank = validate_case_payload(bank)
    program = bank.get("assessment_program")
    key = "learning_program_" + sessions.bank_fingerprint(bank)[:16]
    st.subheader(program["title"] if program else "Banque d'exercices sélectionnée")
    if program:
        st.caption(
            f"Version {program['version']} — supports du programme et acquis de l'apprenant sont suivis séparément."
        )
    learner = st.text_input(
        "Pseudonyme de l'apprenant", value="apprenant_01", key=key + "_learner"
    ).strip()
    if not learner.strip():
        st.info("Renseignez un pseudonyme pour conserver les tentatives.")
        return
    session_key = key + "_session_" + sessions.fingerprint(learner)[:16]
    if session_key not in st.session_state:
        st.session_state[session_key] = sessions.new_session(bank, learner)
    session = st.session_state[session_key]
    with st.expander("Reprendre un dossier sauvegardé"):
        uploaded = st.file_uploader(
            "Dossier de progression JSON",
            type=["json"],
            key=session_key + "_resume_upload",
        )
        if st.button(
            "Reprendre ce dossier",
            key=session_key + "_resume",
            disabled=uploaded is None,
        ):
            try:
                restored = sessions.restore_session(uploaded.getvalue(), bank)
                if restored["learner_ref"] != learner:
                    raise ValueError(
                        "Utilisez le pseudonyme du dossier avant de le reprendre."
                    )
                st.session_state[session_key] = restored
                st.rerun()
            except (ValueError, TypeError, KeyError) as exc:
                st.error(f"Reprise refusée : {exc}")
    workspace_key = session_key + "_workspace_" + session["session_id"]
    catalog, learning, practical, progress, coverage = st.tabs(
        [
            "Catalogue",
            "Apprentissage",
            "Épreuves pratiques",
            "Progression et revue",
            "Couverture",
        ]
    )
    with catalog:
        st.dataframe(
            [
                {
                    "exercice": c["case_id"],
                    "titre": c["title"],
                    "type": "academic_questions"
                    if "academic_assessment" in c
                    else c.get("question_assessment", {}).get("kind", "diagnostic"),
                    "transfert": "transfer_variant" in c,
                }
                for c in bank["cases"]
            ],
            hide_index=True,
        )
    with learning:
        _render_learning(bank, session, workspace_key)
    with practical:
        _render_practical(bank, session, workspace_key)
    with progress:
        _render_reviews(bank, session, workspace_key)
        st.caption(
            f"{len(session['attempts'])} tentative(s), {len(session['reviews'])} revue(s) de réponse, {len(session['practical_reviews'])} revue(s) pratique(s). Lire ou terminer une activité ne valide pas automatiquement une compétence."
        )
    with coverage:
        render_education_coverage(bank["cases"], workspace_key)
        if program:
            report = build_program_coverage_report(program, bank["cases"])
            st.metric("Compétences déclarées", report["competency_count"])
            st.metric(
                "Supports complets parmi les compétences déclarées",
                report["ready_competency_count"],
            )
            st.dataframe(
                [
                    {
                        "compétence": c["title"],
                        "questions": len(c["diagnostic_case_ids"]),
                        "pratique": "practical_assessment" in c,
                        "supports manquants": ", ".join(c["missing_material"]),
                    }
                    for c in report["competencies"]
                ],
                hide_index=True,
            )
            st.info(
                "Ces compteurs portent sur les éléments déclarés. L'exhaustivité du livre est contrôlée par son générateur de programme ; aucune maîtrise n'est déduite de ces compteurs."
            )
            with st.expander("Vérifier les sources du programme"):
                uploads = {
                    s["source_id"]: st.file_uploader(
                        s["title"], key=workspace_key + "_source_" + s["source_id"]
                    )
                    for s in program["sources"]
                }
                if st.button(
                    "Comparer les empreintes des sources",
                    key=workspace_key + "_verify_sources",
                ):
                    try:
                        verified = sessions.verify_sources(
                            bank,
                            {
                                i: u.getvalue()
                                for i, u in uploads.items()
                                if u is not None
                            },
                        )
                        sessions.export_session(
                            {**session, "sources_verified": verified}
                        )
                        session["sources_verified"] = verified
                        st.success(
                            "Les sources fournies correspondent aux empreintes de cette version."
                        )
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            st.info("Cette banque ne déclare pas de référentiel de compétences.")
    try:
        st.download_button(
            "Sauvegarder progression, revues et preuves",
            sessions.export_session(session),
            file_name="learning_assessment_progression_fr.json",
            mime="application/json",
            key=workspace_key + "_download",
        )
        if session["attempts"]:
            st.download_button(
                "Exporter les tentatives pour les workers",
                sessions.canonical_bytes(sessions.worker_submission(session, bank)),
                file_name="learning_assessment_tentatives_fr.json",
                mime="application/json",
                key=workspace_key + "_worker_export",
            )
    except ValueError as exc:
        st.error(str(exc))
