ADR 0001: Package Split Is The Publication Boundary
===================================================

Status
------

Accepted.

Context
-------

AGILAB contains runtime packages, UI packages, app payloads, page bundles,
examples, docs, and release tooling. Publishing every package on every change
creates unnecessary PyPI operations and makes cleanup expensive.

Decision
--------

The package split contract is the publication source of truth. Release tooling
must derive package matrices from ``tools/package_split_contract.py`` and
``tools/release_plan.py``. Packages whose current artifacts already exist on
PyPI can be skipped by the release plan instead of being rebuilt and uploaded
again.

Consequences
------------

- Package names, roles, project paths, and PyPI environments live in one place.
- Public docs and app catalogs must follow the package split.
- Release workflows can avoid redundant uploads and reduce PyPI cleanup work.
- Any package rename must update package split, docs, tests, and release plan
  evidence together.
