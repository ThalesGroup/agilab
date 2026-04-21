Newcomer Guide
==============

If you are new to AGILab, optimize for one outcome only: one successful local
run of the built-in ``flight_project`` from the web UI.

This page gives the mental model. :doc:`quick-start` owns the exact commands.
:doc:`newcomer-troubleshooting` owns the first-failure path.

The first proof is deliberately narrow:

- source checkout
- local run
- built-in ``flight_project``
- ``PROJECT -> ORCHESTRATE -> ANALYSIS``
- visible result under ``~/log/execute/flight/``

That is enough for day 1. Do not widen the problem to notebooks, package mode,
private apps, or cluster setup until this path works once.

What to ignore on day 1
-----------------------

Skip these until the local ``flight_project`` proof works once:

- cluster and SSH setup
- published-package mode
- notebook-first route
- private or optional app repositories
- PyCharm or VS Code convenience flows

The core ideas, in plain language
---------------------------------

- **App / project**: a runnable AGILab workload with settings, manifests, and
  worker code.
- **ORCHESTRATE**: the page that turns settings into install, distribute, and
  run actions.
- **PIPELINE**: the place to save and replay generated steps instead of
  retyping code snippets.
- **ANALYSIS**: Streamlit pages for post-run inspection.
- **Worker**: the isolated runtime that actually executes the workload.

Common newcomer traps
---------------------

- **Mixing package mode and source mode without being explicit**:
  pick one first, then switch deliberately.
- **Trying cluster mode before a local run succeeds**:
  local success gives you a clean baseline for later SSH debugging.
- **Expecting private or optional apps to appear automatically**:
  public built-in apps live under ``src/agilab/apps/builtin``; extra apps
  usually require ``APPS_REPOSITORY`` / ``AGILAB_APPS_REPOSITORY``.
- **Running ``uvx agilab`` from the source tree**:
  from a repository checkout, use the source commands documented in
  :doc:`quick-start` so you do not accidentally run the published wheel.
- **Contributors editing generated docs output**:
  edit ``docs/source`` in the docs repository, not ``docs/html``.

Where to go next
----------------

- :doc:`quick-start` for the exact first-proof commands and the optional
  alternative routes after that.
- :doc:`newcomer-troubleshooting` if the local ``flight_project`` proof fails.
- :doc:`compatibility-matrix` for the current validated versus documented
  public slices.
- :doc:`notebook-quickstart` only after you intentionally choose the
  ``agi-core`` notebook route.
- :doc:`distributed-workers` only after the local proof works and you are ready
  for SSH or multi-node execution.
