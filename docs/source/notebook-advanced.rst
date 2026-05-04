Advanced Notebook Routes
========================

This page keeps the broader notebook matrix for advanced users who explicitly
want source-checkout launchers, benchmark notebooks, Data + DAG examples, or
worker-path inspection.

If you want the smallest newcomer notebook path, use :doc:`notebook-quickstart`
instead.

Source-checkout launchers
-------------------------

Use these when you intentionally want GitHub ``main`` instead of the current
published package.

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

Use these when you explicitly want the current PyPI release but still want the
broader notebook matrix rather than the newcomer quickstart.

- `First Run (PyPI, Colab) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_first_run.ipynb>`_
- `First Run (PyPI, Kaggle) <https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb>`_
- `Benchmark (PyPI) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_benchmark.ipynb>`_
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

If you also want local Ollama-backed models available in the same source
checkout, rerun the installer with the families you want::

   ./install.sh --install-apps --install-local-models gpt-oss,qwen3-coder,ministral,phi4-mini

Supported values are ``gpt-oss``, ``qwen``, ``deepseek``, ``qwen3``,
``qwen3-coder``, ``ministral``, and ``phi4-mini``.

The notebook file lives in the repository at
``examples/notebook_quickstart/agi_core_first_run.ipynb``.

Minimal source-checkout notebook cells
--------------------------------------

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

   from agi_cluster.agi_distributor import AGI, RunRequest
   from agi_env import AgiEnv

   app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)
   request = RunRequest(
       scheduler="127.0.0.1",
       workers={"127.0.0.1": 1},
       mode=AGI.PYTHON_MODE,
   )
   result = await AGI.run(app_env, request=request)
   result

Cell 3: inspect the run artifacts.

.. code-block:: python

   log_root = Path.home() / "log" / "execute" / "mycode"
   print(log_root)

Related pages
-------------

- :doc:`notebook-quickstart` for the newcomer PyPI-first notebook path.
- :doc:`quick-start` for the main AGILAB web UI onboarding path.
- :doc:`distributed-workers` once the local path works and you want to add
  scheduler and worker hosts.
