Execution Playground
====================

The built-in execution playground is the quickest way to show what AGILAB adds
on top of a plain dataframe benchmark.

Instead of only comparing libraries, AGILAB compares **execution models** on
the same workload and keeps the whole orchestration path visible.

What is included
----------------

Two built-in projects ship the same synthetic workload:

- ``execution_pandas_project``
- ``execution_polars_project``

They both read the same generated CSV dataset under
``execution_playground/dataset`` and produce grouped benchmark outputs.

The difference is the worker path:

- ``ExecutionPandasWorker`` extends ``PandasWorker``
- ``ExecutionPolarsWorker`` extends ``PolarsWorker``

That lets AGILAB expose not only timing differences, but also the execution
style behind them.

Where you see it in the UI
--------------------------

The two apps are run through the normal AGILAB pages. The benchmark value comes
from the fact that the same UI flow can drive two different worker families
without changing the orchestration path.

.. figure:: _static/page-shots/orchestrate-page.png
   :alt: ORCHESTRATE page showing install, execute, and benchmark controls
   :align: center
   :class: page-shot

   The benchmark appears in the normal PROJECT -> ORCHESTRATE flow rather than
   in a separate one-off demo script.

Why this example matters
------------------------

Many benchmark demos stop at:

- pandas vs polars
- local vs distributed
- Python vs compiled

AGILAB goes one step further:

- same workload
- same orchestration flow
- same benchmark UI
- different worker/runtime path

This makes it easier to answer the practical question:

**Did performance improve because of the library, or because of the execution model?**

What the benchmark shows
------------------------

For this example, the public message is intentionally simple:

- ``PandasWorker`` highlights a process-oriented worker path
- ``PolarsWorker`` highlights an in-process threaded worker path

The benchmark results in **ORCHESTRATE** then let you compare timings while the
rest of AGILAB still shows:

- install state
- distribution plan
- generated snippets
- exported outputs

Measured local benchmark
------------------------

The repository ships a reproducible benchmark helper:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/benchmark_execution_playground.py --repeats 3 --warmups 1 --worker-counts 1,2,4,8 --rows-per-file 100000 --compute-passes 32 --n-partitions 16

The helper now resolves its built-in app paths from the script location, so it
can be launched from any working directory inside or outside the repo root.

Median results from a local run on macOS / Python ``3.13.9`` with ``16`` partitions,
``100000`` rows per file, and ``32`` compute passes:

These numbers are intentionally useful because the heavier mixed workload
separates "more workers" from "better fit":

- the pandas process-oriented path is only slightly ahead in local ``parallel`` mode at ``1`` worker (``1.772s``), then gets worse as worker count rises (``2.157s`` at ``8`` workers)
- the polars threaded path improves at ``1-2`` workers (``1.520s``, ``1.436s``) and then converges back toward its steady state (``1.564s`` at ``8`` workers)
- AGILAB therefore shows both *execution model* and *worker-count scaling* on the same reproducible workload

Raw benchmark artifacts are versioned under:

- ``docs/source/data/execution_playground_benchmark.json``

2-node 16-mode matrix
---------------------

The repository also ships a second helper that benchmarks the full 16-mode
matrix on 2 Macs over SSH:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/benchmark_execution_mode_matrix.py --remote-host <remote-macos-ip> --scheduler-host <local-macos-ip> --rows-per-file 100000 --compute-passes 32 --n-partitions 16 --repeats 2

``--remote-host`` accepts either ``host`` or ``user@host``. If you pass only a
host or IP, the helper defaults to ``agi@<host>`` for both the SSH probe/setup
steps and the dataset ``rsync`` step.

This run uses:

- 1 local macOS ARM scheduler/worker
- 1 remote macOS ARM worker over SSH
- the same ``16`` partitions, ``100000`` rows per file, and ``32`` compute passes

Mode families
^^^^^^^^^^^^^

The 16 modes split into 4 families:

- ``0-3``: local CPU modes
- ``4-7``: 2-node Dask modes
- ``8-11``: local modes with the RAPIDS bit requested
- ``12-15``: 2-node Dask modes with the RAPIDS bit requested

The compact ``code`` column uses the order ``r d c p``:

- ``r`` = RAPIDS requested
- ``d`` = Dask / cluster topology
- ``c`` = Cython requested
- ``p`` = pool/process path requested

