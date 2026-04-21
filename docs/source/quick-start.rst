Quick-Start
===========

If you are new to AGILab, this page owns one thing only: the exact commands for
the recommended first proof.

That first proof is the built-in ``flight_project`` run locally from the web
UI. If it works once from end to end, then branch into notebooks, package mode,
or cluster mode. If it fails, use :doc:`newcomer-troubleshooting`.

Prerequisites
-------------

- Python 3.11+ with `uv <https://docs.astral.sh/uv/>`_ installed
  (``curl -LsSf https://astral.sh/uv/install.sh | sh``).
- macOS or Linux shell (use WSL2 on Windows until native support lands).
- If you plan to explore remote workers later, keep SSH access for that later
  step; it is not needed for the first proof path.

Recommended first proof path
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use this path exactly once before trying anything broader.

1. **Clone the repository and install the built-in apps**::

       git clone https://github.com/ThalesGroup/agilab.git
       cd agilab
       ./install.sh --install-apps

2. **Optional preflight check**::

       uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py

   Use this before launching the UI when you want an explicit source-checkout
   readiness check.

3. **Launch the web interface**::

       uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py

4. **Keep the first run local and use the built-in flight demo**

   In the UI, use:

   - ``PROJECT`` -> select ``src/agilab/apps/builtin/flight_project``
   - ``ORCHESTRATE`` -> click ``INSTALL``, then ``EXECUTE``
   - ``ANALYSIS`` -> open the default built-in view

5. **Check the first proof outcome**

   You are past the newcomer hurdle when both are true:

   - fresh output exists under ``~/log/execute/flight/``
   - you can open the default ``ANALYSIS`` view for ``flight_project``

6. **Only after that, branch into alternative paths**

   Do not switch to packaged install, notebook-first, or cluster setup before
   this local proof works once from end to end.

If the first proof fails
^^^^^^^^^^^^^^^^^^^^^^^^

Do not broaden the problem immediately. Stay on the built-in local path.
Use :doc:`newcomer-troubleshooting` first.

If you want the preflight to also check the built-in installer and seeded helper
scripts::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-install

The troubleshooting page covers the common first-run failures:

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

**AGILAB demo**:

.. image:: https://img.shields.io/badge/AGILAB-demo-0F766E?style=for-the-badge
   :target: mailto:focus@thalesgroup.com?subject=AGILAB%20demo%20request
   :alt: AGILAB demo

Request a guided demo at ``focus@thalesgroup.com``.

**Published package route** (fastest install, less representative of the full product path)::

    mkdir ~/agi-workspace && cd ~/agi-workspace
    uv venv
    source .venv/bin/activate
    uv pip install agilab
    uv run agilab

**agi-core demo**:

- Use :doc:`notebook-quickstart` when you intentionally want the notebook-first
  runtime path before the web UI.

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

- :doc:`demos` if you want browser-first entry points instead of the local
  first proof.
- :doc:`notebook-quickstart` if you intentionally want the ``agi-core``
  notebook path.
- :doc:`cluster` only after the local proof works and you are ready for SSH or
  multi-node execution.

Support
^^^^^^^

Support: open an issue on GitHub

License
^^^^^^^

New BSD. See :doc:`License File <license>`.
