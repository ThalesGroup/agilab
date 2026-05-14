Strategic Potential
===================

This page explains AGILab's strategic potential score, the evidence behind it,
and the concrete proof needed before the score should increase. It is a public
scorecard, not a marketing claim.

Current score
-------------

AGILab currently supports a ``Strategic potential`` score of ``4.2 / 5``.

That score is based on a narrow position: AGILab is an experimentation and
engineering-validation workbench that connects project setup, reproducible
execution, evidence, and operator-facing analysis. It is not scored as a
production MLOps platform.

Strategic wedge
---------------

AGILab's strongest wedge is:

``run orchestration + evidence + reproducibility for engineering-grade AI workflows``

The project should be evaluated against that wedge, not against generic
dashboard builders, standalone schedulers, or production-serving platforms.

What supports the score
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Dimension
     - Evidence
     - Limit
   * - Adoption path
     - Public Hugging Face demo, local ``flight_telemetry_project`` first proof,
       ``run_manifest.json``, and newcomer troubleshooting.
     - Broader fresh-install validation still needs to run across more external
       machines.
   * - Differentiation
     - AGILab ties execution, artifacts, run evidence, Release Decision, and
       analysis pages into one path.
     - The project must keep this evidence-first story clear and avoid drifting
       into a generic MLOps comparison.
   * - Reproducibility
     - Compatibility report, KPI evidence bundle, run-diff evidence,
       revision-traceability, supply-chain metadata, and CI artifact harvest
       contracts.
     - Formal certification and production attestation are intentionally out of
       scope.
   * - Orchestration path
     - Multi-app DAG contract, global DAG reports, dispatch-state evidence,
       operator-action reports, and static operator UI proof.
     - Live global runner UI and broader cross-app execution remain roadmap
       work.
   * - Data access path
     - Connector facility, resolution, health planning, runtime adapters,
       app-local catalogs, and account-free cloud-emulator contracts.
     - Credentialed live cloud/provider validation remains operator-gated.
   * - Example quality
     - Packaged examples now have a learning path, expected inputs/outputs,
       safe adaptation guidance, and packaging tests.
     - The example scripts still need a final maturity pass before they should
       be treated as external SDK-quality examples.

Vertical stories
----------------

Two vertical stories should carry most public evaluation:

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Story
     - Why it matters
     - Evidence to keep fresh
   * - Flight + weather first proof
     - Demonstrates public onboarding, reproducible file input, generated
       artifacts, and analysis pages without private repositories.
     - ``agilab first-proof --json``, ``flight_telemetry_project``,
       ``weather_forecast_project``, compatibility matrix, and packaged examples.
   * - Mission Decision workflow
     - Demonstrates mission-style decision evidence, richer artifacts,
       connector-aware provenance, and the future DAG/release-decision path.
     - ``mission_decision_project``, Release Decision evidence, connector reports,
       run-diff evidence, and promotion-decision exports.

Elasticity opportunity
----------------------

The most credible strategic improvement is elasticity, not another tracking
dashboard or model registry. AGILab is strongest at the
``Train -> Test -> Evidence`` loop: run a pipeline, inspect artifacts, and
compare outcomes.

The first teaching route now exists in the optional industrial optimization
examples: Active Mesh Optimization models relay UAVs as controllable agents in
a compact centralized PPO policy, then exports movement, topology, and delivery
evidence. That is enough to demonstrate the contract shape, but it is not yet a
claim of full decentralized MARL certification for aircraft, UAV, or satellite
fleets.

This opportunity should raise the strategic score only when public evidence
shows the full hardening path: baseline versus adaptive-network comparison,
failure-injection comparison, service-contract handoff, and reproducible
multi-app DAG evidence through the existing artifact layer.

Score movement rule
-------------------

Do not raise the score only because the docs sound better. Raise it only when
new evidence closes a listed gap.

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Target score
     - Required proof
     - Still not claimed
   * - ``4.3 / 5``
     - Final beta gate passes with network included; packaged examples pass the
       external-beta maturity contract; public docs link the strategic
       scorecard; HF demo, PyPI, and docs are aligned to the same public
       release.
     - Production serving, enterprise governance, and formal certification.
   * - ``4.5 / 5``
     - At least two external fresh-machine first proofs are attached through
       run manifests or artifact indexes; global DAG operator flow has a live
       UI proof; connector examples demonstrate credentialed operator-gated
       validation without leaking secrets.
     - Multi-tenant production operations or cloud/Kubernetes parity.
   * - ``5.0 / 5``
     - AGILab becomes a de facto standard bridge for experimentation-to-handoff
       workflows with repeated external adoption evidence.
     - Generic full-stack MLOps replacement.

Signals that lower the score
----------------------------

Reduce the score, or keep it flat, if any of these appear in public artifacts:

- private app names or symlink-only local state leaking into public gates
- stale alpha/beta wording after a promoted release
- examples using private AGI internals or scratch-only snippets
- HF Space, PyPI, README, and docs pointing to different release states
- evidence commands that no longer pass or no longer match documented claims
- production-serving or certification language that is not backed by evidence

Related pages
-------------

- :doc:`agilab-mlops-positioning` for toolchain fit and current category scores
- :doc:`compatibility-matrix` for validated public routes and evidence commands
- :doc:`beta-readiness` for the beta promotion gate
- :doc:`features` for shipped capability evidence
