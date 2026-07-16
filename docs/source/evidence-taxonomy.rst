Evidence Taxonomy
=================

AGILAB evidence should be easy to inspect without rerunning the workflow. This
taxonomy proposes a shared vocabulary for run manifests, proof bundles,
notebook exports, UI robot evidence, MLflow handoff records, and release proof.
It is a target model: today the shipped evidence producers do not yet emit a
single unified envelope, so the field names below are planned and each row is
marked planned or shipped.

Common Event Envelope
---------------------

The proposed common envelope below is the direction AGILAB evidence bundles are
moving toward. No producer in the repository emits this exact envelope yet, so
treat the field names as planned unless the ``Status`` column says otherwise.
Shipped evidence currently uses producer-specific names such as ``created_at``
plus ``kind`` plus ``schema_version``, or ``sequence`` / ``timestamp`` /
``type``, or a ``schema`` string like ``"agilab.<name>.v1"``. See the mapping
table below for how the planned names correspond to what is actually emitted.

.. list-table::
   :header-rows: 1

   * - Field
     - Status
     - Meaning
   * - ``schema_version``
     - Planned (shipped as ``schema`` string, e.g. ``"agilab.<name>.v1"``, or a
       separate ``schema_version`` value)
     - Version of the evidence event schema.
   * - ``event_type``
     - Planned (shipped as ``kind`` or ``type``)
     - One of the event names listed below.
   * - ``run_id``
     - Planned (shipped as ``run_id`` in some bundles)
     - AGILAB run, proof, robot, release, or agent-run identifier.
   * - ``seq``
     - Planned (shipped as ``sequence`` in some bundles)
     - Monotonic sequence number within the evidence bundle.
   * - ``created_at_utc``
     - Planned (shipped as ``created_at``, ``timestamp``, or ``generated_at``)
     - UTC timestamp recorded by the producing tool.
   * - ``artifact_sha256``
     - Planned (shipped as artifact hash fields on individual artifact records)
     - SHA-256 of the referenced artifact when the event has one.
   * - ``prev_event_hash``
     - Planned (not emitted; reserved for a future tamper-evident chain)
     - Optional previous event hash for future tamper-evident chains.
   * - ``event_hash``
     - Planned (not emitted; reserved for a future tamper-evident chain)
     - Optional hash of the canonicalized event envelope and payload.
   * - ``payload``
     - Planned (shipped as the producer-specific record body)
     - Event-specific metadata. It must not contain secrets or large raw
       artifacts.

Planned-to-shipped field mapping
--------------------------------

Until a single envelope ships, verifiers must read the producer-specific field
names. This table maps the planned taxonomy names to the names currently
emitted by shipped evidence producers.

.. list-table::
   :header-rows: 1

   * - Planned taxonomy field
     - Shipped field name(s)
   * - ``schema_version``
     - ``schema`` (e.g. ``"agilab.ui_robot_evidence.v1"``) or ``schema_version``
   * - ``event_type``
     - ``kind`` or ``type``
   * - ``run_id``
     - ``run_id``
   * - ``seq``
     - ``sequence``
   * - ``created_at_utc``
     - ``created_at``, ``timestamp``, or ``generated_at``
   * - ``artifact_sha256``
     - per-artifact hash fields (no single top-level ``artifact_sha256``)
   * - ``prev_event_hash`` / ``event_hash``
     - not emitted yet (reserved)
   * - ``payload``
     - the producer-specific record body

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