In the versioned benchmark artifacts shipped with the repository, the ``r...``
and ``rd...`` modes are still **CPU-only** because neither node exposed NVIDIA
tooling on that capture. The helper still reports RAPIDS requests explicitly,
and on other hardware it can mark local-only RAPIDS rows as GPU-accelerated
even if the remote node stays CPU-only.

How to read the matrix quickly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. Ignore rows ``8-15`` for performance interpretation in the versioned capture
   below: they keep the RAPIDS bit visible, but they are still CPU-only there.
2. Read the matrix by **families**, not by isolated rows:

   - local Python/Cython baseline: ``0-2``
   - local pool/process family: ``1-3``
   - 2-node Dask family: ``4-7``

3. Compare each family back to mode ``0`` (``____``) to see whether the
   execution model is buying you anything.

.. figure:: diagrams/execution_mode_families.svg
   :alt: Visual summary of execution mode families for execution_pandas_project and execution_polars_project
   :align: center
   :class: diagram-panel diagram-hero

   Compact map of the 16 execution modes grouped by topology and runtime family.

.. _execution-pandas-project:

execution_pandas_project
^^^^^^^^^^^^^^^^^^^^^^^^

Use this app when you want the benchmark to read as a process-oriented baseline.

- Worker family: ``ExecutionPandasWorker`` over ``PandasWorker``
- Story to tell: how far a process/pool/Dask path goes on the same workload
- What to inspect in AGILAB: install/distribution state in **ORCHESTRATE**, then
  the benchmark table and exported artifacts for the ``_d__`` family
- Practical reading: this app is the easiest way to show that "more workers"
  does not automatically beat the local path unless the execution model fits

.. csv-table:: 16-mode matrix for ``execution_pandas_project``
   :file: data/execution_pandas_project_mode_matrix.csv
   :header-rows: 1
   :widths: 8, 28, 28, 12

.. _execution-polars-project:

execution_polars_project
^^^^^^^^^^^^^^^^^^^^^^^^

Use this app when you want the benchmark to read as an in-process threaded path
with a different scaling profile.

- Worker family: ``ExecutionPolarsWorker`` over ``PolarsWorker``
- Story to tell: the same workload can prefer a lighter in-process path over a
  heavier process-oriented topology
- What to inspect in AGILAB: the same **ORCHESTRATE > Benchmark results** table,
  but with attention on the ``_d_p`` family and how it differs from the pandas app
- Practical reading: this app is the clearest proof that AGILAB is benchmarking
  execution models, not only dataframe libraries

.. csv-table:: 16-mode matrix for ``execution_polars_project``
   :file: data/execution_polars_project_mode_matrix.csv
   :header-rows: 1
   :widths: 8, 28, 28, 12

.. rubric:: What the matrix adds

This second benchmark makes three extra points visible:

- the heavier scalar tail now separates the plain local Python/Cython family, the local pool family, and the 2-node Dask family much more clearly
- the best mode is not the same for the two worker designs: ``_d__`` for ``execution_pandas_project`` and ``_d_p`` for ``execution_polars_project``
- a 2-node Dask topology can win for one execution model and not for another
- requesting RAPIDS on hardware without NVIDIA tooling does not create a fake speedup: AGILAB still reports the run honestly as CPU-only
- local-only RAPIDS rows and 2-node RAPIDS rows are reported independently, so GPU availability now follows the topology that actually ran

Raw matrix artifacts are versioned under:

- ``docs/source/data/execution_mode_matrix_benchmark.json``
- ``docs/source/data/execution_mode_matrix_benchmark.csv``
- ``docs/source/data/execution_pandas_project_mode_matrix.csv``
- ``docs/source/data/execution_polars_project_mode_matrix.csv``

How to run it
-------------

1. Launch AGILAB:

   .. code-block:: bash

      uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py

2. In **PROJECT**, select ``src/agilab/apps/builtin/execution_pandas_project``.
3. In **ORCHESTRATE**, run **INSTALL** once, then **EXECUTE**.
4. Enable **Benchmark all modes** when you want AGILAB to compare execution paths.
5. Repeat with ``src/agilab/apps/builtin/execution_polars_project``.
6. Compare the benchmark table in **ORCHESTRATE > Benchmark results** and the generated outputs.

What to look for
----------------

This example is useful when you want to demonstrate that AGILAB makes three
things explicit:

- the workload
- the orchestration path
- the execution model

That is why this example is a better public teaser than a raw benchmark chart:
it keeps the result, the runtime path, and the reproducible workflow together.
