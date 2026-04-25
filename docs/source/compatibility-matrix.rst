Compatibility Matrix
====================

This page is the first shipped version of an AGILAB compatibility and
certification matrix. The matrix is promoted into a workflow-backed
compatibility report so public status claims are checked by the same evidence
tooling as the KPI bundle.

It is intentionally narrow. The goal is to make the currently supported public
paths explicit now, instead of waiting for a larger automation project.

For this page, ``validated`` means the path has an explicit local proof,
regression coverage, or workflow-parity validation in the public AGILAB
repository. It does **not** mean a formal release certification program is in
place yet.

The machine-readable source for this page is:

- :download:`compatibility_matrix.toml <data/compatibility_matrix.toml>`

Maintainers can validate the matrix schema, required public statuses, and proof
commands with:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --compact

Current public matrix
---------------------

.. list-table::
   :header-rows: 1
   :widths: 22 12 18 24 24

   * - Slice
     - Status
     - Primary proof
     - Scope
     - Limits
   * - Source checkout first proof
     - validated
     - ``uv run python tools/newcomer_first_proof.py``
     - Public built-in ``flight_project`` path, local execution, and the
       recommended newcomer workflow
     - No SSH, no private apps, no packaged install
   * - Web UI local first proof
     - validated
     - ``uv run streamlit run src/agilab/About_agilab.py``
     - ``PROJECT -> ORCHESTRATE -> ANALYSIS`` on the local built-in app path,
       with fresh output under ``~/log/execute/flight/``
     - Not a remote cluster proof
   * - AGILAB Hugging Face demo
     - validated
     - ``uv run python tools/hf_space_smoke.py --json``
     - Self-serve AGILAB web UI demo hosted on Hugging Face Spaces, including
       route smoke and a public app-tree guardrail
     - Hosted demo environment; availability depends on Hugging Face Spaces uptime; not a remote cluster proof
   * - Service-mode operator surface
     - validated
     - ORCHESTRATE service controls and health gate
     - Start / status / health / stop operator flow and SLA thresholds
     - Does not certify every remote topology or deployment policy
   * - Notebook quickstart
     - documented
     - ``examples/notebook_quickstart/agi_core_first_run.ipynb``
     - Public notebook-first route for users who intentionally start from
       ``agi-core``
     - Not the recommended first proof path
   * - Published package route
     - documented
     - ``uv pip install agilab`` then ``uv run agilab``
     - Fast packaged install for public evaluation outside the source checkout
     - Less representative of the full source workflow than the built-in first proof

How to use this matrix
----------------------

Use it to answer three concrete questions:

1. Which public path should a newcomer trust first?
2. Which routes are currently validated versus only documented?
3. Which paths still need broader certification or automation work?

Use :doc:`newcomer-guide` and :doc:`quick-start` for the actual onboarding
flow. This page is only the support-status map.

Maintainer evidence commands
----------------------------

The public evaluation score is backed by reproducible checks rather than by the
README table alone. Maintainers can collect the evidence bundle and supporting
smokes with:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/kpi_evidence_bundle.py --compact
   uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json
   uv --preview-features extra-build-dependencies run python tools/agilab_web_robot.py --url https://jpmorard-agilab.hf.space --analysis-view view_maps --json
   uv --preview-features extra-build-dependencies run python tools/production_readiness_report.py --compact

The compact compatibility report checks the required public statuses and the
proof commands behind validated entries. The compact KPI bundle consumes that
report and includes the ``reduce_contract_adoption_guardrail`` check, which
verifies that every non-template built-in app exposes a reducer contract and
records ``mycode_project`` as the explicit template-only exemption.

For the source-checkout first proof, ``tools/newcomer_first_proof.py --json``
also writes ``~/log/execute/flight/run_manifest.json``. That stable manifest is
the shared run record for command, environment, timing, artifact references, and
validation status; the compact KPI bundle checks this as
``run_manifest_contract``.

The in-product first-proof wizard consumes the same support boundary: it routes
newcomers to the single actionable source-checkout ``flight_project`` proof and
keeps notebook and packaged-install routes documented, not recommended, until
that local proof has passed once.

What remains roadmap work
-------------------------

This first matrix closes the small, manual version of the compatibility item.
The larger roadmap work is still open:

- automatic ingestion from external CI workflow artifacts
- per-release compatibility status
- broader app/core revision traceability beyond the first-proof manifest
- explicit certification for more than the public newcomer/operator slices
