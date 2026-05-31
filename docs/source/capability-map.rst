Capability Map
==============

AGILAB has many demos, apps, reports, and proof commands. Use this page as the
product map: start from the user job, follow the shortest route, then inspect
the evidence and boundary before expanding to advanced features.

For agent and tooling discovery, the repository root also ships
``agilab-capabilities.json``. Regenerate it with
``python3 tools/agilab_capabilities_manifest.py --apply``. The manifest lists
checked-in CLI commands, Streamlit pages, public apps, packages, schemas, docs,
and catalog files; it is a discovery index, not runtime validation or external
certification evidence. The paired ``agilab-capabilities.schema.json`` file
defines the JSON contract, while
``python3 tools/agilab_capabilities_lint.py --check`` enforces cross-object
rules such as existing docs paths, summary counts, known app packages, and
evidence-schema references. The linter's auditable rule metadata lives in
``agilab-capability-rules.yml`` with stable severity, category, rationale, and
profile groupings.
The root ``agenticweb.md`` file is generated from the same capability manifest
as a compact discovery front door for AI agents. Check it with
``python3 tools/agenticweb_manifest.py --check``; it is a discovery index, not
additional runtime validation.

Maturity labels
---------------

.. list-table::
   :header-rows: 1
   :widths: 22 42 36

   * - Label
     - Meaning
     - User action
   * - Live product path
     - Shipped UI or CLI route intended for normal local use.
     - Run it directly, then inspect the generated evidence.
   * - Local proof
     - Deterministic packaged proof that avoids external accounts, secrets, or
       long-running services.
     - Use it to validate a boundary before replacing the local fixture with
       real infrastructure.
   * - Contract proof
     - Static or dry-run validation of schema, configuration, dependency, or
       handoff contracts.
     - Treat it as readiness evidence, not as a live integration test.
   * - Operator-triggered live check
     - Optional check that touches an operator-managed endpoint, worker, cloud
       account, or tracking service.
     - Enable it only in an environment where credentials, network access, and
       isolation are intentional.
   * - Roadmap boundary
     - Documented direction that is not shipped as a first-class product
       primitive yet.
     - Do not present it as current capability; use the linked building blocks
       or integrations instead.

Job-to-route map
----------------

