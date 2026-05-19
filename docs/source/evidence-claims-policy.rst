Evidence Claims Policy
======================

AGILAB evidence is an engineering and reproducibility contract. It helps a
reviewer understand what ran, which artifacts were produced, which package and
release were used, and which checks were available at the time. It is not a
legal opinion, a compliance certification, or a substitute for a production
governance platform.

This page defines the public-claim boundary for evidence wording in README
files, docs, release notes, demos, and badges.

Allowed Claims
--------------

Use these phrases only when the linked implementation or artifact exists.

.. list-table::
   :header-rows: 1

   * - Claim
     - Required support
   * - AGILAB records reproducibility evidence.
     - A run manifest, stage metadata, or artifact manifest is written.
   * - AGILAB release proof ties together package, CI, docs, and demo evidence.
     - The public :doc:`release-proof` page references the current release.
   * - AGILAB can export a workflow back to a runnable ``agi-core`` notebook.
     - The workflow has a notebook export manifest or exported notebook that
       declares the stable, production-grade ``agi-core`` runtime dependency.
   * - AGILAB can hand evidence to MLflow when the integration is enabled.
     - The MLflow route is explicitly enabled and the run records the handoff.
   * - AGILAB UI robot evidence captures public UI behavior.
     - The robot run stores screenshots, traces, HAR, video, or aggregate JSON.
   * - AGILAB verifier checks are deterministic engineering checks.
     - The verifier only recomputes local evidence, hashes, references, and
       schema contracts; it does not rerun the workflow.

Forbidden Claims And Replacements
---------------------------------

Do not use the left-hand phrasing as a positive public claim. Use the right-hand
replacement instead.

.. list-table::
   :header-rows: 1

   * - Avoid
     - Use instead
   * - EU AI Act compliant
     - designed toward auditability and reproducible engineering evidence
   * - EU AI Act ready
     - evidence-assisted review for teams mapping their own obligations
   * - tamper-proof
     - tamper-evident only when a shipped verifier recomputes hashes
   * - certified
     - supported by local tests, release proof, or published artifacts
   * - regulator-ready
     - reviewable by operators and auditors as engineering evidence
   * - court-admissible evidence
     - structured evidence bundle for independent review
   * - production-grade governance
     - controlled evaluation and shared-use hardening boundary
   * - full audit trail
     - bounded evidence trail for the documented AGILAB workflow
   * - cryptographically anchored
     - package provenance, hashes, or attestations only for the exact shipped path
   * - SLSA compliant
     - supply-chain evidence using Trusted Publishing, hashes, SBOM, audit, and
       provenance where the release proof shows those artifacts

Verifier Claim Boundary
-----------------------

The verifier contract is deliberately read-only:

* it may load manifests and evidence bundles
* it may recompute content hashes and reference closure
* it may validate schema versions and expected files
* it may compare release metadata against local evidence
* it must not rerun user code, notebook cells, cluster jobs, or UI workflows
* it must not claim legal compliance, certification, production readiness, or
  external auditor approval

Stable Verifier Codes
---------------------

AGILAB verifier-style tools should prefer stable, machine-readable codes. The
initial public contract is:

.. list-table::
   :header-rows: 1

   * - Code
     - Meaning
   * - ``AGI_VERIFY_OK``
     - Verification completed without a detected evidence failure.
   * - ``AGI_VERIFY_MANIFEST_MISSING``
     - A required manifest is absent.
   * - ``AGI_VERIFY_SCHEMA_ERROR``
     - A manifest or evidence file has an unsupported shape.
   * - ``AGI_VERIFY_ARTIFACT_HASH_FAILED``
     - An artifact hash does not match the recorded value.
   * - ``AGI_VERIFY_REFERENCE_DANGLING``
     - A manifest reference points to a missing file or event.
   * - ``AGI_VERIFY_NOTEBOOK_EXPORT_FAILED``
     - A notebook export manifest or exported notebook is incomplete.
   * - ``AGI_VERIFY_MLFLOW_REF_DANGLING``
     - An MLflow handoff reference is present but cannot be resolved locally.
   * - ``AGI_VERIFY_RELEASE_PROOF_MISMATCH``
     - Release evidence disagrees with package, tag, docs, or CI metadata.
   * - ``AGI_VERIFY_UNSUPPORTED_CLAIM``
     - A public claim is broader than the evidence can support.

These codes are engineering outcomes. They do not certify legal compliance,
security posture, production suitability, or audit admissibility.

Maintenance Rule
----------------

When a new public evidence claim is added, update this page in the same change
as the implementation or artifact that supports the claim. If the claim is only
roadmap, say so explicitly and keep it out of badges and release-proof language.
