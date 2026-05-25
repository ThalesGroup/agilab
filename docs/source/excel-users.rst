AGILAB for Excel users
======================

Excel users do not need a cluster pitch first. The useful first question is
smaller:

   Can I keep Excel as the familiar workbook interface, run a reproducible
   analysis outside the spreadsheet, and get a workbook plus evidence back?

AGILAB's current answer is a lightweight bridge: workbook-shaped input,
refresh-friendly CSV output, and explicit evidence. This is not a full Office
add-in and it is not yet arbitrary workbook import from the web UI.

What ships now
--------------

The packaged ``excel_workbook_proof`` preview creates an Excel-shaped proof
without adding Excel-specific dependencies:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python src/agilab/examples/excel_workbook_proof/preview_excel_workbook_proof.py

It writes:

.. code-block:: text

   ~/log/execute/excel_workbook_proof/input_sales_workbook.xlsx
   ~/log/execute/excel_workbook_proof/sales_proof_workbook.xlsx
   ~/log/execute/excel_workbook_proof/agilab_evidence.json
   ~/log/execute/excel_workbook_proof/power_query_refresh/sales_input.csv
   ~/log/execute/excel_workbook_proof/power_query_refresh/sales_summary.csv

Open ``sales_proof_workbook.xlsx`` in Excel and inspect the ``AGILAB Evidence``
sheet. The JSON evidence records artifact hashes and keeps the adoption
boundary explicit.

Why this is the right first bridge
----------------------------------

Excel analysts already understand workbooks, sheets, tables, refreshes, and
folder-based data handoff. AGILAB should meet that workflow before asking them
to think about workers, DAGs, Cython, or clusters.

The bridge keeps the responsibilities clear:

.. list-table::
   :header-rows: 1

   * - User concern
     - AGILAB response
   * - I want a workbook I can open.
     - Produce ``sales_proof_workbook.xlsx`` with result and evidence sheets.
   * - I want refreshable data.
     - Write stable CSV outputs under ``power_query_refresh/``.
   * - I need to know what changed.
     - Record SHA-256 hashes in ``agilab_evidence.json``.
   * - I do not want an Office deployment project.
     - Use files and folders first; keep add-ins as a later option.

Product direction
-----------------

The next product step is a focused command and UI path:

.. code-block:: bash

   agilab excel-proof --workbook sales.xlsx --sheet Sales --out sales_proof.xlsx

That should:

- read a user-selected workbook sheet or table;
- run a local AGILAB proof;
- write a result workbook with an ``AGILAB Evidence`` sheet;
- write Power Query-friendly CSV or parquet outputs;
- keep a JSON evidence bundle with hashes, inputs, run metadata, and limits.

What remains roadmap
--------------------

The preview does not yet claim:

- arbitrary ``.xlsx`` upload/import in the AGILAB web UI;
- formula preservation for existing customer workbooks;
- Excel macro or ``.xlsm`` execution;
- an Excel ribbon/task-pane add-in;
- Microsoft 365 tenant deployment.

Those are useful later only if workbook import/export proves that Excel users
care about the bridge. For now, the adoption message should stay simple:

   Keep Excel as the interface. Use AGILAB to make the analysis reproducible,
   auditable, and replayable.
