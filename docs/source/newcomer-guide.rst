Newcomer Guide
==============

If you are new to AGILab, optimize for one outcome only: one successful local
run of the built-in ``flight_project`` from the web UI.

This page gives the mental model only. :doc:`quick-start` owns the exact
commands. :doc:`newcomer-troubleshooting` owns the first-failure path.

Choose one route
----------------

.. list-table::
   :header-rows: 1

   * - Goal
     - Route
     - Use when
   * - See the UI now
     - :doc:`demos`
     - You want a browser-only look at the AGILAB web UI before installing
       anything.
   * - Prove it locally
     - :doc:`quick-start`
     - You want the real source-checkout path with ``flight_project``. Target:
       pass the first proof in 10 minutes.
   * - Use the API/notebook
     - :doc:`notebook-quickstart`
     - You want the smaller ``AgiEnv`` / ``AGI.run(...)`` surface before the
       full UI.

The first proof is deliberately narrow:
use a source checkout, run the built-in ``flight_project`` locally from the
web UI, and confirm a visible result under ``~/log/execute/flight/``.

That is enough for day 1. Do not widen the problem to notebooks, package mode,
private apps, or cluster setup until this path works once.

What to ignore on day 1
-----------------------

Skip these until the local ``flight_project`` proof works once:

- cluster and SSH setup
- published-package mode
- notebook-first route
- private or optional app repositories
- IDE convenience flows

The four words you need
-----------------------

- **PROJECT**: where you choose the app you want to run.
- **ORCHESTRATE**: where you install and execute it.
- **ANALYSIS**: where you look at the result.
- **Worker**: the isolated runtime that actually executes the app.

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

Where to go next
----------------

- :doc:`quick-start` for the exact first-proof commands.
- :doc:`newcomer-troubleshooting` if the local ``flight_project`` proof fails.
- :doc:`demos` if you want the public demo chooser instead of a local install.
- :doc:`notebook-quickstart` only if you intentionally choose the
  ``agi-core`` notebook path.
- :doc:`distributed-workers` only after the local proof works and you are ready
  for SSH or multi-node execution.
