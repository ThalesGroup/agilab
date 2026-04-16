Quick-Start
===========

AGILab is an open-source platform for reproducible AI/ML workflows. For a
first-time visitor, the recommended proof path is simple: source checkout, web
UI, built-in ``flight_project``, local run, visible analysis. For architectural
context see :doc:`architecture` and :doc:`agi-core-architecture`.

If you are evaluating AGILab for the first time, read :doc:`newcomer-guide`
first. This page now treats the source checkout + ``flight_project`` workflow as
the recommended first proof path. Alternative install routes stay available
below.

If you want the thinnest code-first path without the web UI, see
:doc:`notebook-quickstart`. That is a supported newcomer path if you prefer to
stay in a notebook.

Prerequisites
-------------

- Python 3.11+ with `uv <https://docs.astral.sh/uv/>`_ installed
  (``curl -LsSf https://astral.sh/uv/install.sh | sh``).
- macOS or Linux shell (use WSL2 on Windows until native support lands).
- SSH key access to any remote cluster you intend to use.
- If you need to reuse Linux-dependent code paths, prefer macOS or Linux as your
  development environment.

Before working on private apps that depend on the public AGILab framework,
initialise the pinned submodule::

    git submodule update --init --recursive

Codex workflow
--------------

From this repository, use the shared workflow helper:

- ``./tools/codex_workflow.sh review`` before larger edits
- ``./tools/codex_workflow.sh exec "short change request"``
- ``./tools/codex_workflow.sh apply <task-id>``

The helper resolves ``.external/agilab/tools/codex_workflow.sh`` first, then
falls back to a sibling ``../agilab`` checkout only if you explicitly use the
legacy layout.

License
^^^^^^^

New BSD. See :doc:`License File <license>`.

Recommended first proof path
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use this path if you want to understand what AGILAB actually does:

1. **Clone the repository and install the built-in apps**::

       git clone https://github.com/ThalesGroup/agilab.git
       cd agilab
       ./install.sh --install-apps --test-apps

2. **Launch the web interface**::

       uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py

3. **Keep the first run local and use the built-in flight demo**

   In the UI, use:

   - ``PROJECT`` -> select ``src/agilab/apps/builtin/flight_project``
   - ``ORCHESTRATE`` -> run the install/distribute/run flow
   - ``PIPELINE`` -> inspect the generated step
   - ``ANALYSIS`` -> open the resulting built-in view

4. **Check the first proof outcome**

   You are past the newcomer hurdle when both are true:

   - fresh output exists under ``~/log/execute/flight/``
   - the workflow stayed understandable as ``PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS``

Alternative install routes
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use these only if you already know why you want them.

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
