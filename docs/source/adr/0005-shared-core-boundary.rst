ADR 0005: Shared Core Changes Require Explicit Blast-Radius Control
===================================================================

Status
------

Accepted.

Context
-------

The shared core packages handle environment resolution, worker deployment,
runtime orchestration, cluster behavior, and stable handoff surfaces. Small
changes can affect many apps, operating systems, and install modes.

Decision
--------

Shared core changes require explicit approval, impact validation, focused
tests, and typing checks when applicable. App-local fixes remain preferred
when the failure is app-local. Public behavior changes require documentation
updates in the same change.

Consequences
------------

- ``tools/impact_validate.py`` classifies shared-core risk.
- ``shared-core-typing`` and focused tests are release gates for shared
  runtime changes.
- Contributors must describe blast radius before editing shared core.
- The core stays stable enough to remain the smallest no-lock-in handoff
  surface.
