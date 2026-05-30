Advanced Notebook Routes
========================

This page keeps the broader notebook matrix for advanced users who explicitly
want source-checkout launchers, benchmark notebooks, Data + DAG examples, or
worker-path inspection.

If you want the smallest newcomer notebook path, use :doc:`notebook-quickstart`
instead.

Notebook evidence sandbox
-------------------------

Use the notebook sandbox when you want AGILAB to execute a local ``.ipynb`` file
and collect notebook evidence without first turning it into a full app:

.. code-block:: bash

   agilab run notebook \
     --notebook analysis.ipynb \
     --params params.json \
     --output run/notebook-sandbox \
     --json

Install the optional runner dependencies with ``agilab[notebook]``. In a source
checkout, use ``uv run --extra notebook agilab run notebook ...``.

The sandbox writes:

- ``prepared_notebook.ipynb`` with an injected ``AGILAB_PARAMS`` cell,
- ``executed_notebook.ipynb`` after kernel execution,
- redacted ``stdout.log`` and ``stderr.log``,
- an ``artifacts/`` directory for notebook-created files,
- ``notebook_sandbox_evidence.json``,
- ``run_manifest.json`` for the normal AGILAB evidence path.

The injected cell exposes ``AGILAB_PARAMS``, ``AGILAB_PARAMS_PATH``, and
``AGILAB_ARTIFACT_DIR``. Keys in ``params.json`` that are valid Python
identifiers are also added as globals for concise notebook cells.

This is a reproducibility sandbox, not hostile-code isolation. Run trusted
notebooks locally, or add an external container/VM boundary before using
untrusted notebooks.

Source-checkout launchers
-------------------------

Use these when you intentionally want GitHub ``main`` instead of the current
published package.

.. image:: https://colab.research.google.com/assets/colab-badge.svg
   :target: https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_first_run_source.ipynb
   :alt: Open In Colab

.. image:: https://kaggle.com/static/images/open-in-kaggle.svg
   :target: https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run_source.ipynb
   :alt: Open In Kaggle

- Colab source route:
  `Open First Run In Colab <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_first_run_source.ipynb>`_
- Kaggle source route:
  `Open First Run In Kaggle <https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run_source.ipynb>`_

Both launchers clone the repository, prepare an isolated runtime venv, and run
the built-in Minimal App example app (internal id ``minimal_app_project``) without
mutating the base notebook kernel packages.

Kaggle note: enable Internet in the notebook settings for the first install.

Other notebook entry points
---------------------------

- `Benchmark <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_benchmark_source.ipynb>`_
  benchmarks the built-in Minimal App example app across the default AGILAB mode
  sweep and renders a ranked comparison table.
- `Data + DAG <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_data_dag.ipynb>`_
  is the advanced source notebook for a data-worker app and a DAG-style app.
- `Worker Paths <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_worker_paths.ipynb>`_
  is the advanced source notebook for worker-class and source-path inspection.

Published-package variants
--------------------------

Use these when you explicitly want the current PyPI release but still want the
broader notebook matrix rather than the newcomer quickstart.

- `First Run (PyPI, Colab) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_first_run.ipynb>`_
- `First Run (PyPI, Kaggle) <https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb>`_
- `Benchmark (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_benchmark.ipynb>`_
- `Data + DAG (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_data_dag_pypi.ipynb>`_
- `Worker Paths (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_colab_worker_paths_pypi.ipynb>`_

Repository launch flow
----------------------

From the AGILab repository root:

.. code-block:: bash

   CHECKOUT="${AGILAB_CHECKOUT:-$HOME/agilab-src}"
   git clone https://github.com/ThalesGroup/agilab.git "$CHECKOUT"
   cd "$CHECKOUT"
   ./install.sh --install-apps
   uv run --with jupyterlab jupyter lab src/agilab/examples/notebook_quickstart/agi_core_first_run.ipynb

If you also want local Ollama-backed models available in the same source
checkout, rerun the installer with the families you want::

   ./install.sh --install-apps --install-local-models gpt-oss,qwen3-coder,ministral,phi4-mini

Supported values are ``gpt-oss``, ``qwen``, ``deepseek``, ``qwen3``,
``qwen3-coder``, ``ministral``, and ``phi4-mini``. The first requested family
becomes the default WORKFLOW local assistant and is persisted in the AGILAB
environment file.

The notebook file lives in the repository at
``src/agilab/examples/notebook_quickstart/agi_core_first_run.ipynb``.

Minimal source-checkout notebook cells
--------------------------------------

Cell 1: create the built-in app environment and local request.

.. code-block:: python

   from agi_cluster.agi_distributor import AGI
   from agilab.notebook_demo import (
       notebook_app_env,
       notebook_local_request,
       notebook_log_root,
   )

   APP = "minimal_app_project"  # built-in Minimal App example app
   app_env = notebook_app_env(APP, verbose=1)
   request = notebook_local_request()
   print("App:", app_env.app)
   print("Log root:", notebook_log_root(app_env))

Cell 2: run the visible local ``AGI.run(...)`` shape.

.. code-block:: python

   result = await AGI.run(app_env, request=request)
   result

Cell 3: inspect the run artifacts.

.. code-block:: python

   log_root = notebook_log_root(app_env)
   print(log_root)

Related pages
-------------

- :doc:`notebook-quickstart` for the newcomer PyPI-first notebook path.
- :doc:`quick-start` for the main AGILAB web UI onboarding path.
- :doc:`distributed-workers` once the local path works and you want to add
  scheduler and worker hosts.
