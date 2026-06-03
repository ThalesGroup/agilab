ADR 0004: Extensions Grow Through Contracts
===========================================

Status
------

Accepted.

Context
-------

AGILAB can grow through apps, page bundles, notebook bridges, connectors,
proof reports, and worker extensions. If each feature invents its own metadata
and evidence shape, maintenance cost grows faster than product value.

Decision
--------

Every extension type must declare metadata, evidence, guardrails, and maturity
labels. The public extension contract kit documents those requirements and the
maintenance dashboard checks that the kit exists.

Consequences
------------

- New public apps need docs, package/catalog alignment, and evidence outputs.
- New pages need app-agnostic discovery and isolated dependencies.
- New connectors must distinguish contract proof from live endpoint proof.
- Roadmap boundaries stay visible until implementation and release evidence
  exist.
