agi-core Demo
=============

Use this page only when you intentionally want the notebook path first.

If you want the main AGILAB product path first, use :doc:`quick-start` and run
the built-in ``flight_telemetry_project`` from the web UI. This page is the smallest
published-package notebook route for the built-in MyCode example app.

Start here
----------

Use the Kaggle launcher first:

.. image:: https://kaggle.com/static/images/open-in-kaggle.svg
   :target: https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb
   :alt: Open In Kaggle

- `Open First Run In Kaggle <https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb>`_

This launcher installs the published AGILAB runtime packages into an isolated
Kaggle venv under ``/kaggle/working`` and runs the built-in MyCode example app
(``mycode_project``) without mutating the base notebook kernel packages.

Kaggle note: enable Internet in the notebook settings for the first install.

What will happen
----------------

The first notebook does only one thing:

- it prepares an isolated runtime environment from published packages
- it loads the built-in MyCode example app
- it runs one local ``AGI.run(...)`` call
- it shows you where the run artifacts were written

What success looks like
-----------------------

You are past the notebook newcomer hurdle when both are true:

- the notebook run finishes without error
- you can inspect fresh output under ``~/log/execute/mycode``

Local PyPI fallback
-------------------

If you want local Jupyter instead of Kaggle, use the published packages in a
clean environment:

.. code-block:: bash

   mkdir ~/agi-core-demo && cd ~/agi-core-demo
   uv venv
   source .venv/bin/activate
   uv pip install agilab
   uv run --with jupyterlab jupyter lab

Then use the minimal notebook cells below in a blank notebook.

Minimal notebook cells
----------------------

Cell 1: select the built-in MyCode example app.

.. literalinclude:: snippets/agi_core_mycode_minimal_app_env.py
   :language: python

Cell 2: run the smallest local ``AGI.run(...)`` shape.

.. literalinclude:: snippets/agi_core_mycode_minimal_run.py
   :language: python

Cell 3: inspect the run artifacts.

.. literalinclude:: snippets/agi_core_mycode_log_root.py
   :language: python

How this maps back to the web UI
--------------------------------

- Notebook ``AgiEnv(app=\"mycode_project\")`` corresponds to choosing the
  built-in MyCode example app in **PROJECT**.
- Notebook ``AGI.run(...)`` corresponds to the generated snippet from
  **ORCHESTRATE**.
- The output path under ``~/log/execute/mycode`` is the same family of artifacts
  the UI writes and reuses.

Advanced notebook routes
------------------------

If you want source-checkout launchers, benchmark notebooks, Data + DAG, worker
path inspection, or the source-checkout local notebook flow, use
:doc:`notebook-advanced`.

Related pages
-------------

- :doc:`quick-start` for the main AGILAB onboarding path.
- :doc:`newcomer-guide` for the overall onboarding strategy.
- :doc:`notebook-advanced` for source-checkout and advanced notebook routes.
- :doc:`distributed-workers` once the local path works and you want to add
  scheduler and worker hosts.
