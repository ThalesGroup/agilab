Security And Adoption Boundary
==============================

Use this page when you need a short audit-facing answer about AGILAB adoption,
security reporting, and hardening. It does not replace ``SECURITY.md``; the
repository security policy remains the source of truth for coordinated
vulnerability disclosure.

Vulnerability reporting
-----------------------

Do not use public GitHub issues, discussions, pull requests, or comments for
suspected vulnerabilities.

Use GitHub Private Vulnerability Reporting when it is available for the
repository. If that private channel is unavailable to you, ask the maintainers
for a private AGILAB security intake channel without sharing exploit details
publicly. Share reproduction steps, exploit details, secrets, or sensitive logs
only after a private channel has been confirmed.

Public GitHub issues are for non-sensitive product bugs, support questions, and
post-fix follow-up only.

Adoption boundary
-----------------

AGILAB is a trusted-operator experimentation workbench. It can install apps,
generate and execute Python snippets, launch worker environments, orchestrate
local or distributed runs, and optionally start UI, tracking, or local-model
tooling. Treat apps, notebooks, generated snippets, and external app
repositories as executable code until they have been reviewed.

.. list-table::
   :header-rows: 1

   * - Decision
     - Fit
     - Minimum controls
   * - Go for controlled local use
     - Local research sandbox, internal demo, notebook-to-app migration, and
       reproducible validation with non-sensitive data.
     - Normal repository hygiene, one local first proof, and evidence under
       ``~/log/execute``.
   * - Go for hardened shared/team use
     - Shared workstation, internal cluster, external apps repository, LLM
       connector, local/offline LLM, or sensitive internal data when the
       hardening gate passes.
     - Clean strict ``agilab security-check`` report for the target profile,
       per-user isolation, explicit secrets management, TLS/auth for exposed
       services, app-repository allowlist and immutable pinning, SBOM plus
       vulnerability scan evidence for the deployed install profile, bounded
       resources, and a deployment threat model.
   * - No-go as a standalone production platform
     - Public Streamlit exposure, open multi-tenant service, regulated
       production model serving, enterprise governance, online monitoring,
       drift detection, or sole MLOps control plane.
     - Pair AGILAB with a hardened production stack such as MLflow, Kubeflow,
       SageMaker, Dagster, Airflow, or an internal platform.

Operational checks
------------------

Before moving beyond a single-user proof, archive the profile-specific security
and supply-chain evidence for the environment you will actually deploy. Treat a
clean strict report plus profile-specific SBOM and vulnerability evidence as
the documented go gate for hardened shared/team use:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run agilab security-check --profile shared --json > security-check.json
   uv --preview-features extra-build-dependencies run python tools/profile_supply_chain_scan.py --profile all --run

Use strict mode when missing controls must fail the gate:

.. code-block:: bash

   AGILAB_SECURITY_CHECK_STRICT=1 \
   uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile security-adoption

For public release evidence, use :doc:`release-proof`. Treat it as bounded
release evidence, not production certification for every remote cluster,
GPU/cloud stack, private app repository, security posture, or long-running
operation.

Untrusted content boundary
--------------------------

AGILAB treats notebooks, external apps repositories, model-generated snippets,
and uploaded files as untrusted content until they have been reviewed in the
target environment. The current helper writes or exposes
``agilab.untrusted_content_boundary.v1`` metadata with the source kind, source
name, SHA-256 or repository-source marker, trust status, and handling
instructions.

Current integration points:

* Notebook project import writes
  ``<notebook>.untrusted-content.json`` beside the imported notebook.
* WORKFLOW LLM code extraction records a generated-snippet boundary in session
  state before the code is reviewed or executed.
* ``agilab security-check`` annotates configured ``APPS_REPOSITORY`` checkouts
  as external executable-content boundaries while still enforcing pinning and
  allowlist policy for shared profiles.

The boundary is evidence, not a sandbox. It makes the trust decision visible and
hashable; it does not make arbitrary notebooks, app repositories, uploads, or
LLM snippets safe to execute without review, isolation, and the appropriate
security-check profile.

See also
--------

- ``SECURITY.md`` in the GitHub repository for the coordinated disclosure
  policy.
- :doc:`quick-start` for the local first-proof route.
- :doc:`environment` for secret and UI bind environment variables.
- :doc:`agilab-mlops-positioning` for the production MLOps boundary.
