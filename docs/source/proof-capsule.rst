Proof capsule
=============

The product north star for AGILAB is a portable proof capsule: a reviewable
bundle that lets another operator verify what ran, where it ran, which
artifacts were produced, and how the work can be replayed or handed off.

AGILAB now ships a first proof-pack layer around ``run_manifest.json``. It can
write either a directory of plain JSON evidence or a hash-verifiable
``.agipack`` archive for portable handoff. The optional ``proof`` extra adds
detached Ed25519 signatures and local trust-policy verification. External
Sigstore/SLSA attestation binding remains a separate roadmap layer.

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
     - Imported notebook provenance or exported runnable ``agi-core`` notebook
       for handoff.
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

The shipped first layer operates on a run manifest:

.. code-block:: bash

   agilab prove ~/log/execute/flight_telemetry/run_manifest.json --output-dir proof-pack
   agilab prove ~/log/execute/flight_telemetry/run_manifest.json --export proof.agipack
   agilab verify ~/log/execute/flight_telemetry/run_manifest.json --strict
   agilab verify proof.agipack --strict
   agilab sign proof.agipack --key signer.pem --generate-key --signature proof.agipack.sig.json
   agilab verify proof.agipack --signature proof.agipack.sig.json --trust-policy policy.toml --strict
   agilab replay ~/log/execute/flight_telemetry/run_manifest.json
   agilab replay proof.agipack
   agilab story ~/log/execute/flight_telemetry/run_manifest.json --output-dir proof-pack/story
   agilab promotion-dossier ~/log/execute/flight_telemetry/run_manifest.json --output-dir proof-pack/promotion
   agilab export-lineage ~/log/execute/flight_telemetry/run_manifest.json --format all --output-dir proof-pack
   agilab export-traces proof.agipack --output-dir proof-pack
   agilab policy-check ~/log/execute/flight_telemetry/run_manifest.json --strict
   agilab cards ~/log/execute/flight_telemetry/run_manifest.json --output-dir proof-pack
   agilab metadata-store ~/log/execute/flight_telemetry/run_manifest.json --store ~/.agilab/metadata-store.json

The proof pack includes:

* a verification report
* a small policy report
* OpenLineage-shaped JSON
* RO-Crate metadata
* OpenTelemetry-shaped trace JSON
* ``run_story.json`` and ``run_story.md`` for a shareable one-run summary
* ``promotion_dossier.md`` plus ``promotion_decision.json`` for handoff review
* a local metadata-store entry
* model, dataset, prompt, and evaluation cards generated from available
  manifest evidence

The ``.agipack`` archive contains the same proof-pack files plus
``agipack-manifest.json`` with per-entry SHA-256 hashes and sizes.
``agilab verify proof.agipack`` checks the ZIP inventory, the recorded hashes,
the run-manifest snapshot, and the proof-pack manifest. ``agilab sign`` writes
a detached JSON signature containing the capsule SHA-256, signer/issuer
metadata, the Ed25519 public key, and the signature. ``agilab verify`` can then
validate that signature and enforce a JSON/TOML trust policy with allowed
public-key hashes, signers, issuers, or expected capsule hashes. Replay is safe
by default: ``agilab replay`` prints the recorded command from either
``run_manifest.json`` or ``proof.agipack`` and requires ``--execute`` before
launching it.

Run story
---------

``agilab story`` is the fast-adoption view of the same evidence. It reads a
``run_manifest.json`` file, hashes present artifacts, summarizes validations,
keeps only environment-variable names from command overrides, and writes:

* ``run_story.md`` for a human-readable execution story.
* ``run_story.json`` for CI, chat, ticket, or review-tool ingestion.

The command is read-only: it does not replay the run, call network services, or
execute recorded commands. Use it when a reviewer needs to understand what
happened after one AGILAB run without opening logs or notebooks first.

Promotion dossier
-----------------

``agilab promotion-dossier`` is the production-handoff view of the same
manifest. It does not deploy or serve a model. Instead it writes a deterministic
review package:

* ``promotion_decision.json`` with ``promote``, ``block``, or
  ``manual-review``.
* ``promotion_dossier.md`` for human reviewers.
* ``evidence_manifest.json`` with dossier file hashes and source artifacts.
* ``policy_results.json``, ``lineage.json``, ``mlflow_export.json``, and
  ``replay.sh`` for downstream systems.

Use it when a run needs a clear handoff package before MLflow, Kubeflow,
SageMaker, a CI promotion gate, or another production stack takes ownership.

Minimal trust policy example:

.. code-block:: toml

   schema = "agilab.proof_capsule_trust_policy.v1"
   allowed_public_key_sha256 = ["<public-key-sha256-from-signature>"]
   allowed_signers = ["AGILAB QA"]
   allowed_issuers = ["local"]

If ``cryptography`` is not installed, install the proof profile before signing:

.. code-block:: bash

   uv --preview-features extra-build-dependencies tool install --upgrade "agilab[proof]"

Keep using the existing first-proof and adoption commands as the entry evidence:

.. code-block:: bash

   agilab first-proof --json
   agilab adoption-report
   agilab security-check --profile shared --json

Roadmap boundary
----------------

The following items remain planned work, not shipped capability:

* external Sigstore/SLSA references and third-party attestation verification for
  signed ``.agipack`` archives
* transport to an external OpenLineage backend
* native OpenTelemetry SDK/OTLP spans across UI, worker build, distributed
  execution, notebook export, MLflow handoff, and agent runs
* durable ML metadata storage and query APIs
* app-authored model/data/prompt/eval cards with domain metadata
* richer policy-as-code, including potential OPA/Rego-compatible gates
* capability-based sandboxing for generated code, notebooks, and agent runs
* first-class agent eval traces and replayable scoring
* production monitoring, drift, RBAC, secrets-backend, and tenant-isolation
  integrations

Adoption rule
-------------

A proof capsule is promotion evidence, not a production certification. It
should make a controlled experiment reviewable and repeatable; production
serving, monitoring, RBAC, multi-tenant isolation, and regulated audit trails
remain responsibilities of the hardened platform AGILAB hands off to.
