Quick-Start
===========

If you are new to AGILab, do one thing first: run the built-in
``flight_project`` locally from the web UI.

That first proof is simple:
use a source checkout, install the built-in apps, launch the web UI, choose
``flight_project`` in ``PROJECT``, run ``INSTALL`` then ``EXECUTE`` in
``ORCHESTRATE``, and confirm a visible result in ``ANALYSIS``.

If that works once, then branch into notebooks, cluster mode, or package mode.
If it fails, use :doc:`newcomer-troubleshooting`.

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
       ./install.sh --install-apps

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

Use these only after the local ``flight_project`` proof works once.

.. _hosted-agilab-demo:
.. _lightning-studio-ui-demo:

**AGILAB demo** (browser-hosted single-machine UI demo)::

    git clone https://github.com/ThalesGroup/agilab.git
    cd agilab
    uv sync
    uv --preview-features extra-build-dependencies run python tools/lightning_studio_demo.py --port 8501

This launcher keeps AGILAB in local-only demo mode, starts on
``flight_project``, and writes demo runtime state into
``.lightning_studio_runtime/`` under the repository root.

Use it in one of two ways:

- self-host it on your own Linux VM and expose port ``8501`` behind Caddy or
  Nginx when viewers should not need any account
- run the same launcher in Lightning Studio when you want a managed operator
  environment; in that case only the operator needs a Lightning account

Lightning is optional. It is not required to install, run, or develop with
AGILAB.

**Published package route** (fastest install, less representative of the full product path)::

    mkdir ~/agi-workspace && cd ~/agi-workspace
    uv venv
    source .venv/bin/activate
    uv pip install agilab
    uv run agilab

**Notebook-first route** (best if you intentionally want ``agi-core`` before the UI)::

    git clone https://github.com/ThalesGroup/agilab.git
    cd agilab
    ./install.sh --install-apps
    uv run --with jupyterlab jupyter lab examples/notebook_quickstart/agi_core_first_run.ipynb

Private apps or framework contributor setup
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Only do this after the public built-in proof path is working.

Before working on private apps that depend on the public AGILab framework,
initialise the pinned submodule::

    git submodule update --init --recursive

Cluster installs
^^^^^^^^^^^^^^^^

If you want to install on a cluster, the installer must have SSH key access or
credentials with permission to deploy workers. See :doc:`cluster` for the full
workflow. ``pycharm/setup_pycharm.py`` mirrors web interface run configurations to
``~/log/execute/<app>/AGI_*.py`` so that IDE and CLI stay in sync.

Next steps
^^^^^^^^^^

- :doc:`newcomer-guide` for the mental model and what to ignore on day 1.
- :doc:`demos` for the public demo entry-point chooser.
- :doc:`architecture` for how the web UI, ``agi_core``, ``agi_env``, and
  ``agi_cluster`` fit together.
- :doc:`cluster` when you are intentionally moving from local proof to SSH or
  multi-node execution.

Support
^^^^^^^

Support: open an issue on GitHub

License
^^^^^^^

New BSD. See :doc:`License File <license>`.
