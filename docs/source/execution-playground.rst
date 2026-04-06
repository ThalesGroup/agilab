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

   uv --preview-features extra-build-dependencies run python tools/benchmark_execution_playground.py --repeats 3 --warmups 1 --worker-counts 1,2,4

Median results from a local run on macOS / Python ``3.13.9``:

+----------------------------+-------------------+-----------+----------+-----------+-----------+
| App                        | Worker path       | Mode      | 1 worker | 2 workers | 4 workers |
+============================+===================+===========+==========+===========+===========+
| execution_pandas_project   | pandas / process  | mono      | 1.087    | 1.220     | 1.317     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+
| execution_pandas_project   | pandas / process  | parallel  | 4.146    | 2.795     | 2.241     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+
| execution_polars_project   | polars / threads  | mono      | 1.100    | 1.155     | 1.317     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+
| execution_polars_project   | polars / threads  | parallel  | 1.080    | 1.157     | 1.325     |
+----------------------------+-------------------+-----------+----------+-----------+-----------+

These numbers are intentionally useful, even though they are not flattering to
every path:

- the pandas process-based path improves when worker count rises from ``1`` to ``4``, but still pays heavy startup and IPC overhead on this workload
- the polars threaded path is already near its best result with ``1`` worker and does not improve when more workers are added here
- AGILAB therefore shows both *execution model* and *worker-count scaling* on the same reproducible workload

Raw benchmark artifacts are versioned under:

- ``docs/source/data/execution_playground_benchmark.json``

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
