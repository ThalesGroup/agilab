PIPELINE
===========

.. toctree::
   :hidden:

Page snapshot
-------------

.. figure:: _static/page-shots/pipeline-page.png
   :alt: Screenshot of the PIPELINE page with assistant controls, lab directory selectors, and MLflow status.
   :align: center
   :class: diagram-panel diagram-wide

   PIPELINE combines lab-step editing, execution context, and MLflow tracking status in the same workspace.

What you should read from this screenshot
----------------------------------------

The image is designed as one operational loop:

1. **Project context selector (left side of sidebar)**: picks ``AGILAB_EXPORT_ABS/<module>`` and determines where ``lab_steps.toml`` and artifacts are loaded.
2. **Execution controls (center panel)**: open the assistant tab, edit snippets, and run one step or full pipeline.
3. **Run feedback (right area)**: MLflow status and output area indicate whether execution was accepted by the engine.
4. **History path (lower main panel)**: verify the persisted step file state and refresh if needed before resuming work.

Suggested read-through for this screenshot:

1. Pick the target module and step file in the sidebar.
2. Run a small step from the assistant.
3. Check output/MLflow status area immediately after execution.
4. Open ``HISTORY`` if the step count feels inconsistent and re-sync the conversation.

Sidebar
-------
- ``Read Documentation`` opens this guide in the hosted public docs, and
  ``Open Local Documentation`` uses the locally generated docs build when
  available.
- ``Lab Directory``: choose the module whose lab artefacts you want to work on.
  The selection points at ``${AGILAB_EXPORT_ABS}/<module>`` and initialises
  ``lab_steps.toml`` if it does not exist yet.
- ``Steps``: pick the ``lab_steps`` file relative to the export directory. When
  you change the selection the assistant reloads the stored conversation.
- ``DataFrame``: select which CSV (or parquet) is mounted for the assistant. The
  resolved absolute path lives under ``${AGILAB_EXPORT_ABS}``.
- ``Import Notebook``: upload an ``.ipynb`` file to seed the conversation when
  working offline.
- ``MLflow``: shows whether the local tracking UI is running and exposes an
  ``Open UI`` link. The UI is a tracker view, not another execution button.

Main Content Area
-----------------

ASSISTANT
~~~~~~~~~
Each lab is organised as a sequence of steps stored in ``lab_steps.toml``.
The numbered buttons at the top let you jump between them. Ask questions or
describe transformations in the text area—AGILab forwards the prompt to the
Responses API together with the selected DataFrame metadata. The code editor
reacts to the toolbar actions:

* ``Save`` keeps the snippet as-is in the current step.
* ``Next`` persists the snippet and advances to a fresh step.
* ``Remove`` deletes the step from ``lab_steps.toml``.
* ``Run`` writes the snippet to ``lab_snippet.py``, executes it and stores any
  produced dataframe under ``lab_out.csv`` so the preview and the
  Orchestrate/Analysis pages can consume the result.

The runtime is chosen from the *Execution environment* box below the editor.
If you pick a concrete virtual environment path the snippet runs via
``run_agi`` inside that environment (the path is kept with the step under
the ``E`` field). Leaving the selector on the default AGILab environment
falls back to ``run_lab``, reusing the managed runtime that ships with the
app. In both cases the exported dataframe and history behave identically.

The assistant automatically reloads the most recent dataframe and shows it below
the editor. If nothing has been saved yet, you will see a reminder to run a
snippet first.

When your lab step is based on app execution, use the **Pipeline** add flow:

- Generate the target snippet in **ORCHESTRATE** (typically ``AGI.run``).
- In **Add step** (or **New step** on an empty project), choose ``Step source =``
  ``gen step`` to regenerate from prompt, or select an existing exported snippet
  to import it directly.
- Imported snippets are marked read-only and run with the project manager runtime.

If you change values in Orchestrate arguments, regenerate or re-import the
snippet in Pipeline before running the step.

AGILab does not silently rewrite saved Python snippets when a lab is reopened.
If a generated step becomes stale after an app or orchestration change, the
saved code remains unchanged until you explicitly regenerate or replace it.
This avoids hidden behaviour changes, but it also means stale generated steps
must be refreshed deliberately.
One concrete example is ``sat_trajectory_project``: generated snippets now use
``total_satellites_wanted``, so older saved snippets using ``number_of_sat`` or
``number_of_tle_satellites`` must be regenerated before they can run.

MLflow tracking
~~~~~~~~~~~~~~~
Pipeline execution and MLflow tracking now share the same runtime contract:

.. figure:: diagrams/pipeline_mlflow_tracking.svg
   :alt: Diagram showing one parent MLflow run for the whole pipeline and one nested run per executed step.
   :align: center
   :class: diagram-panel diagram-standard

   PIPELINE creates one parent MLflow run per execution, then one nested run per step, while both in-process and subprocess paths write to the same tracking store exposed by the MLflow UI.

* ``Run pipeline`` creates one parent MLflow run for the whole lab execution.
* Every executed step becomes a nested MLflow run with its own metadata.
* The tracked metadata comes from ``lab_steps.toml`` and includes the step
  description, prompt/question, selected model, execution engine, and runtime.
* Captured stdout, the executed snippet, the run log, and produced dataframe
  artefacts are logged to the same tracking store when they exist.

This means MLflow is no longer just a nearby dashboard. It is the execution
trace for PIPELINE runs, while the sidebar remains the place where you inspect
that trace.

The tracking store is the directory configured by ``MLFLOW_TRACKING_DIR``.
Subprocess-based steps receive the same ``MLFLOW_TRACKING_URI`` as in-process
steps, so both execution paths are visible from the same MLflow UI.

HISTORY
~~~~~~~
Inspect or tweak the raw ``lab_steps.toml`` via the code editor. Saving the
file here immediately refreshes the assistant tab.

Troubleshooting and checks
--------------------------

Use these checks if Pipeline steps are confusing or fail to execute:

- If numbered step buttons do not match ``lab_steps.toml``, open **HISTORY** and
  confirm the selected file is the current module's lab file.
- If execution fails on a stale path, regenerate or re-import the snippet in
  PIPELINE before rerunning the step.
- If ``Run`` writes no dataframe, check the destination under
  ``${AGILAB_EXPORT_ABS}/<module>/lab_out.csv`` and ensure ``Write permissions``
  are enabled for the selected execution environment.
- If an imported notebook is not loaded, re-upload ``.ipynb`` and then reopen the
  step editor to force a refresh.
- If MLflow stays empty after a run, confirm that the step completed and that
  the tracking store under ``MLFLOW_TRACKING_DIR`` is writable.
- If MLflow link fails to open, verify ``activate_mlflow`` completed and port
  forwarding is not blocked locally.

See also
--------

- :doc:`agilab-help` for the overall page sequence.
- :doc:`execute-help` for generating reliable snippets before running a step.
- :doc:`apps-pages` for analysis-side visualisations after a successful run.
- :doc:`roadmap/versioned-pipeline-steps` for the proposed structured successor
  to raw generated snippets in ``lab_steps.toml``.
