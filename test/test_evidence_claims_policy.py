from __future__ import annotations

from pathlib import Path


DOCS_SOURCE = Path("docs/source")
CLAIMS_POLICY = DOCS_SOURCE / "evidence-claims-policy.rst"
EVIDENCE_TAXONOMY = DOCS_SOURCE / "evidence-taxonomy.rst"
INDEX = DOCS_SOURCE / "index.rst"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_evidence_claim_pages_are_linked_from_docs_index() -> None:
    index = _read(INDEX)

    assert "Evidence claims policy <evidence-claims-policy>" in index
    assert "Evidence taxonomy <evidence-taxonomy>" in index


def test_evidence_claim_policy_declares_allowed_and_forbidden_boundaries() -> None:
    text = _read(CLAIMS_POLICY)

    for phrase in (
        "AGILAB evidence is an engineering and reproducibility contract",
        "Allowed Claims",
        "Forbidden Claims And Replacements",
        "Verifier Claim Boundary",
        "Stable Verifier Codes",
        "must not claim legal compliance",
        "These codes are engineering outcomes",
    ):
        assert phrase in text

    replacements = {
        "EU AI Act compliant": "designed toward auditability",
        "EU AI Act ready": "evidence-assisted review",
        "tamper-proof": "tamper-evident only when a shipped verifier recomputes hashes",
        "certified": "supported by local tests, release proof, or published artifacts",
        "regulator-ready": "reviewable by operators and auditors as engineering evidence",
        "court-admissible evidence": "structured evidence bundle for independent review",
        "production-grade governance": "controlled evaluation and shared-use hardening boundary",
        "full audit trail": "bounded evidence trail for the documented AGILAB workflow",
        "cryptographically anchored": "package provenance, hashes, or attestations",
        "SLSA compliant": "supply-chain evidence using Trusted Publishing",
    }
    for unsupported, replacement in replacements.items():
        assert unsupported in text
        assert replacement in text


def test_evidence_taxonomy_declares_events_and_read_only_verifier_scope() -> None:
    text = _read(EVIDENCE_TAXONOMY)

    for event_type in (
        "run_manifest_event",
        "stage_transition_event",
        "artifact_event",
        "notebook_export_event",
        "mlflow_handoff_event",
        "ui_robot_event",
        "agent_run_event",
        "policy_check_event",
        "release_proof_event",
    ):
        assert event_type in text

    for field in (
        "schema_version",
        "event_type",
        "run_id",
        "seq",
        "artifact_sha256",
        "prev_event_hash",
        "event_hash",
    ):
        assert field in text

    assert "without rerunning work" in text
    assert "must not validate facts outside the evidence bundle" in text
    assert "designed toward tamper-evident chains" in text


def test_public_entry_points_do_not_make_unsupported_evidence_claims() -> None:
    public_text = "\n".join(
        _read(path)
        for path in (
            Path("README.md"),
            Path("README.pypi.md"),
            DOCS_SOURCE / "index.rst",
            DOCS_SOURCE / "release-proof.rst",
            DOCS_SOURCE / "security-adoption.rst",
        )
    )

    unsupported_positive_claims = (
        "EU AI Act compliant",
        "EU AI Act ready",
        "tamper-proof",
        "regulator-ready",
        "court-admissible evidence",
        "production-grade governance",
        "full audit trail",
        "SLSA compliant",
        "certified audit evidence",
    )
    for claim in unsupported_positive_claims:
        assert claim not in public_text


def test_verifier_error_code_contract_is_machine_readable() -> None:
    text = _read(CLAIMS_POLICY)

    expected_codes = (
        "AGI_VERIFY_OK",
        "AGI_VERIFY_MANIFEST_MISSING",
        "AGI_VERIFY_SCHEMA_ERROR",
        "AGI_VERIFY_ARTIFACT_HASH_FAILED",
        "AGI_VERIFY_REFERENCE_DANGLING",
        "AGI_VERIFY_NOTEBOOK_EXPORT_FAILED",
        "AGI_VERIFY_MLFLOW_REF_DANGLING",
        "AGI_VERIFY_RELEASE_PROOF_MISMATCH",
        "AGI_VERIFY_UNSUPPORTED_CLAIM",
    )
    for code in expected_codes:
        assert f"``{code}``" in text

    assert len(expected_codes) == len(set(expected_codes))
