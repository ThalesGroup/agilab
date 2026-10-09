"""Portable attempts and declared human reviews, bound to one programme version.

Checksums detect modification and replay inconsistencies; they do not authenticate
the learner or reviewer. Uploaded evidence is retained, never executed.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4


SESSION_SCHEMA = "agilab.learning_assessment.program_session.v1"
MAX_SESSION_BYTES = 24 * 1024 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 12 * 1024 * 1024
PRACTICAL_WEIGHTS = {
    "explanation": 15,
    "reproduction": 25,
    "diagnosis": 20,
    "synthesis": 25,
    "defence": 15,
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} doit être renseigné.")
    return value.strip()


def _bank(bank: Mapping[str, Any]) -> dict[str, Any]:
    from .diagnostic import validate_case_payload

    return validate_case_payload(bank)


def bank_fingerprint(bank: Mapping[str, Any]) -> str:
    return fingerprint(_bank(bank))


def new_session(bank: Mapping[str, Any], learner_ref: str) -> dict[str, Any]:
    normalized = _bank(bank)
    return {
        "schema": SESSION_SCHEMA,
        "session_id": uuid4().hex,
        "learner_ref": _text(learner_ref, "Pseudonyme"),
        "bank_sha256": fingerprint(normalized),
        "created_at": _now(),
        "attempts": [],
        "reviews": [],
        "practical_reviews": [],
        "sources_verified": [],
    }


def _check_binding(
    session: Mapping[str, Any], bank: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = _bank(bank)
    if session.get("schema") != SESSION_SCHEMA or session.get(
        "bank_sha256"
    ) != fingerprint(normalized):
        raise ValueError(
            "Le programme a changé : conservez l'ancien dossier et démarrez une nouvelle session."
        )
    return normalized


def _append_record(
    session: dict[str, Any], collection: str, record: dict[str, Any]
) -> None:
    """Reject a write before it can make the retained history unexportable."""
    candidate = {**session, collection: [*session[collection], record]}
    export_session(candidate)
    session[collection].append(record)


def case_context(bank: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    program = bank.get("assessment_program", {})
    competencies = [
        c
        for c in program.get("competencies", [])
        if case_id in c["diagnostic_case_ids"]
    ]
    return {
        "program_id": program.get("program_id", ""),
        "program_version": program.get("version", ""),
        "bank_sha256": bank_fingerprint(bank),
        "competency_ids": [c["competency_id"] for c in competencies],
        "source_refs": [deepcopy(r) for c in competencies for r in c["source_refs"]],
        "sources": deepcopy(program.get("sources", [])),
    }


def submit_attempt(
    session: dict[str, Any],
    bank: Mapping[str, Any],
    case_id: str,
    answer: Mapping[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    from .diagnostic import diagnose_case, validate_case_payload

    normalized = _check_binding(session, bank)
    if mode not in {"practice", "positioning", "transfer"}:
        raise ValueError(
            "Les exemples commentés ne constituent pas des tentatives évaluées."
        )
    case = next((c for c in normalized["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise ValueError("Exercice inconnu.")
    if mode == "transfer" and "transfer_variant" not in case:
        raise ValueError(
            "Le transfert demande une variante distincte, modifiant au moins deux dimensions."
        )
    submitted_case = {**deepcopy(case), "student_answer": deepcopy(dict(answer))}
    validated = validate_case_payload(
        {"schema": normalized["schema"], "cases": [submitted_case]}
    )["cases"][0]
    evaluation = diagnose_case(validated)["self_evaluation"]
    if evaluation["status"] == "not_submitted":
        raise ValueError("La réponse est vide.")
    previous = [a for a in session["attempts"] if a["case_id"] == case_id]
    attempt = {
        "attempt_id": uuid4().hex,
        "case_id": case_id,
        "attempt_number": len(previous) + 1,
        "previous_attempt_id": previous[-1]["attempt_id"] if previous else None,
        "submitted_at": _now(),
        "mode": mode,
        "answer": deepcopy(dict(answer)),
        "evaluation": evaluation,
        "context": case_context(normalized, case_id),
    }
    _append_record(session, "attempts", attempt)
    return deepcopy(attempt)


def _review_scores(scores: Mapping[str, Any], criteria: list[str]) -> dict[str, int]:
    if not isinstance(scores, Mapping) or set(scores) != set(criteria):
        raise ValueError("Chaque critère de la grille doit être évalué.")
    if any(type(v) is not int or not 0 <= v <= 4 for v in scores.values()):
        raise ValueError("Les critères sont des entiers de 0 à 4.")
    return dict(scores)


def review_attempt(
    session: dict[str, Any],
    bank: Mapping[str, Any],
    attempt_id: str,
    *,
    reviewer: str,
    rationale: str,
    scores: Mapping[str, int],
) -> dict[str, Any]:
    normalized = _check_binding(session, bank)
    attempt = next(
        (a for a in session["attempts"] if a["attempt_id"] == attempt_id), None
    )
    if attempt is None:
        raise ValueError("Tentative inconnue.")
    case = next(c for c in normalized["cases"] if c["case_id"] == attempt["case_id"])
    criteria = case.get("question_assessment", {}).get(
        "criteria",
        [
            "Exactitude du raisonnement",
            "Justification par les preuves",
            "Limites et contre-exemples",
        ],
    )
    checked = _review_scores(scores, criteria)
    review = {
        "review_id": uuid4().hex,
        "attempt_id": attempt_id,
        "reviewed_at": _now(),
        "reviewer": _text(reviewer, "Évaluateur"),
        "rationale": _text(rationale, "Justification"),
        "criteria": checked,
        "rubric_score": round(sum(checked.values()) / len(checked), 2),
        "status": "reviewed",
        "attestation": "declared_human_review",
    }
    _append_record(session, "reviews", review)
    return deepcopy(review)


def pack_artifacts(files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    result = []
    total = 0
    for name, content in sorted(files.items()):
        if (
            not isinstance(name, str)
            or not name
            or PurePosixPath(name).name != name
            or "\\" in name
            or name in {".", ".."}
        ):
            raise ValueError("Chaque pièce doit avoir un nom de fichier simple.")
        if (
            not isinstance(content, bytes)
            or not content
            or len(content) > MAX_ARTIFACT_BYTES
        ):
            raise ValueError("Chaque pièce doit contenir entre 1 octet et 4 Mio.")
        total += len(content)
        result.append(
            {
                "name": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    if not result or total > MAX_EVIDENCE_BYTES:
        raise ValueError(
            "Joignez des preuves, dans la limite de 12 Mio par dossier pratique."
        )
    return result


def review_practical(
    session: dict[str, Any],
    bank: Mapping[str, Any],
    competency_id: str,
    *,
    reviewer: str,
    rationale: str,
    scores: Mapping[str, int],
    artifacts: Mapping[str, bytes],
    safety_authorized: bool,
    integrity_verified: bool,
) -> dict[str, Any]:
    normalized = _check_binding(session, bank)
    competency = next(
        (
            c
            for c in normalized.get("assessment_program", {}).get("competencies", [])
            if c["competency_id"] == competency_id
        ),
        None,
    )
    if competency is None or "practical_assessment" not in competency:
        raise ValueError("Épreuve pratique inconnue.")
    criteria = [c["criterion_id"] for c in competency["practical_assessment"]["rubric"]]
    checked = _review_scores(scores, criteria)
    if type(safety_authorized) is not bool or type(integrity_verified) is not bool:
        raise ValueError("Les portes sécurité et intégrité doivent être explicites.")
    weights = (
        PRACTICAL_WEIGHTS
        if set(criteria) == set(PRACTICAL_WEIGHTS)
        else {c: 1 for c in criteria}
    )
    score = round(
        sum(checked[c] * weights[c] for c in criteria) / sum(weights.values()), 2
    )
    review = {
        "review_id": uuid4().hex,
        "competency_id": competency_id,
        "reviewed_at": _now(),
        "reviewer": _text(reviewer, "Évaluateur"),
        "rationale": _text(rationale, "Justification"),
        "criteria": checked,
        "rubric_score": score,
        "artifacts": pack_artifacts(artifacts),
        "safety_authorized": safety_authorized,
        "integrity_verified": integrity_verified,
        "status": "reviewed" if safety_authorized and integrity_verified else "blocked",
        "attestation": "declared_human_review",
    }
    _append_record(session, "practical_reviews", review)
    return deepcopy(review)


def verify_sources(
    bank: Mapping[str, Any], uploads: Mapping[str, bytes]
) -> list[dict[str, str]]:
    """Check explicitly supplied source bytes; never follow source paths or URLs."""
    result = []
    for source in _bank(bank).get("assessment_program", {}).get("sources", []):
        content = uploads.get(source["source_id"])
        if content is None or hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise ValueError(f"Source absente ou modifiée : {source['title']}")
        result.append({"source_id": source["source_id"], "sha256": source["sha256"]})
    return result


def export_session(session: Mapping[str, Any]) -> bytes:
    body = deepcopy(dict(session))
    result = canonical_bytes({"payload": body, "sha256": fingerprint(body)})
    if len(result) > MAX_SESSION_BYTES:
        raise ValueError(
            "Le dossier dépasse 24 Mio ; conservez des pièces plus petites."
        )
    return result


def restore_session(raw: bytes, bank: Mapping[str, Any]) -> dict[str, Any]:
    from .diagnostic import diagnose_case

    if len(raw) > MAX_SESSION_BYTES:
        raise ValueError("Dossier trop volumineux.")
    envelope = json.loads(raw)
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
        raise ValueError("Dossier de progression invalide.")
    session = envelope["payload"]
    if not isinstance(session, dict) or fingerprint(session) != envelope["sha256"]:
        raise ValueError("L'empreinte du dossier ne correspond pas au contenu.")
    normalized = _check_binding(session, bank)
    _text(session.get("learner_ref"), "Pseudonyme")
    _text(session.get("session_id"), "Session")
    expected_fields = {
        "schema",
        "session_id",
        "learner_ref",
        "bank_sha256",
        "created_at",
        "attempts",
        "reviews",
        "practical_reviews",
        "sources_verified",
    }
    collections = ("attempts", "reviews", "practical_reviews", "sources_verified")
    if set(session) != expected_fields or any(
        not isinstance(session[k], list) for k in collections
    ):
        raise ValueError("Structure du dossier invalide.")
    if any(
        not isinstance(record, dict)
        for collection in collections
        for record in session[collection]
    ):
        raise ValueError(
            "Chaque tentative, revue ou vérification de source doit être un objet."
        )
    cases = {c["case_id"]: c for c in normalized["cases"]}
    seen: set[str] = set()
    previous: dict[str, list[str]] = {}
    for attempt in session["attempts"]:
        identity = _text(attempt.get("attempt_id"), "Tentative")
        case_id = attempt.get("case_id")
        if identity in seen or case_id not in cases:
            raise ValueError("Tentative dupliquée ou exercice inconnu.")
        seen.add(identity)
        before = previous.setdefault(case_id, [])
        if attempt.get("attempt_number") != len(before) + 1 or attempt.get(
            "previous_attempt_id"
        ) != (before[-1] if before else None):
            raise ValueError("Filiation des tentatives incohérente.")
        before.append(identity)
        if attempt.get("mode") not in {"practice", "positioning", "transfer"} or (
            attempt["mode"] == "transfer" and "transfer_variant" not in cases[case_id]
        ):
            raise ValueError("Mode de tentative incohérent.")
        replay = diagnose_case({**cases[case_id], "student_answer": attempt["answer"]})[
            "self_evaluation"
        ]
        if replay["status"] == "not_submitted":
            raise ValueError("Une tentative ne peut pas contenir une réponse vide.")
        if attempt.get("evaluation") != replay or attempt.get(
            "context"
        ) != case_context(normalized, case_id):
            raise ValueError(
                "Le rejeu de la tentative ou sa provenance ne correspond pas."
            )
    scratch = {**deepcopy(session), "reviews": [], "practical_reviews": []}
    review_ids: set[str] = set()
    for review in session["reviews"]:
        replay = review_attempt(
            scratch,
            normalized,
            review["attempt_id"],
            reviewer=review["reviewer"],
            rationale=review["rationale"],
            scores=review["criteria"],
        )
        _verify_review(review, replay, review_ids)
    for review in session["practical_reviews"]:
        files = {}
        for artifact in review["artifacts"]:
            if (
                artifact["name"] in files
                or len(artifact["content_base64"]) > 6 * 1024 * 1024
            ):
                raise ValueError("Pièce dupliquée ou trop volumineuse.")
            content = base64.b64decode(artifact["content_base64"], validate=True)
            if (
                len(content) != artifact["size"]
                or hashlib.sha256(content).hexdigest() != artifact["sha256"]
            ):
                raise ValueError("Une pièce pratique a été modifiée.")
            files[artifact["name"]] = content
        replay = review_practical(
            scratch,
            normalized,
            review["competency_id"],
            reviewer=review["reviewer"],
            rationale=review["rationale"],
            scores=review["criteria"],
            artifacts=files,
            safety_authorized=review["safety_authorized"],
            integrity_verified=review["integrity_verified"],
        )
        _verify_review(review, replay, review_ids)
    expected_sources = [
        {"source_id": s["source_id"], "sha256": s["sha256"]}
        for s in normalized.get("assessment_program", {}).get("sources", [])
    ]
    if session["sources_verified"] not in ([], expected_sources):
        raise ValueError("Vérification des sources incohérente.")
    return deepcopy(session)


def _verify_review(
    review: Mapping[str, Any], replay: Mapping[str, Any], seen: set[str]
) -> None:
    identity = _text(review.get("review_id"), "Revue")
    if identity in seen or set(review) != set(replay):
        raise ValueError("Revue dupliquée ou invalide.")
    seen.add(identity)
    if any(
        review[k] != replay[k] for k in replay if k not in {"review_id", "reviewed_at"}
    ):
        raise ValueError("Une décision de revue est incohérente.")


def worker_submission(
    session: Mapping[str, Any], bank: Mapping[str, Any]
) -> dict[str, Any]:
    """Export the same bank and answers used in the UI through existing workers."""
    normalized = _check_binding(session, bank)
    if not session["attempts"]:
        raise ValueError("Aucune tentative à exporter.")
    result = deepcopy(normalized)
    by_id = {c["case_id"]: c for c in normalized["cases"]}
    result["cases"] = []
    case_ids: dict[str, list[str]] = {}
    for attempt in session["attempts"]:
        case = deepcopy(by_id[attempt["case_id"]])
        identity = f"attempt_{attempt['attempt_id']}"
        case.update(
            case_id=identity,
            exercise_id=attempt["case_id"],
            student_ref=session["learner_ref"],
            session_id=session["session_id"],
            submitted_at=attempt["submitted_at"],
            student_answer=deepcopy(attempt["answer"]),
        )
        case["submission_context"] = {
            "original_bank_sha256": session["bank_sha256"],
            "attempt_id": attempt["attempt_id"],
            "attempt_number": attempt["attempt_number"],
            "mode": attempt["mode"],
            "previous_attempt_id": attempt["previous_attempt_id"],
        }
        case.pop("transfer_variant", None)
        result["cases"].append(case)
        case_ids.setdefault(attempt["case_id"], []).append(identity)
    for competency in result.get("assessment_program", {}).get("competencies", []):
        competency["diagnostic_case_ids"] = [
            identity
            for ref in competency["diagnostic_case_ids"]
            for identity in case_ids.get(ref, [])
        ]
    return _bank(result)
