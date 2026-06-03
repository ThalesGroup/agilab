Evidence Taxonomy
=================

AGILAB evidence should be easy to inspect without rerunning the workflow. This
taxonomy defines the first shared vocabulary for run manifests, proof bundles,
notebook exports, UI robot evidence, MLflow handoff records, and release proof.

Common Event Envelope
---------------------

Evidence events should use a small common envelope when they are serialized into
JSON evidence bundles:

.. list-table::
   :header-rows: 1

   * - Field
     - Meaning
   * - ``schema_version``
     - Version of the evidence event schema.
   * - ``event_type``
     - One of the event names listed below.
   * - ``run_id``
     - AGILAB run, proof, robot, release, or agent-run identifier.
   * - ``seq``
     - Monotonic sequence number within the evidence bundle.
   * - ``created_at_utc``
     - UTC timestamp recorded by the producing tool.
   * - ``artifact_sha256``
     - SHA-256 of the referenced artifact when the event has one.
   * - ``prev_event_hash``
     - Optional previous event hash for future tamper-evident chains.
   * - ``event_hash``
     - Optional hash of the canonicalized event envelope and payload.
   * - ``payload``
     - Event-specific metadata. It must not contain secrets or large raw
       artifacts.

Event Types
-----------

.. list-table::
   :header-rows: 1

   * - Event type
     - Purpose
   * - ``run_manifest_event``
     - Records the top-level run manifest, selected app, environment, and
       command boundary.
   * - ``stage_transition_event``
     - Records a workflow, DAG, or pipeline stage state transition.
   * - ``artifact_event``
     - Records a produced file, directory manifest, or content hash.
   * - ``notebook_export_event``
     - Records an exported notebook or notebook export manifest.
   * - ``mlflow_handoff_event``
     - Records an MLflow tracking or registry handoff when that integration is
       enabled.
   * - ``ui_robot_event``
     - Records screenshots, traces, HAR, video, aggregate JSON, and replay
       commands from UI robot validation.
   * - ``agent_run_event``
     - Records a coding-agent or assistant-backed command through the AGILAB
       agent-run evidence surface.
   * - ``policy_check_event``
     - Records a deterministic policy or promotion gate decision.
   * - ``release_proof_event``
     - Records release tag, package, docs, CI, coverage, SBOM, audit, or
       provenance evidence used in release proof.

Redaction Rules
---------------

Evidence payloads must not store secrets, raw prompts that contain credentials,
full notebook outputs with sensitive data, or large artifact bodies. Prefer:

* content hashes over raw content
* stable reason codes over free text when a code is enough
* local file references over embedded blobs
* explicit ``redacted`` markers when a field was intentionally removed

Verifier Scope
--------------

A verifier consumes this taxonomy to check evidence without rerunning work. It
may validate:

* schema versions
* required event fields
* monotonic sequence numbers
* artifact hash matches
* reference closure
* release-proof metadata consistency

It must not validate facts outside the evidence bundle, such as legal
compliance, model correctness, production suitability, or whether an external
auditor accepts the evidence.

Roadmap Boundary
----------------

Optional ``prev_event_hash`` and ``event_hash`` fields make room for a future
tamper-evident chain. Until that verifier is shipped and referenced from the
release proof, public wording must stay at "hash-backed evidence" or
"designed toward tamper-evident chains", not "tamper-proof".
