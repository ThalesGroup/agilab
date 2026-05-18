Proof capsule
=============

The product north star for AGILAB is a portable proof capsule: a reviewable
bundle that lets another operator verify what ran, where it ran, which
artifacts were produced, and how the work can be replayed or handed off.

This is the product shape AGILAB should converge toward; it is not yet shipped
as one archive file or one ``agilab prove`` command.

Why this matters
----------------

Most AI/ML tools can track metrics, launch pipelines, or host notebooks. The
harder product gap is a compact handoff object for experimental work: code,
runtime context, visible UI evidence, generated artifacts, dependency state,
and supply-chain evidence kept together with enough metadata to audit or rerun
the work later.

AGILAB's strongest long-term position is that handoff layer:

* MLflow tracks experiment runs and artifacts.
* AGILAB turns notebooks and scripts into controlled executable applications.
* A proof capsule should preserve the evidence needed to review, compare,
  replay, or promote that application outside the original developer session.

Capsule contents
----------------

A complete proof capsule should contain these parts:

.. list-table::
   :header-rows: 1

   * - Layer
     - Capsule content
     - Current AGILAB building block
   * - Execution
     - App path, command, runtime mode, platform, Python version, duration,
       success status, and failure diagnostics.
     - ``agilab first-proof --json`` and ``run_manifest.json``.
   * - Application snapshot
     - Stage contract, app metadata, selected settings, and safe paths needed
       to rerun the application.
     - ``lab_stages.toml``, app settings seeds, and exported run manifests.
   * - Notebook bridge
     - Imported notebook provenance or exported runnable notebook for handoff.
     - WORKFLOW notebook import/export and notebook export manifests.
   * - Tracking handoff
     - MLflow run identifiers or exported tracking metadata when MLflow is
       enabled.
     - Optional MLflow integration and run artifact handoff.
   * - Visible evidence
     - Screenshots, UI robot progress logs, failure bundles, traces, HAR, and
       video when captured by the validation robot.
     - UI robot evidence, visual baselines, and failure replay artifacts.
   * - Artifact inventory
     - Output files, hashes, schema labels, summaries, and comparison metadata.
     - ANALYSIS artifacts, release-decision evidence, and run-diff reports.
   * - Environment
     - Dependency lock information, wheel hashes, package versions, platform
       markers, and optional extras actually used.
     - Release proof, profile supply-chain scans, and package metadata.
   * - Supply chain
     - SBOM, ``pip-audit`` output, PyPI provenance, GitHub release assets, and
       attestation references.
     - Release workflow SBOM, audit, trusted publishing, and provenance checks.
   * - Human summary
     - A short machine-readable and human-readable conclusion: what passed,
       what failed, what is out of scope, and what to do next.
     - Adoption reports, release proof, compatibility matrix, and security
       checks.

Target CLI shape
----------------

The reserved product shape is:

.. code-block:: bash

   agilab prove . --profile audit --export proof.agipack
   agilab verify proof.agipack
   agilab replay proof.agipack

These commands should not be documented as available until the archive schema,
verification rules, and replay boundary are implemented. Until then, use the
existing evidence commands:

.. code-block:: bash

   agilab first-proof --json --with-ui
   agilab adoption-report
   agilab security-check --profile shared --json

Adoption rule
-------------

A proof capsule is promotion evidence, not a production certification. It
should make a controlled experiment reviewable and repeatable; production
serving, monitoring, RBAC, multi-tenant isolation, and regulated audit trails
remain responsibilities of the hardened platform AGILAB hands off to.
