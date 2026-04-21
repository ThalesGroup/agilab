Quick-Start
===========

If you are new to AGILab, do one thing first: run the built-in
``flight_project`` locally from the web UI.

That first proof is:

- source checkout
- local install
- web UI
- ``PROJECT`` -> choose ``flight_project``
- ``ORCHESTRATE`` -> ``INSTALL`` then ``EXECUTE``
- ``ANALYSIS`` -> open the default view

If that works once, then branch into notebooks, cluster mode, or package mode.
If it fails, use :doc:`newcomer-troubleshooting`.

This first proof is deliberately narrower than the public four-page tour. It
proves the safest local path first; it does not try to prove ``PIPELINE`` on
day 1.

For architectural context, see :doc:`architecture` and
:doc:`agi-core-architecture`.

Prerequisites
-------------

- Python 3.11+ with `uv <https://docs.astral.sh/uv/>`_ installed
  (``curl -LsSf https://astral.sh/uv/install.sh | sh``).
- macOS or Linux shell (use WSL2 on Windows until native support lands).
- If you plan to explore remote workers later, keep SSH access for that later
  step; it is not needed for the first proof path.

Recommended first proof path
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use this path exactly once before trying anything broader:

1. **Clone the repository and install the built-in apps**::

       git clone https://github.com/ThalesGroup/agilab.git
       cd agilab
       ./install.sh --install-apps --test-apps

2. **Launch the web interface**::

       uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py

3. **Keep the first run local and use the built-in flight demo**

   In the UI, use:

   - ``PROJECT`` -> select ``src/agilab/apps/builtin/flight_project``
   - ``ORCHESTRATE`` -> click ``INSTALL``, then ``EXECUTE``
   - ``ANALYSIS`` -> open the default built-in view

4. **Check the first proof outcome**

   You are past the newcomer hurdle when both are true:

   - fresh output exists under ``~/log/execute/flight/``
   - you can open the default ``ANALYSIS`` view for ``flight_project``

5. **Only after that, branch into alternative paths**

   Do not switch to packaged install, notebook-first, or cluster setup before
   this local proof works once from end to end.

   If you want the full public four-page story after that, use the
   ``uav_relay_queue_project`` demo path documented in :doc:`demos`.

If the first proof fails
^^^^^^^^^^^^^^^^^^^^^^^^

Do not broaden the problem immediately. Stay on the built-in local path and run
the explicit newcomer proof first::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py

If you also want the built-in app installer and seeded helper scripts checked in
the same run::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-install

Then use :doc:`newcomer-troubleshooting` for the five common first-run failures:

- missing ``uv``
- installer failure
- built-in app path not found
- About / ORCHESTRATE startup failure
- no fresh output under ``~/log/execute/flight/``

If you want the current public support picture before branching into other
routes, use :doc:`compatibility-matrix`. It makes the current validated slices
explicit and separates them from routes that are documented but not the
recommended newcomer proof.

Alternative install routes
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use these only if you already know why you want them.

.. _lightning-studio-ui-demo:

**Lightning Studio route** (browser-hosted single-machine UI demo)::

    git clone https://github.com/ThalesGroup/agilab.git
    cd agilab
    uv sync
    uv --preview-features extra-build-dependencies run python tools/lightning_studio_demo.py --port 8501

Then use the Lightning Studio UI to open the web app on port ``8501``.

This route keeps AGILAB in a local-only demo mode, starts on
``flight_project``, and redirects logs, exports, and local share data into
``.lightning_studio_runtime/`` under the repository root. It is a useful UI
demo path, but it is not the full remote-cluster/orchestration product path.

Lightning docs that support this workflow:

- `Run single or multi-node on Lightning Studios <https://lightning.ai/docs/pytorch/latest/clouds/lightning_ai.html>`_
- `How to Build a Machine Learning Training and Deployment Pipeline <https://lightning.ai/pages/community/tutorial/ml-training-deployment/>`_

**Published package route** (fastest install, less representative of the full product path)::

    mkdir ~/agi-workspace && cd ~/agi-workspace
    uv venv
    source .venv/bin/activate
    uv pip install agilab
    uv run agilab

**Notebook-first route** (best if you intentionally want ``agi-core`` before the UI)::

    git clone https://github.com/ThalesGroup/agilab.git
    cd agilab
    ./install.sh --install-apps --test-apps
    uv run --with jupyterlab jupyter lab examples/notebook_quickstart/agi_core_first_run.ipynb

Private apps or framework contributor setup
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Only do this after the public built-in proof path is working.

Before working on private apps that depend on the public AGILab framework,
initialise the pinned submodule::

    git submodule update --init --recursive

Run without PyCharm (CLI wrappers)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you work from a repository checkout and do not use PyCharm, run the
pre-generated wrappers under ``tools/run_configs`` directly from a shell.
They mirror the bundled run configurations for built-in/public apps.

List available wrappers::

    find tools/run_configs -type f -name "*.sh" | sort

Examples::

    bash tools/run_configs/agilab/agilab-run-dev.sh
    bash tools/run_configs/apps/builtin-flight-run.sh
    bash tools/run_configs/apps/builtin-flight-test-worker.sh

Optional developer workflow
^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you work from a repository checkout, PyCharm and Codex CLI can speed up
iteration, but they are not required to install or run AGILab.

- PyCharm Professional can reuse the bundled run configurations.
- Codex CLI can follow the repository guidance in ``AGENTS.md`` and
  ``.codex/skills``.
- A minimal shell-only workflow remains available through
  ``tools/run_configs``.

Codex workflow
^^^^^^^^^^^^^^

From this repository, use the shared workflow helper:

- ``./tools/codex_workflow.sh review`` before larger edits
- ``./tools/codex_workflow.sh exec "short change request"``
- ``./tools/codex_workflow.sh apply <task-id>``

The helper resolves ``.external/agilab/tools/codex_workflow.sh`` first, then
falls back to a sibling ``../agilab`` checkout only if you explicitly use the
legacy layout.

Cluster installs
^^^^^^^^^^^^^^^^

If you want to install on a cluster, the installer must have SSH key access or
credentials with permission to deploy workers. See :doc:`cluster` for the full
workflow. ``pycharm/setup_pycharm.py`` mirrors web interface run configurations to
``~/log/execute/<app>/AGI_*.py`` so that IDE and CLI stay in sync.

.. note::

   On a virgin workspace you do not need to hand-create
   ``~/log/execute/<app>`` snippets. The installer dispatcher
   (``src/agilab/apps/install.py``) calls ``_seed_example_scripts`` before
   kicking off AGI, copying each ``AGI_*.py`` helper from
   ``src/agilab/examples/<app>/`` into ``~/log/execute/<app>/`` so the first
   install has runnable mirrors. After that initial bootstrap, the web interface
   ORCHESTRATE page re-generates the snippets on demand according to the form
   inputs you provide, keeping IDE and CLI flows in sync. Field defaults are
   read from each app's per-user workspace copy
   ``~/.agilab/apps/<app>/app_settings.toml`` before the form renders. That
   workspace file is seeded from the versioned ``app_settings.toml`` source file
   (for example ``<project>/app_settings.toml`` or ``<project>/src/app_settings.toml``)
   on first use, so update the workspace copy when you need local baselines and
   update the source seed only when you intend to change the shipped defaults.

Next steps
^^^^^^^^^^

- :doc:`architecture` – understand how the web interface, ``agi_core``, ``agi_env`` and
  ``agi_cluster`` fit together.
- :doc:`directory-structure` – explore the repository layout with an annotated
  tree tracked in the repo and refreshed when ``docs/source/directory-structure.txt`` is updated.
- :doc:`agilab-help` – learn how core pages and optional page bundles fit
  together in the UI.
- :doc:`apps-pages` – learn how page bundles are discovered, enabled, and launched.

Support
^^^^^^^

Support: open an issue on GitHub

License
^^^^^^^

New BSD. See :doc:`License File <license>`.
