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
   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --manifest ~/log/execute/flight_telemetry/run_manifest.json --compact
   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py --artifact-index artifact_index.json --compact
   uv --preview-features extra-build-dependencies run python tools/public_proof_scenarios.py --compact
   uv --preview-features extra-build-dependencies run python tools/first_launch_robot.py --json
   uv --preview-features extra-build-dependencies run python tools/security_hygiene_report.py --compact

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
     - Public built-in ``flight_telemetry_project`` path, local execution, and the
       recommended newcomer workflow
     - No SSH, no private apps, no packaged install
   * - Web UI local first proof
     - validated
     - ``uv run streamlit run src/agilab/main_page.py``
     - ``PROJECT -> ORCHESTRATE -> ANALYSIS`` on the local built-in app path,
       with fresh output under ``~/log/execute/flight_telemetry/``
     - Not a remote cluster proof
   * - AGILAB Hugging Face demo
     - validated
     - ``uv run python tools/hf_space_smoke.py --json``
     - Self-serve AGILAB web UI demo hosted on Hugging Face Spaces, including
       flight and weather route smoke plus a public app-tree guardrail
     - Hosted demo environment; availability depends on Hugging Face Spaces uptime; not a remote cluster proof
   * - Service-mode operator surface
     - validated
     - ORCHESTRATE service controls and health gate
     - Start / status / health / stop operator flow and SLA thresholds
     - Does not certify every remote topology or deployment policy
   * - Notebook quickstart
     - documented
     - ``src/agilab/examples/notebook_quickstart/agi_core_first_run.ipynb``
     - Public notebook-first route for users who intentionally start from
       ``agi-core``
     - Not the recommended first proof path
   * - Published package route
     - validated
     - ``python -m pip install "agilab[examples]"`` then
       ``python -m agilab.lab_run first-proof --json --max-seconds 60``
     - Clean public package install with example apps outside the source
       checkout, followed by the packaged CLI/core first-proof smoke
     - Validates the released package and public example payload, not unmerged
       branch contents; less representative than the source-checkout first proof

Platform coverage snapshot
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 18 34 28

   * - Platform / route
     - Public status
     - Evidence
     - Limit
   * - macOS local
     - validated for source/web UI paths
     - source-checkout first proof, web UI local first proof, and local
       workflow-parity profiles
     - not a cloud or SSH-cluster certification
   * - Linux package
     - validated
     - GitHub Actions clean install: ``python -m pip install "agilab[examples]"`` then
       ``python -m agilab.lab_run first-proof --json --max-seconds 60``
     - validates the latest released package plus public examples, not the
       local web UI extra
   * - macOS package
     - validated
     - GitHub Actions clean install: ``python -m pip install "agilab[examples]"`` then
       ``python -m agilab.lab_run first-proof --json --max-seconds 60``
     - validates the latest released package plus public examples on the macOS runner, not
       every local Homebrew/PyCharm setup or UI extra combination
   * - Windows / WSL2
     - validated for the clean package smoke; documented for WSL2/source flows
     - GitHub Actions clean install on ``windows-latest`` plus installer and
       quick-start instructions for WSL2 and Windows-oriented paths
     - validates the released package smoke on the GitHub runner, not every
       local Windows shell, GPU, or SSH setup
   * - VM / SSH cluster
     - documented with validated operator surfaces
     - service-mode health gates, cluster-share diagnostics, and ORCHESTRATE
       operator checks
     - every remote topology still requires deployment-specific validation
   * - Hugging Face Space
     - validated
     - ``tools/hf_space_smoke.py --json`` and the public app-tree guardrail
     - availability depends on Hugging Face Spaces uptime

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
   uv --preview-features extra-build-dependencies run python tools/public_proof_scenarios.py --compact
   uv --preview-features extra-build-dependencies run python tools/public_proof_scenarios.py --first-proof-json first-proof.json --hf-smoke-json hf-space-smoke.json --output public-proof-scenarios.json
   uv --preview-features extra-build-dependencies run python tools/first_launch_robot.py --json --output first-launch-robot.json
   uv --preview-features extra-build-dependencies run python tools/security_hygiene_report.py --output security-hygiene.json --compact
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
--json`` writes ``~/log/execute/flight_telemetry/run_manifest.json``. The compatibility
report can ingest that manifest directly:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/compatibility_report.py \
     --manifest ~/log/execute/flight_telemetry/run_manifest.json \
     --compact

The broader evidence tooling covers release metadata, supply-chain metadata,
connector contracts, global pipeline state, CI artifact harvests, and promotion
decision exports. Keep those details in tool help, tests, and maintainer
runbooks; this public page should stay a readable support-status map.

The in-product first-proof wizard uses the same boundary: it routes newcomers
to the source-checkout ``flight_telemetry_project`` proof first, reads
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
