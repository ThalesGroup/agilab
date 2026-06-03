Regulatory Readiness
====================

AGILAB can prepare engineering evidence for a regulatory or governance review,
but it does not certify legal compliance. The local readiness report is a
screening artifact that helps reviewers see what evidence exists, what is
missing, and which official sources should be checked before a legal or
compliance conclusion is made.

Run it against a completed AGILAB run manifest and the review files you want to
attach:

.. code-block:: bash

   python3 tools/regulatory_readiness_report.py \
     --profile eu-ai-act-screening \
     --run-manifest <run_manifest.json> \
     --system-description "AI system that screens job applicants by analysing CVs." \
     --evidence-dir <review-bundle> \
     --check \
     --json

The output uses schema ``agilab.regulatory_readiness.v1``. It records:

- official source references used for the screening profile;
- source freshness status, so stale regulatory references are visible;
- a keyword triage bucket for review planning, not legal classification;
- hashed evidence files and their matched readiness controls;
- gaps for missing run evidence, artifact lineage, data governance notes,
  technical documentation, human oversight, transparency notes, and security
  posture evidence.

The report explicitly does not prove EU AI Act compliance, legal adequacy,
conformity assessment, production approval, or enterprise governance readiness.
Treat it as a handoff checklist for qualified legal, compliance, safety, and
security reviewers.

Why this belongs in AGILAB
--------------------------

AGILAB's value is evidence-first experimentation. Regulatory and governance
reviews often start from the same raw material: what was run, with which data,
which artifacts were produced, what humans reviewed, what security checks ran,
and what users or deployers were told. The readiness report keeps that bridge
inside AGILAB without turning the workbench into a legal compliance platform.

Current profile
---------------

The first profile is ``eu-ai-act-screening``. It maps AGILAB evidence to review
questions inspired by the EU AI Act risk-based approach:

.. list-table::
   :header-rows: 1

   * - Control
     - Looks for
     - Boundary
   * - System purpose and deployment context
     - ``--system-description`` or purpose/context in run evidence.
     - Scope input only; it does not decide legal applicability.
   * - Risk-screening input
     - A concise human-readable description.
     - Keyword triage only; it is not a legal risk classification.
   * - Run traceability
     - Parseable ``run_manifest.json``.
     - Proves AGILAB run evidence exists, not operational audit completeness.
   * - Artifact and lineage inventory
     - Hashable outputs, lineage exports, proof capsules, reports, or
       reducer summaries.
     - Proves presence and hashes, not correctness.
   * - Data governance evidence
     - Dataset, data lineage, validation, test, or data-artifact-lane notes.
     - Does not prove data quality, privacy compliance, or bias adequacy.
   * - Technical documentation evidence
     - Reports, README-style context, architecture notes, or model cards.
     - Does not prove Annex IV completeness.
   * - Human oversight evidence
     - Review, approval, operator decision, or promotion dossier notes.
     - Does not prove oversight effectiveness.
   * - Transparency and instructions evidence
     - User notices, deployer instructions, disclosure, or transparency notes.
     - Does not prove regulatory sufficiency.
   * - Security posture evidence
     - ``agilab security-check``, SBOM, ``pip-audit``, dependency policy, or
       cybersecurity notes.
     - Does not prove production cybersecurity compliance.
   * - Regulatory source freshness
     - Recent review date for official sources.
     - Stale sources block readiness claims until rechecked.

Official sources
----------------

The profile references official public sources and marks the built-in review
date. Recheck them before using the report for an actual compliance review:

- European Commission AI Act overview:
  https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai
- AI Act Service Desk implementation timeline:
  https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act
- Regulation (EU) 2024/1689 on EUR-Lex:
  https://eur-lex.europa.eu/eli/reg/2024/1689/oj

When a reviewer has rechecked those sources, pass the date explicitly:

.. code-block:: bash

   python3 tools/regulatory_readiness_report.py \
     --run-manifest <run_manifest.json> \
     --evidence-dir <review-bundle> \
     --system-description "<system description>" \
     --source-review-date YYYY-MM-DD \
     --json

The date is evidence metadata. It does not replace legal review.
