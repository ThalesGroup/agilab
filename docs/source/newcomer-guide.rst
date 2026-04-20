Newcomer Guide
==============

If you are new to AGILab, optimize for one outcome only: one successful local
run of the built-in ``flight_project`` from the web UI.

Do not start with cluster installs, private app repositories, notebook-first
flows, or packaging work. The first goal is not to explore every mode. The
first goal is one successful local proof from app selection to visible result.

This page gives the shortest mental model for the framework. For the exact
installation commands, see :doc:`quick-start`. If the first proof fails, use
:doc:`newcomer-troubleshooting` before branching into broader troubleshooting.

Shortest first proof
--------------------

This proof does **not** require ``PIPELINE``. ``PIPELINE`` becomes important
later, after the first local path is already working.

Do this in order:

1. Install and launch AGILab with the commands from :doc:`quick-start`.
2. In the web UI, go to ``PROJECT`` and choose
   ``src/agilab/apps/builtin/flight_project``.
3. Go to ``ORCHESTRATE`` and click ``INSTALL``, then ``EXECUTE``.
4. Go to ``ANALYSIS`` and open the default view.

You are done when:

- fresh output exists under ``~/log/execute/flight/``
- the default ``ANALYSIS`` view opens for ``flight_project``

Only after that should you try notebooks, cluster mode, private apps, or
packaged install.

What success looks like
-----------------------

You are "past the newcomer hurdle" when all of the following are true:

- A local install/run completes without needing SSH or remote workers.
- AGILab writes logs and generated snippets under ``~/log/execute/<app>/``.
- You can do that either from the web UI or from a notebook using
  ``AgiEnv`` and ``AGI.run(...)``.

What to ignore on day 1
-----------------------

Skip these until the local ``flight_project`` proof works once:

- cluster and SSH setup
- published-package mode
- notebook-first route
- private or optional app repositories
- PyCharm or VS Code convenience flows

The first 10 minutes
--------------------

1. Install or launch AGILab with the commands from :doc:`quick-start`.
2. Keep the first run local. Skip SSH hosts and cluster settings.
3. Start with ``src/agilab/apps/builtin/flight_project``. Use
   ``mycode_project`` only later, when you intentionally want the smallest
   reference app instead of the clearest product demonstration.
4. Use the UI in this order:
   **PROJECT** -> **ORCHESTRATE** -> **ANALYSIS**.
5. Confirm that ``~/log/execute/flight/`` contains fresh output and the
   default analysis view opens.

That is enough for day 1. The fuller four-page demo story
(``PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS``) is a separate public tour
based on ``uav_relay_queue_project``, not the newcomer proof.

If that path fails at any point, stop and use :doc:`newcomer-troubleshooting`
instead of jumping directly into cluster, packaging, or general FAQ material.

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

Only after the first proof
--------------------------

Branch into these routes only after the local ``flight_project`` path works:

- :doc:`notebook-quickstart` if you prefer to stay in Jupyter
- published package mode if you want the thinnest install path
- :doc:`distributed-workers` when you are ready for SSH or multi-node execution
- developer convenience flows such as PyCharm run configurations or VS Code tasks

Where to go next
----------------

- :doc:`quick-start` for the shortest install/run commands.
- :doc:`newcomer-troubleshooting` for the five most common first-run failures.
- :doc:`compatibility-matrix` for the current public validated-vs-documented
  support slices.
- :doc:`notebook-quickstart` for the code-first notebook route.
- :doc:`architecture` for the runtime control path.
- :doc:`execute-help` for the ORCHESTRATE workflow.
- :doc:`distributed-workers` after the local path works and you are ready for
  SSH or multi-node execution.
