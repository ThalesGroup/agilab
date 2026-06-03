ADR 0003: Notebook Bridge Preserves Work In Both Directions
===========================================================

Status
------

Accepted.

Context
-------

Many users start in notebooks. AGILAB adds structure through apps, stages,
runtime roles, artifacts, and evidence. Long-term adoption depends on users
not losing work when they later decide the UI or distributed runtime is not
the right interface.

Decision
--------

Notebook import and export are a reversible adoption bridge. Import turns a
reviewed notebook into AGILAB stages. Export turns saved AGILAB stages back
into a runnable ``agi-core`` supervisor notebook with stage order, runtime
hints, review context, and artifact references.

Consequences
------------

- Notebook cells must not be blindly trusted; role metadata or explicit review
  is required.
- Export is an exit and handoff path, not only a convenience download.
- Notebook examples should remain small, runnable, and aligned with public app
  examples.
- Import/export regressions are release-facing because they support the
  no-lock-in claim.
