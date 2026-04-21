agi-core Demo
=============

Use this page only when you intentionally want the notebook path first.

If you want the main AGILAB product path first, use :doc:`quick-start` and run
the built-in ``flight_project`` from the web UI. This notebook path is for
Python users who prefer ``AgiEnv`` and ``AGI.run(...)`` before the UI.

Recommended notebook launchers
------------------------------

.. image:: https://colab.research.google.com/assets/colab-badge.svg
   :target: https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_first_run_source.ipynb
   :alt: Open In Colab

.. image:: https://kaggle.com/static/images/open-in-kaggle.svg
   :target: https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run_source.ipynb
   :alt: Open In Kaggle

- Colab source route:
  `Open First Run In Colab <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_first_run_source.ipynb>`_
- Kaggle source route:
  `Open First Run In Kaggle <https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run_source.ipynb>`_

Both launchers clone the repository, prepare an isolated runtime venv, and run
the built-in MyCode example app (internal id ``mycode_project``) without
mutating the base notebook kernel packages.

Kaggle note: enable Internet in the notebook settings for the first install.

Other notebook entry points
---------------------------

- `Benchmark <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_benchmark_source.ipynb>`_
  benchmarks the built-in MyCode example app across the default AGILAB mode
  sweep and renders a ranked comparison table.
- `Data + DAG <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_data_dag.ipynb>`_
  is the advanced source notebook for a data-worker app and a DAG-style app.
- `Worker Paths <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_worker_paths.ipynb>`_
  is the advanced source notebook for worker-class and source-path inspection.

Published-package variants
--------------------------

Use these only when you explicitly want the current PyPI release instead of
GitHub ``main``.

- `First Run (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_first_run.ipynb>`_
  prepares an isolated runtime venv under ``/content`` and keeps the base
  Colab kernel packages unchanged.
- `First Run (PyPI, Kaggle) <https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb>`_
  prepares an isolated runtime venv under ``/kaggle/working`` and keeps the
  base Kaggle kernel packages unchanged.
  Kaggle note: enable Internet in the notebook settings for the first install.
- `Benchmark (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_benchmark.ipynb>`_
  prepares an isolated runtime venv under ``/content`` and keeps the base
  Colab kernel packages unchanged.
- `Data + DAG (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_data_dag_pypi.ipynb>`_
- `Worker Paths (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_worker_paths_pypi.ipynb>`_

Repository launch flow
----------------------

From the AGILab repository root:

.. code-block:: bash

   git clone https://github.com/ThalesGroup/agilab.git
   cd agilab
   ./install.sh --install-apps
   uv run --with jupyterlab jupyter lab examples/notebook_quickstart/agi_core_first_run.ipynb

The notebook file lives in the repository at
``examples/notebook_quickstart/agi_core_first_run.ipynb``.

Minimal notebook cells
----------------------

Cell 1: resolve the repository and built-in apps path.

.. code-block:: python

   from pathlib import Path

   def find_repo_root(start: Path) -> Path:
       for candidate in (start, *start.parents):
           if (candidate / "pyproject.toml").is_file() and (candidate / "src/agilab/apps/builtin").is_dir():
               return candidate
       raise RuntimeError(
           "Launch this notebook from inside the AGILab repository, or edit REPO_ROOT manually."
       )

   REPO_ROOT = find_repo_root(Path.cwd().resolve())
   APPS_PATH = REPO_ROOT / "src/agilab/apps/builtin"
   APP = "mycode_project"  # built-in MyCode example app

Cell 2: build ``AgiEnv`` and run the smallest local ``AGI.run(...)`` shape.

.. code-block:: python

   from agi_cluster.agi_distributor import AGI
   from agi_env import AgiEnv

   app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)
   result = await AGI.run(
       app_env,
       scheduler="127.0.0.1",
       workers={"127.0.0.1": 1},
       mode=0,  # plain local Python execution
   )
   result

Cell 3: inspect the run artifacts.

.. code-block:: python

   log_root = Path.home() / "log" / "execute" / "mycode"
   print(log_root)

How this maps back to the web UI
--------------------------------

- Notebook ``AgiEnv(apps_path=..., app="mycode_project")`` corresponds to
  choosing the built-in MyCode example app in **PROJECT**.
- Notebook ``AGI.run(...)`` corresponds to the generated snippet from
  **ORCHESTRATE**.
- The output path under ``~/log/execute/mycode`` is the same family of artifacts
  the UI writes and reuses.
- You only need to move to **PIPELINE** when you want saved, repeatable steps
  instead of ad hoc cells.

Related pages
-------------

- :doc:`quick-start` for the main AGILAB onboarding path.
- :doc:`newcomer-guide` for the overall onboarding strategy.
- :doc:`distributed-workers` once the local path works and you want to add
  scheduler and worker hosts.
