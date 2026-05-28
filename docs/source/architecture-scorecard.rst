Architecture scorecard
======================

This page records AGILAB's architecture self-assessment from repository
evidence. It is not a production MLOps certification, not a security
certification, and not a multi-tenant production platform score.

Current supported score
-----------------------

``4.5 / 5`` for the evidence-first workbench architecture.

The scope is deliberately narrow: AGILAB has an excellent architecture for
turning AI/ML experiments, notebooks, app runs, and agent-assisted workflows
into replayable evidence. The same score is conditional for shared or
multi-tenant production use because tenant isolation, enterprise auth, RBAC,
production rollback, and regulated serving remain deployment responsibilities
outside the current AGILAB core.

Executable scorecard
--------------------

Run the scorecard locally:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/architecture_scorecard.py --compact

The production-readiness profile also consumes this scorecard:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile production-readiness

What must stay true
-------------------

.. list-table::
   :header-rows: 1
   :widths: 28 42 30

   * - Architecture dimension
     - Excellent means
     - Evidence gate
   * - Control, payload, and evidence planes
     - UI, CLI, notebooks, manager runtime, worker runtime, artifacts, and
       proof files have clear responsibilities.
     - ``architecture_plane_boundaries``
   * - Runtime guardrails
     - Known bad states fail closed for public UI binds, cluster shares,
       missing manifests, notebook imports, service health, and routes.
     - ``architecture_runtime_guardrails``
   * - Supply chain and release proof
     - Release artifacts, provenance, SBOM/audit planning, and release proof
       are checked by tooling rather than prose.
     - ``architecture_supply_chain_release_proof``
   * - Remote execution hardening
     - Dynamic SSH command fragments such as worker paths, scheduler
       addresses, and PID paths are quoted by a central builder.
     - ``architecture_remote_execution_hardening``
   * - Capacity model trust boundary
     - The optional pickle capacity predictor is loaded only from the trusted
       resources root and world-writable files are refused.
     - ``architecture_capacity_model_trust_boundary``
   * - Claim boundary
     - Public wording says exactly what the architecture proves and does not
       promote roadmap or production-platform claims as shipped features.
     - ``architecture_claim_boundary``

Score movement rule
-------------------

The score can increase only when a repository check links the claim to an
executable report, test, manifest, workflow, or public proof artifact. It must
decrease or become conditional when the evidence is missing, advisory-only, or
depends on manual trust.

Use this page as the architecture evidence index. Use
:doc:`architecture-five-minutes` for the mental model, :doc:`architecture` for
the full stack reference, and :doc:`agilab-mlops-positioning` for the production
boundary.
