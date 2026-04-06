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

Median results from a local run on macOS / Python ``3.13.9`` with ``16`` partitions,
``100000`` rows per file, and ``32`` compute passes:

+----------------------------+-------------------+-----------+----------+-----------+-----------+-----------+
| App                        | Worker path       | Mode      | 1 worker | 2 workers | 4 workers | 8 workers |
+============================+===================+===========+==========+===========+===========+===========+
| execution_pandas_project   | pandas / process  | mono      | 1.738    | 1.480     | 1.487     | 1.485     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+-----------+
| execution_pandas_project   | pandas / process  | parallel  | 7.613    | 4.731     | 3.346     | 2.518     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+-----------+
| execution_polars_project   | polars / threads  | mono      | 1.789    | 1.539     | 1.568     | 1.579     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+-----------+
| execution_polars_project   | polars / threads  | parallel  | 1.789    | 1.561     | 1.563     | 1.582     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+-----------+

These numbers are intentionally useful, even though they are not flattering to
every path:

- the pandas process-based path now shows a clear worker-count effect on the same workload: ``7.613s`` at ``1`` worker, ``4.731s`` at ``2``, ``3.346s`` at ``4``, and ``2.518s`` at ``8`` in parallel mode
- the polars threaded path stays close to its steady-state result across ``1``, ``2``, ``4``, and ``8`` workers on the same workload
- AGILAB therefore shows both *execution model* and *worker-count scaling* on the same reproducible workload

Raw benchmark artifacts are versioned under:

- ``docs/source/data/execution_playground_benchmark.json``

2-node 16-mode matrix
---------------------

The repository also ships a second helper that benchmarks the full 16-mode
matrix on 2 Macs over SSH:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/benchmark_execution_mode_matrix.py --remote-host <remote-macos-ip> --scheduler-host <local-macos-ip> --rows-per-file 100000 --compute-passes 32 --n-partitions 16 --repeats 2

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

On these 2 Macs, the ``r...`` and ``rd...`` modes are still **CPU-only**
because neither node exposes NVIDIA tooling. They are benchmarked anyway so the
matrix stays complete and the mode semantics remain visible.

.. rubric:: execution_pandas_project

.. csv-table:: 16-mode matrix for ``execution_pandas_project``
   :file: data/execution_pandas_project_mode_matrix.csv
   :header-rows: 1
   :widths: 8, 28, 28, 12

.. rubric:: execution_polars_project

.. csv-table:: 16-mode matrix for ``execution_polars_project``
   :file: data/execution_polars_project_mode_matrix.csv
   :header-rows: 1
   :widths: 8, 28, 28, 12

.. rubric:: What the matrix adds

This second benchmark makes three extra points visible:

- the best mode is not necessarily the same for the two worker designs
- a 2-node Dask topology can win for one execution model and not for another
- requesting RAPIDS on hardware without NVIDIA tooling does not create a fake speedup: AGILAB still reports the run honestly as CPU-only

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