.. list-table::
   :header-rows: 1
   :widths: 18 23 25 19 15

   * - User job
     - Shortest route
     - Evidence to inspect
     - Maturity
     - Boundary
   * - See AGILAB without installing it
     - :doc:`agilab-demo`
     - Hosted UI route and release proof references.
     - Live product path
     - Hosted availability is release-time evidence, not an SLA.
   * - Prove a local install
     - :doc:`quick-start`
     - ``agilab first-proof --json`` and ``run_manifest.json``.
     - Live product path
     - Local proof first; cluster mode comes later.
   * - Start notebook-first
     - :doc:`notebook-quickstart`
     - Minimal ``AgiEnv`` / ``AGI.run(...)`` run evidence.
     - Live product path
     - Smaller core surface, not the full UI path.
   * - Import an existing notebook
     - :doc:`notebook-migration-skforecast-meteo`
     - ``lab_stages.toml``, import preview, artifacts, analysis views.
     - Live product path
     - Notebook cells are imported without being trusted blindly.
   * - Validate a workflow before execution
     - ``agilab workflow validate <lab_stages.toml> --dry-run --json``
     - ``agilab.workflow_dry_run_report.v1`` with stage, dependency,
       artifact-flow, role, app-reference, and static code checks.
     - Contract proof
     - Static validation catches contract issues; it does not execute stages or
       prove runtime success.
   * - Keep a durable exit path
     - :doc:`notebook-advanced`
     - Runnable ``agi-core`` supervisor notebook export and export manifest.
     - Live product path
     - Export preserves work; it does not certify production readiness.
   * - Review a run
     - :doc:`proof-capsule`
     - ``agilab prove``, ``verify``, ``story``, ``promotion-dossier`` outputs.
     - Live product path
     - Proof capsules are engineering evidence, not external certification.
   * - Route a coding-agent task
     - ``python3 tools/agent_context_router.py --files <paths> --prompt <task> --json``
     - ``agilab.agent_context_recommendation.v1`` with matched rules, runbooks,
       and recommended repo-managed skills.
     - Contract proof
     - Routes context only; it does not execute agents, tests, or repository
       mutations.
   * - Expose agentic-web discovery
     - ``python3 tools/agenticweb_manifest.py --check``
     - Generated ``agenticweb.md`` derived from ``agilab-capabilities.json``.
     - Contract proof
     - Discovery only; it does not prove runtime success or production
       readiness.
   * - Compare or promote evidence
     - :doc:`advanced-proof-pack`
     - Release-decision views, run-diff reports, promotion dossier artifacts.
     - Live product path
     - Promotion remains a handoff decision for the downstream platform.
   * - Prove database access locally
     - :ref:`SQLite database proof <sqlite-database-proof>`
     - SQLite DB, result CSV, ``database_evidence.json`` hashes.
     - Local proof
     - Replace the local URI with real databases only after operator review.
   * - Validate a file-based data or document handoff
     - ``python3 tools/data_artifact_lane_contract.py --profile data-analysis --root <bundle> --check --json``
     - ``agilab.data_artifact_lane_contract.v1`` with role directories,
       required artifact rules, file sizes, and SHA-256 hashes.
     - Contract proof
     - Checks handoff presence and hashability, not data correctness, OCR
       quality, privacy compliance, or service liveness.
   * - Prepare cloud/object-storage connectors
     - :doc:`data-connectors`
     - Facility, resolution, health-plan, and runtime-adapter reports.
     - Contract proof
     - Public checks do not prove real IAM, firewalls, billing, or quota.
   * - Show performance engineering
     - :doc:`execution-playground`
     - Benchmark JSON/CSV, reducer artifacts, checksum-matched speedups.
     - Local proof
     - Kernel-level speedups are not universal end-to-end promises.
   * - Use packaged public apps
     - :doc:`public-app-catalog`
     - App catalog, package status, reducer and app-contract guardrails.
     - Live product path
     - Apps are examples/workbench payloads, not production deployments.
   * - Scale to workers or cluster
     - :doc:`cluster` and :doc:`distributed-workers`
     - Worker packaging logs, service health gates, cluster validation output.
     - Operator-triggered live check
     - Requires explicit share, accounts, quotas, and network isolation.
   * - Integrate with MLflow
     - :doc:`agilab-mlops-positioning`
     - MLflow run/artifact references plus AGILAB run evidence.
     - Operator-triggered live check
     - MLflow remains the tracking/registry system of record.
   * - Publish release evidence
     - :doc:`release-proof`
     - Package proof, CI guardrails, SBOM, ``pip-audit``, provenance.
     - Live product path
     - Proves the release route, not every deployment topology.

Evidence Core reading order
---------------------------

When a run needs review, inspect evidence in this order:

1. ``run_manifest.json`` for command, app, status, paths, and duration.
2. App artifacts and reducer summaries for domain outputs and hashes.
3. Notebook import/export manifests when the work entered or leaves through a
   notebook.
4. ``agilab workflow validate <lab_stages.toml> --dry-run --json`` when the
   question is static workflow readiness before execution.
5. ``agilab prove`` / ``agilab verify`` output or a ``.agipack`` archive when a
   portable proof package is needed.
6. Release proof, SBOM, ``pip-audit``, and provenance only when the question is
   package or release trust.

This is the current Evidence Core operating model: evidence files remain plain
JSON or manifest-backed artifacts, while the proof capsule page explains the
portable bundle boundary and roadmap.

Adoption rule
-------------

Use the lowest maturity level that proves the question:

- choose a live product path for ordinary local use;
- choose a local proof when the question is a boundary such as database access
  or compiled worker execution;
- choose a contract proof before touching external systems;
- choose an operator-triggered live check only after credentials, network
  access, and isolation are intentional;
- keep roadmap boundaries out of user-facing claims until implementation and
  release proof exist.
