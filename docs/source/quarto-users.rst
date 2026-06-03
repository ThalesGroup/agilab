AGILAB for Quarto Users
=======================

AGILAB can export a run manifest into a Quarto report. Use AGILAB to execute the
experiment and collect evidence, then use Quarto to publish the proof.

Export a report
---------------

After an AGILAB run writes a ``run_manifest.json``, create a ``.qmd`` report:

.. code-block:: bash

   agilab export quarto \
     --run ~/log/execute/flight_telemetry/latest/run_manifest.json \
     --output report.qmd

The generated report contains the run summary, command, environment, validations,
artifact paths, artifact hashes, and derived metrics from the manifest.

Render when Quarto is available
-------------------------------

To ask AGILAB to call Quarto after writing the report:

.. code-block:: bash

   agilab run quarto \
     --run ~/log/execute/flight_telemetry/latest/run_manifest.json \
     --output report.qmd

If ``quarto`` is not installed, AGILAB still writes the ``.qmd`` file and reports
the render step as skipped. To write only the ``.qmd`` file from the ``run``
command:

.. code-block:: bash

   agilab run quarto \
     --run run_manifest.json \
     --output report.qmd \
     --no-render

Bridge boundary
---------------

Quarto is the report layer. AGILAB remains the reproducible execution and
evidence engine. The bridge does not make AGILAB an R-native worker and does not
replace Quarto publishing workflows.

Related bridges
---------------

The same bridge command surface also exposes read-only and handoff integrations:

.. code-block:: bash

   agilab mcp serve --read-only
   agilab export hf-space --project my_project --output hf_space/ --force
   agilab export mlflow --run run_manifest.json --output mlflow_handoff.json
   agilab init vscode --root .
   agilab run notebook --notebook analysis.ipynb --output notebook-evidence/
   agilab run duckdb --query analysis.sql --output evidence/ --plan-only

For the detailed bridge strategy, see :doc:`roadmap/audience-bridges`.
