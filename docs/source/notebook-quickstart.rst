Notebook Quick Start
====================

This is the thinnest AGILab onboarding path for Python users who prefer a
notebook over the web UI. It uses ``agi-core`` directly through
``AgiEnv`` and ``AGI.run(...)`` and keeps the first run local.

Use this page when you want a first successful run with less UI surface area
and want to stay in a notebook while learning the runtime. It is a supported
local-first onboarding path for newcomers who prefer code over UI.

When this path helps
--------------------

- You already work comfortably in Jupyter.
- You want to understand the runtime from code first.
- You want a smaller mental model before learning PROJECT, ORCHESTRATE,
  PIPELINE, and ANALYSIS.

What this path does not cover
-----------------------------

- App selection through the AGILab sidebar.
- Generated snippets from ORCHESTRATE.
- Pipeline editing in the UI.
- Cluster or service-mode operations.

You can stay in notebook mode for your first local runs. Move to the web UI
later when you want the higher-level AGILAB workflow around the same API.

Colab launch flow
-----------------

The Colab notebooks are now split explicitly by install path.

Published-package notebooks
^^^^^^^^^^^^^^^^^^^^^^^^^^^

- `First Run <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_first_run.ipynb>`_
  installs AGILAB from PyPI and runs ``mycode_project``.
- `Benchmark <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_benchmark.ipynb>`_
  installs AGILAB from PyPI, benchmarks ``mycode_project`` across the default
  execution-mode sweep, renders a ranked comparison table, and writes the
  benchmark JSON artifact.
- `Data + DAG <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_data_dag_pypi.ipynb>`_
  installs AGILAB from PyPI and runs ``execution_pandas_project`` plus
  ``uav_relay_queue_project``.
- `Worker Paths <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_worker_paths_pypi.ipynb>`_
  installs AGILAB from PyPI and inspects packaged worker-class paths.

Source-checkout notebooks
^^^^^^^^^^^^^^^^^^^^^^^^^

- `First Run (source) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_first_run_source.ipynb>`_
  clones the repository, installs editable packages, and runs
  ``mycode_project``.
- `Benchmark (source) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_benchmark_source.ipynb>`_
  clones the repository, installs editable packages, and benchmarks
  ``mycode_project`` across the default execution-mode sweep.
- `Data + DAG (source) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_data_dag.ipynb>`_
  clones the repository, installs editable packages, and runs
  ``execution_pandas_project`` plus ``uav_relay_queue_project`` so you can see
  both a data-oriented workload and a pipeline-shaped workflow from the same
  notebook entry point.
- `Worker Paths (source) <https://colab.research.google.com/github/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_colab_worker_paths.ipynb>`_
  clones the repository, installs editable packages, resolves the worker path
  for ``execution_pandas_project``, ``flight_project``, and
  ``uav_relay_queue_project``, and prints the imported class lineage for
  ``ExecutionPandasWorker``, ``FlightWorker``, and the shared ``DagWorker``
  base class.

Repository launch flow
----------------------

From the AGILab repository root:

.. code-block:: bash

   git clone https://github.com/ThalesGroup/agilab.git
   cd agilab
   ./install.sh --install-apps --test-apps
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
   APP = "mycode_project"

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

How this maps back to the GUI
-----------------------------

- Notebook ``AgiEnv(apps_path=..., app="mycode_project")`` corresponds to
  choosing a project in **PROJECT**.
- Notebook ``AGI.run(...)`` corresponds to the generated snippet from
  **ORCHESTRATE**.
- The output path under ``~/log/execute/mycode`` is the same family of artifacts
  the UI writes and reuses.
- You only need to move to **PIPELINE** when you want saved, repeatable steps
  instead of ad hoc cells.

Optional next step
------------------

After one successful notebook run, you can keep working in notebooks or move to
the UI:

1. Open the AGILab web UI.
2. Select the same ``mycode_project`` app.
3. Recreate the run in **ORCHESTRATE** if you want to learn the UI vocabulary.

Related pages
-------------

- :doc:`newcomer-guide` for the overall onboarding strategy.
- :doc:`quick-start` for the standard package and source install paths.
- :doc:`distributed-workers` once the local path works and you want to add
  scheduler and worker hosts.
