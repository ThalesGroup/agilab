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
run-manifest evidence ingestion, and proof commands with:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --manifest ~/log/execute/flight/run_manifest.json --compact

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

The compact compatibility report checks the required public statuses, the proof
commands behind validated entries, and optional ``run_manifest.json`` evidence.
It scans default local log roots and also accepts explicit external evidence
with ``--manifest`` or ``--manifest-dir``. When a manifest is present, the report
derives that path's effective status from the manifest result; without a
manifest, it falls back to the checked-in matrix status. The compact KPI bundle
consumes that report and includes the ``multi_app_dag_report_contract``,
``global_pipeline_dag_report_contract``,
``global_pipeline_execution_plan_report_contract``,
``global_pipeline_runner_state_report_contract``,
``global_pipeline_dispatch_state_report_contract``,
``global_pipeline_app_dispatch_smoke_report_contract``,
``global_pipeline_operator_state_report_contract``,
``global_pipeline_dependency_view_report_contract``,
``global_pipeline_live_state_updates_report_contract``,
``global_pipeline_operator_actions_report_contract``,
``global_pipeline_operator_ui_report_contract``,
``notebook_pipeline_import_report_contract``,
``notebook_roundtrip_report_contract``, and
``reduce_contract_adoption_guardrail`` checks, which respectively validate the
checked-in cross-app DAG handoff sample, assemble the read-only product-level
graph from app-local ``pipeline_view.dot`` files, define pending/not-executed
runnable units with artifact dependencies and provenance, project runnable and
blocked runner state with retry/partial-rerun metadata and operator messages,
persist a queue-to-relay dispatch-state transition proof, execute
``queue_baseline`` and ``relay_followup`` through the real
``uav_queue_project`` and ``uav_relay_queue_project`` app entries, persist
``queue_metrics`` and ``relay_metrics``, project operator-visible completed
state plus retry/partial-rerun actions from that persisted dispatch state,
project upstream/downstream dependency visualization for
``queue_baseline -> relay_followup`` from that operator state, project ordered
live orchestration-state update payloads from the dependency view, execute
retry and partial-rerun operator requests through real app-entry action replay,
render persisted global-DAG state into operator UI components, validate
notebook-to-pipeline import from a checked-in ``.ipynb``, write a richer
``lab_steps.toml`` preview used by the ``PIPELINE`` upload path without
executing cells, validate ``lab_steps.toml -> supervisor notebook -> import ->
lab_steps preview`` round-trip preservation, and verify that every non-template
built-in app exposes a reducer contract while recording
``mycode_project`` as the explicit template-only exemption.

For the source-checkout first proof, ``tools/newcomer_first_proof.py --json``
also writes ``~/log/execute/flight/run_manifest.json``. That stable manifest is
the shared run record for command, environment, timing, artifact references, and
validation status; the compact KPI bundle checks this as
``run_manifest_contract``, and the release-decision page consumes it as the
first promotion gate. The same page can now import external manifest evidence
with ``--manifest`` / ``--manifest-dir`` style inputs, display source path,
provenance, path id, timing, validation status, evidence status, SHA-256, byte
size, UTC modified time, and optional sidecar signature metadata, and export
that import summary in ``promotion_decision.json``. Release Decision also
exports ``connector_registry_paths`` and ``connector_registry_summary`` so
artifact, log, export, and first-proof paths are portable across page launches
instead of reconstructed from local path glue. Export also updates
``manifest_index.json`` under the artifact root so imported manifests are grouped
by candidate bundle for later release decisions, and the page compares the
current candidate against prior indexed evidence to flag better, stale, missing,
failed, and newly validated manifests, including attachment hash matches. The
same export includes a cross-run evidence bundle comparison across selected
manifest, KPI, required artifact, and reduce-artifact evidence for the baseline
and prior indexed releases.

The in-product first-proof wizard consumes the same support boundary: it routes
newcomers to the single actionable source-checkout ``flight_project`` proof and
keeps notebook and packaged-install routes documented, not recommended, until
that local proof has passed once. It reads the same ``run_manifest.json`` and
turns missing, invalid, incomplete, or failing evidence into a recovery
checklist with the exact first-proof and compatibility-report commands.

What remains roadmap work
-------------------------

This first matrix closes the small, manual version of the compatibility item.
The larger roadmap work is still open:

- automatic harvesting from external CI workflow artifacts
- per-release compatibility status driven by harvested attachments
- broader app/core revision traceability beyond the first-proof manifest
- explicit certification for more than the public newcomer/operator slices
