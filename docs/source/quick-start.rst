Quick-Start
===========

AGILab is a software solution to explore AI for engineering. This quick-start
walks you through the minimal steps required to install the framework, open the
web interface, and run one of the sample apps. For architectural context see
:doc:`architecture` and :doc:`agi-core-architecture`.

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

Install AGILab
^^^^^^^^^^^^^^

1. **Bootstrap a workspace** (keeps project files and the web interface cache in a
   single folder)::

       mkdir ~/agi-workspace && cd ~/agi-workspace

2. **Create a managed environment** (uv-first and source-agnostic)::

       uv venv
       source .venv/bin/activate

3. **Install AGILab (published wheel)**::

       uv pip install agilab

4. **Launch the web interface** (runs inside the managed virtual environment)::

       uv run agilab

The ORCHESTRATE page opens automatically. Point the sidebar to the folder that
contains your AGILab projects (for example a checked-out app repository, or a
path you set with ``APPS_PATH``).

5. **Run an example app**

   If you are working from a source checkout, run the sample from the local
   ``src/`` tree::

       cd /path/to/agilab-checkout
       uv run python src/agilab/examples/mycode/AGI_run_mycode.py

   The same project can be exercised from the web interface by selecting it in
   PROJECT, then using ORCHESTRATE and PIPELINE.

   This script constructs an ``AgiEnv``, bundles the worker, and executes a
   full AGI run so you can inspect the generated logs under
   ``~/log/execute/mycode``.

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
  tree tracked in the repo and refreshed by ``docs/gen-docs.py --refresh-generated``.
- :doc:`agilab-help` – learn how core pages and optional page bundles fit
  together in the UI.
- :doc:`apps-pages` – learn how page bundles are discovered, enabled, and launched.

Support
^^^^^^^

Support: open an issue on GitHub
