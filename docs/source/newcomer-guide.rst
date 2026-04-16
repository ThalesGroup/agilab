Newcomer Guide
==============

If you are new to AGILab, optimize for one outcome: one successful local run of
a built-in app. Do not start with cluster installs, private app repositories,
or packaging work.

This page gives the shortest mental model for the framework. For the exact
installation commands, see :doc:`quick-start`.

What success looks like
-----------------------

You are "past the newcomer hurdle" when all of the following are true:

- A local install/run completes without needing SSH or remote workers.
- AGILab writes logs and generated snippets under ``~/log/execute/<app>/``.
- You can do that either from the web UI or from a notebook using
  ``AgiEnv`` and ``AGI.run(...)``.

Choose your path
----------------

Pick one path before you start, but do not treat them as equal:

- **Recommended first proof path**: clone the repository, use the web UI, and
  run the built-in ``flight_project`` locally.
- **Evaluate AGILab quickly**: use the published package in a fresh
  ``uv``-managed virtual environment.
- **Contribute or inspect the framework deeply**: use the source checkout and
  then branch into notebook, wrappers, or cluster flows after the first local
  proof works.

If you are unsure, choose the recommended ``flight_project`` path from
:doc:`quick-start`. Mixing the packaged install and a source checkout too early
is one of the easiest ways to confuse paths, environments, and generated
scripts.

Prefer code first?
------------------

If you already live in Jupyter, use :doc:`notebook-quickstart` for the fastest
local notebook-first route. This is a supported newcomer path, not just an
advanced API reference.

The first 10 minutes
--------------------

1. Install or launch AGILab with the commands from :doc:`quick-start`.
2. Keep the first run local. Skip SSH hosts and cluster settings.
3. Start with ``src/agilab/apps/builtin/flight_project`` as the default first
   proof path. Use ``mycode_project`` only if you explicitly want the smallest
   reference app instead of the clearest product demonstration.
4. Choose one first-run workflow:

   - **Notebook-first**: open :doc:`notebook-quickstart` and run the local
     ``AgiEnv`` + ``AGI.run(...)`` example from Jupyter.
   - **UI-first**: use the AGILAB UI in this order:
     **PROJECT** -> **ORCHESTRATE** -> **PIPELINE** -> **ANALYSIS**.

5. Confirm that ``~/log/execute/<app>/`` contains fresh output.

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

- :doc:`quick-start` for the shortest install/run commands.
- :doc:`notebook-quickstart` for the code-first notebook route.
- :doc:`architecture` for the runtime control path.
- :doc:`execute-help` for the ORCHESTRATE workflow.
- :doc:`distributed-workers` after the local path works and you are ready for
  SSH or multi-node execution.
