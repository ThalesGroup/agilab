ADR 0002: Evidence Core Is The Maintenance Backbone
===================================================

Status
------

Accepted.

Context
-------

AGILAB has many evidence surfaces: run manifests, notebook import/export
manifests, reducer artifacts, release proof, SBOM, dependency audit, UI robot
evidence, proof packs, and promotion dossiers. Without a shared reading order,
the product becomes a collection of reports.

Decision
--------

Evidence Core is the maintenance backbone. A meaningful run or public feature
should be reviewable through plain evidence: run manifest, artifact hashes,
notebook provenance when relevant, verifier output, and an explicit claim
boundary. Proof capsules and promotion dossiers package that evidence for
handoff; they do not certify production readiness by themselves.

Consequences
------------

- New evidence reports need schema versions and producer commands.
- Public claims must point to concrete evidence and limitations.
- Reviewers should inspect evidence before rerunning workflows.
- Future dashboards and release gates should aggregate evidence instead of
  inventing another source of truth.
