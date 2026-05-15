Newcomer Guide
==============

If you are new to AGILab, optimize for one outcome only: one successful local
proof from the web UI. The default lane is the built-in
``flight_telemetry_project`` through ABOUT -> ``INSTALL`` -> ``RUN`` ->
``ANALYSIS``. If you already have a notebook, use the ABOUT wizard's
``Import notebook`` lane instead and prove that imported project before
expanding.

This page gives the mental model only. :doc:`quick-start` owns the exact
commands. :doc:`newcomer-troubleshooting` owns the first-failure path.

Fast adoption ladder
--------------------

Use this order when you need the quickest route to confidence:

.. list-table::
   :header-rows: 1

   * - Stage
     - What to do
     - Why it matters
   * - Browser preview
     - Open :doc:`agilab-demo`.
     - Confirms the public UI shape before you install anything.
   * - Local first proof
     - Follow :doc:`quick-start` with the built-in
       ``flight_telemetry_project``, or use the wizard's notebook-import lane
       when your first asset is already a notebook.
     - Exercises the real source-checkout install, run, analysis, or notebook
       import path.
   * - Evidence record
     - Keep ``~/log/execute/flight_telemetry/run_manifest.json`` from
       ``agilab first-proof --json``.
     - Gives support, contributors, and future runs the same baseline.
   * - Expansion
     - Move to notebooks, package mode, private apps, or cluster work.
     - Prevents day-1 failures from mixing product, app, and infrastructure
       variables.

Choose one route
----------------

.. list-table::
   :header-rows: 1

   * - Goal
     - Route
     - Use when
   * - See the UI now
     - :doc:`agilab-demo`
     - You want a browser-only look at the AGILAB web UI before installing
       anything.
   * - Prove it locally
     - :doc:`quick-start`
     - You want the real source-checkout path. Default target: pass the
       ``flight_telemetry_project`` proof in 10 minutes. Alternative: import
       your own notebook from the ABOUT wizard.
   * - Use the API/notebook
     - :doc:`notebook-quickstart`
     - You want the smaller ``AgiEnv`` / ``AGI.run(...)`` surface before the
       full UI.

The first proof is deliberately narrow. Use a source checkout and choose one
lane from the landing page:

- built-in lane: run ``flight_telemetry_project`` locally, inspect the visible
  result under ``~/log/execute/flight_telemetry/``, and keep the passing
  ``run_manifest.json``
- notebook lane: upload one notebook through ``Import notebook`` / ``Upload``,
  create the project, then prove that imported project before adding
  infrastructure variables

That is enough for day 1. Do not widen the problem to package mode, private
apps, or cluster setup until one lane works once and gives you a clear
baseline.

This also means PyCharm is not part of the day-1 contract. AGILAB keeps
PyCharm run configurations for developers who want IDE debugging, but the
newcomer route is shell + browser first. The same install, execute, and
analysis path can be driven from commands, the web UI, or checked-in wrappers.

Which example should I start with?
----------------------------------

Use this decision guide before opening the full packaged example catalog in
``src/agilab/examples/README.md``. It picks one first step and avoids mixing
runtime goals.

.. list-table::
   :header-rows: 1

   * - Goal
     - Start with
     - Why
   * - Prove AGILAB works locally
     - ``flight_telemetry_project``
     - This is the recommended first proof: install one public built-in app,
       run it, inspect visible output, and keep ``run_manifest.json``.
   * - Modify the smallest app
     - ``mycode_project``
     - It is the minimal built-in app/template to adapt after the first proof
       passes.
   * - Explore richer app behavior
     - ``weather_forecast_project`` or ``mission_decision_project``
     - Use these after the first proof when you want more domain behavior than
       the template app.
   * - Understand a contract before running a full app
     - Read-only preview examples such as ``service_mode`` or
       ``mlflow_auto_tracking``
     - They write deterministic JSON evidence and do not launch hidden
       long-lived services or multi-app runs.
   * - Learn notebook migration
     - ``notebook_migrations/skforecast_meteo_fr``
     - These are source assets to inspect or import; reading them does not
       start a service or cluster run.

Rule of thumb: run ``flight_telemetry_project`` first, modify
``mycode_project`` second, then use previews and notebook assets to understand
specific contracts before expanding to richer apps or cluster work.

Adoption evidence
-----------------

On April 24, 2026, the source-checkout first-proof smoke passed locally in
``5.86s`` against the ``600s`` target. On April 25, 2026, the same
source-checkout proof passed on a fresh external machine in ``26.87s``.
On April 27, 2026, the packaged first-proof CLI passed locally in ``7.04s``:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run agilab first-proof --json

The JSON proof writes ``~/log/execute/flight_telemetry/run_manifest.json``. That manifest
is the portable first-proof run record: command, Python/platform context, active
app, timing, artifact references, and validation status.

That supports an ``Ease of adoption`` score of ``4.0 / 5``: the public demo
works, the first routes are explicit, PyCharm is optional, installer tests are
opt-in, and the source-checkout proof now has local, fresh external macOS,
repeatable Flight cluster doctor, AI Lightning, Hugging Face, bare-metal
cluster, and VM-based cluster validation.
It is not scored higher yet because Azure, AWS, and GCP deployment validation
remains open.

After day 1: cluster proof
--------------------------

Cluster validation is a second milestone, not part of the newcomer proof.
Use it only after the local ``flight_telemetry_project`` path has passed once.

For the repeatable two-node check, go to :doc:`cluster`. That page owns:

- LAN discovery and SSH prerequisites
- shared cluster-share setup and sentinel checks
- the Flight cluster doctor command
- source-checkout and package-mode cluster validation commands

What to ignore on day 1
-----------------------

Skip these until either the local ``flight_telemetry_project`` proof or one
notebook-import proof works once:

- cluster and SSH setup
- published-package mode
- private or optional app repositories
- IDE convenience flows
- full installer test suites unless you explicitly want validation instead of
  the fastest first proof

The five words you need
-----------------------

- **PROJECT**: where you choose the app you want to run.
- **ORCHESTRATE**: where you install and execute it.
- **WORKFLOW**: where you inspect, generate, or replay run stages.
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
  require ``APPS_REPOSITORY`` to point at the external apps repository.
- **Running ``uvx agilab`` from the source tree**:
  from a repository checkout, use the source commands documented in
  :doc:`quick-start` so you do not accidentally run the published wheel.
- **Assuming PyCharm is required**:
  PyCharm mirrors are useful for debugging, but the supported first proof is
  independent of PyCharm.

Where to go next
----------------

- :doc:`quick-start` for the exact first-proof commands.
- :doc:`newcomer-troubleshooting` if the local ``flight_telemetry_project`` proof fails.
- :doc:`agilab-demo` if you want the public hosted web UI instead of a local
  install.
- :doc:`demos` if you want the public demo chooser.
- :doc:`notebook-quickstart` only if you intentionally choose the
  ``agi-core`` notebook path.
- :doc:`distributed-workers` only after the local proof works and you are ready
  for SSH or multi-node execution.
