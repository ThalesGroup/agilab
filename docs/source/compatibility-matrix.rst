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

Maintainers can validate the matrix schema, required public statuses,
run-manifest evidence ingestion, artifact-index evidence ingestion, and proof
commands with:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --manifest ~/log/execute/flight/run_manifest.json --compact
   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --artifact-index artifact_index.json --compact

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
README summary alone. For normal maintenance, use the compact checks first:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/kpi_evidence_bundle.py --compact
   uv --preview-features extra-build-dependencies run python tools/revision_traceability_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/public_certification_profile_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json
   uv --preview-features extra-build-dependencies run python tools/agilab_web_robot.py --target-url https://jpmorard-agilab.hf.space
   uv --preview-features extra-build-dependencies run python tools/production_readiness_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/supply_chain_attestation_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/repository_knowledge_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/run_diff_evidence_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/ci_artifact_harvest_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/github_actions_artifact_index.py --archive artifact.zip --output artifact_index.json
   uv --preview-features extra-build-dependencies run python tools/ci_provider_artifact_index.py --provider gitlab_ci --archive artifact.zip --output artifact_index.json
   uv --preview-features extra-build-dependencies run python tools/multi_app_dag_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_dag_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_execution_plan_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_runner_state_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_dispatch_state_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_app_dispatch_smoke_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_operator_state_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_dependency_view_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_live_state_updates_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_operator_actions_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/global_pipeline_operator_ui_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/notebook_pipeline_import_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/notebook_roundtrip_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/notebook_union_environment_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_facility_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_resolution_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_health_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_health_actions_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_runtime_adapters_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_live_endpoint_smoke_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_ui_preview_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_live_ui_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_view_surface_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_app_catalogs_report.py --compact

For source-checkout first proof evidence, ``tools/newcomer_first_proof.py
--json`` writes ``~/log/execute/flight/run_manifest.json``. The compatibility
report can ingest that manifest directly:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py \
     --manifest ~/log/execute/flight/run_manifest.json \
     --compact

The broader evidence tooling covers release metadata, supply-chain metadata,
connector contracts, global pipeline state, CI artifact harvests, and promotion
decision exports. Keep those details in tool help, tests, and maintainer
runbooks; this public page should stay a readable support-status map.

The in-product first-proof wizard uses the same boundary: it routes newcomers
to the source-checkout ``flight_project`` proof first, reads
``run_manifest.json``, and turns missing or failing evidence into a recovery
checklist.

What remains roadmap work
-------------------------

This first matrix closes the small, manual version of the compatibility item,
and the CI artifact harvest report plus GitHub Actions and generic provider
artifact-index flows define the no-network attachment contract, downloaded
GitLab CI/generic archive coverage, and the first live provider download
adapter.
The larger roadmap work is still open:

- credentialed execution of non-GitHub live provider API harvests
- formal supply-chain attestation beyond static local-file evidence
- formal certification beyond the bounded public-evidence profile
