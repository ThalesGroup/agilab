WORKFLOW
===========

.. toctree::
   :hidden:

Page snapshot
-------------

.. figure:: _static/page-shots/workflow-page.png
   :alt: Screenshot of the WORKFLOW page with assistant controls, lab directory selectors, and dataframe selection.
   :align: center
   :class: diagram-panel diagram-wide

   WORKFLOW combines lab-stage editing, execution context, dataframe selection, and notebook export in the same workspace.

Sidebar
-------
- ``Read Documentation`` opens this guide in the hosted public docs when
  reachable, and falls back to the locally generated docs build when available.
- ``Lab Directory``: choose the module whose lab artefacts you want to work on.
  The selection points at ``${AGILAB_EXPORT_ABS}/<module>`` and initialises
  ``lab_stages.toml`` if it does not exist yet.
- ``Stages``: pick the ``lab_stages`` file relative to the export directory. When
  you change the selection the assistant reloads the stored conversation.
- ``DataFrame``: select which CSV (or parquet) is mounted for the assistant. The
  resolved absolute path lives under ``${AGILAB_EXPORT_ABS}``.
- ``MLflow``: shows whether the local tracking UI is running and exposes an
  ``Open UI`` link. The UI is a tracker view, not another execution button.

Main Content Area
-----------------

ASSISTANT
~~~~~~~~~
Each lab is organised as a sequence of stages stored in ``lab_stages.toml``.
The numbered buttons at the top let you jump between them. Ask questions or
describe transformations in the text area—AGILab forwards the prompt to the
Responses API together with the selected DataFrame metadata. The code editor
reacts to the toolbar actions:

* ``Save`` keeps the snippet as-is in the current stage.
* ``Next`` persists the snippet and advances to a fresh stage.
* ``Remove`` deletes the stage from ``lab_stages.toml``.
* ``Run`` writes the snippet to ``lab_snippet.py``, executes it and stores any
  produced dataframe under ``lab_out.csv`` so the preview and the
  Orchestrate/Analysis pages can consume the result.

The runtime is chosen from the *Execution environment* box below the editor.
If you pick a concrete virtual environment path the snippet runs via
``run_agi`` inside that environment (the path is kept with the stage under
the ``E`` field). Leaving the selector on the default AGILab environment
falls back to ``run_lab``, reusing the managed runtime that ships with the
app. In both cases the exported dataframe and history behave identically.

The assistant automatically reloads the most recent dataframe and shows it below
the editor. If nothing has been saved yet, you will see a reminder to run a
snippet first.

When your lab step is based on app execution, use the **WORKFLOW** add flow:

- Generate the target snippet in **ORCHESTRATE** (typically ``AGI.run``).
- In **Add stage** (or **New stage** on an empty project), choose ``Stage source =``
  ``Generate stage`` to regenerate from prompt, or select an existing exported snippet
  to import it directly.
- The default generation mode is **Safe actions**. The assistant returns a
  versioned JSON action contract, AGILAB validates it against the loaded
  dataframe schema, and the page saves deterministic pandas code derived from
  that contract.
- Use **Python snippet (advanced)** only when the transformation cannot be
  represented by the safe action registry and you intend to review the raw
  generated code yourself.
- Imported snippets are marked read-only and run with the project manager runtime.

If you change values in Orchestrate arguments, regenerate or re-import the
snippet in WORKFLOW before running the stage.

AGILab does not silently rewrite saved Python snippets when a lab is reopened.
If a generated stage becomes stale after an app or orchestration change, the
saved code remains unchanged until you explicitly regenerate or replace it.
This avoids hidden behaviour changes, but it also means stale generated stages
must be refreshed deliberately.
For example, if an app renames a runtime argument, older saved snippets that
still pass the removed name must be regenerated or replaced before they can run.

Workflow graph scopes
~~~~~~~~~~~~~~~~~~~~~
The **Workflow graph** expander is the transition path from a single-project
workflow to cross-app artifact orchestration. Use the ``Workflow scope``
selector to choose what the graph represents:

* ``Project workflow`` renders the current ``lab_stages.toml`` as a read-only
  compatibility graph. It explains stage order and dependencies, while the
  existing stage controls remain the source of truth for real single-project
  execution.
* ``Multi-app DAG`` loads or edits a cross-app artifact contract. This is the
  path for connecting app stages through explicit produced and consumed
  artifacts.

For ``Multi-app DAG`` scope, use the ``Workplan source`` selector to choose
where the plan comes from:

* ``App templates`` loads checked-in workflow templates bundled with the active
  app.
* ``Sample library`` loads checked-in public examples from
  ``docs/source/data/multi_app_dag*.json``.
* ``Workspace drafts`` loads plans saved from the current project workspace
  under ``.agilab/global_dags``.
* ``Custom path`` loads an external JSON plan by path.

The graph is hidden by default so small screens stay readable. Enable
``Show graph`` only when the current screen has enough room. Enable
``Show technical output details`` when you need the lower-level output handoff
table behind the plan.

To edit a plan, enable ``Edit plan``. The normal editing path stays away from
raw JSON:

* ``Steps`` chooses the app-level steps in the plan.
* ``Creates`` chooses the outputs produced by those steps.
* ``Uses`` chooses which later steps use earlier outputs.
* ``Check plan`` validates the schema, app names, inputs, and outputs.
* ``Save as workspace plan`` stores the draft for the current project.
* ``Show generated JSON`` is available for review or export, but it is not the
  primary editing flow.

Execution is intentionally conservative:

* ``Preview next ready step`` is a preview action. It updates the persisted
  runner state without claiming that an app really ran.
* ``Run next stage`` is only available for checked-in workflow templates with a
  controlled execution marker. AGILAB ships controlled examples, and app-owned
  executable templates saved under an app's ``dag_templates`` directory can use
  the generic controlled contract adapter.
* ``Run ready stages`` executes every currently runnable controlled stage in
  one batch. Independent branches can run concurrently, and each stage still
  owns its app runtime, including any AGI/Dask distribution used inside that
  app.
* When a distributed stage submitter is configured, a ``Stage backend`` selector
  appears before the run buttons. ``Local contracts`` keeps execution in the
  current UI process; ``Distributed backend`` submits each ready stage through
  the configured backend and records ``distributed_stage`` provenance in the
  DAG state.
  When ``Distributed backend`` is selected, WORKFLOW shows the exact
  per-stage request preview before the run buttons: app, scheduler, worker
  nodes/slots, workers data path, mode integer, apps path, and the JSON
  ``RunRequest`` payload that will be sent for each stage.
  The built-in submitter is configured from the active app's saved
  **ORCHESTRATE** cluster settings: ``cluster_enabled`` must be true, a
  scheduler, workers, and ``Workers Data Path`` must be present, and each DAG
  stage ``app`` must resolve under ``src/agilab/apps/builtin`` or
  ``src/agilab/apps``. Each submitted stage runs in an isolated AGILAB
  subprocess so parallel ready stages do not share the in-process ``AGI`` class
  state.
* Workspace drafts and custom DAGs remain preview-only until they are promoted
  into a checked-in app template with an explicit controlled execution contract.

The technical JSON contract still uses stable field names so plans remain
portable:

* ``nodes[].execution.entrypoint`` names the stable stage executor, for example
  ``flight_telemetry_project.flight_context``. WORKFLOW displays this value in the stage
  table and graph so users can see what will execute before pressing
  ``Run next stage``.
* ``nodes[].execution.command`` is an optional command-list executor for
  deterministic local steps. Prefer a JSON list such as
  ``["python", "-m", "package.module"]`` over a shell string.
* ``nodes[].execution.params``, ``steps``, ``data_in``, ``data_out``, and
  ``reset_target`` are preserved from the DAG template into the execution plan,
  runner state, distributed request preview, and distributed submission
  evidence. This keeps cross-app DAG execution auditable instead of relying on
  hidden defaults.
* ``produces`` and ``consumes`` declare the artifact contract between stages.
  Executable app templates must declare at least one produced artifact per
  controlled stage so the runner can publish evidence and unlock downstream
  stages.

Use the smoke validator before a live two-node run:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/dag_distributed_stage_smoke.py \
     --scheduler 192.168.20.111:8786 \
     --workers '{"192.168.20.111": 1, "192.168.20.15": 1}' \
     --workers-data-path clustershare/agi \
     --compact

Add ``--execute`` only after SSH, SSHFS, app installs, and ORCHESTRATE cluster
settings are known good. Without ``--execute``, the command writes a dry-run
evidence JSON under ``test-results/`` and does not start Dask workers.

The panel shows the current readiness metrics, graph, artifact handoffs, and
execution history. Use the history table to distinguish preview dispatch events
from controlled real stage completions before promoting a DAG into a broader
orchestration flow.

Notebook export
~~~~~~~~~~~~~~~
The closed-by-default ``Notebook`` expander keeps notebook import and export
near the pipeline definition instead of in the sidebar:

* ``Import notebook`` uploads an ``.ipynb`` file and previews the stages that
  would be merged into ``lab_stages.toml``.
* ``Download pipeline notebook`` exports the current lab as ``lab_stages.ipynb``.

WORKFLOW can export the current lab as a runnable supervisor notebook. This is
not just a static dump of code cells.

* The notebook is written beside ``lab_stages.toml`` as ``lab_stages.ipynb``.
* You can open it outside the AGILAB UI in Jupyter-compatible tools such as
  JupyterLab or PyCharm.
* For a source checkout, prefer the mirror under
  ``exported_notebooks/<module>/lab_stages.ipynb`` and launch it from the AGILAB
  root project explicitly, for example:

  .. code-block:: bash

     CHECKOUT="${AGILAB_CHECKOUT:-/path/to/checkout}"
     uv --project "$CHECKOUT" run --with jupyterlab jupyter lab exported_notebooks/<module>/lab_stages.ipynb

  or execute it headlessly with:

  .. code-block:: bash

     CHECKOUT="${AGILAB_CHECKOUT:-/path/to/checkout}"
     uv --project "$CHECKOUT" run --with nbconvert python -m jupyter nbconvert --to notebook --execute --inplace exported_notebooks/<module>/lab_stages.ipynb

* The exported notebook keeps the recorded per-stage runtime and environment
  metadata instead of flattening the whole pipeline into one implicit kernel
  contract.
* Use the generated helper functions such as ``run_agilab_stage(i)`` and
  ``run_agilab_pipeline()`` to execute the saved stages in their recorded
  runtime.
* When the active app declares related analysis pages, the notebook also
  includes launcher helpers for those pages.

This is the accurate mental model: AGILAB can export a runnable version of your
pipeline outside the UI, but for mixed-runtime or multi-venv flows it does so as
a supervisor notebook rather than pretending every stage belongs to one notebook
kernel.

MLflow tracking
~~~~~~~~~~~~~~~
WORKFLOW execution and MLflow tracking now share the same runtime contract:

.. figure:: diagrams/pipeline_mlflow_tracking.svg
   :alt: Diagram showing one parent MLflow run for the whole workflow and one nested run per executed stage.
   :align: center
   :class: diagram-panel diagram-standard

   WORKFLOW creates one parent MLflow run per execution, then one nested run per stage, while both in-process and subprocess paths write to the same tracking store exposed by the MLflow UI.

* ``Run pipeline`` creates one parent MLflow run for the whole lab execution.
* Every executed stage becomes a nested MLflow run with its own metadata.
* The tracked metadata comes from ``lab_stages.toml`` and includes the stage
  description, prompt/question, selected model, execution engine, and runtime.
* Captured stdout, the executed snippet, the run log, and produced dataframe
  artefacts are logged to the same tracking store when they exist.

This means MLflow is no longer just a nearby dashboard. It is the execution
trace for WORKFLOW runs, while the sidebar remains the place where you inspect
that trace.

AGILAB does not define a separate experiment tracker, model registry, run
format, or metrics schema. The AGILAB runtime talks through a small tracker
facade (for example ``tracker.log_metric(...)`` and
``tracker.log_artifact(...)``), and the default backend is MLflow. This keeps
tracking automatic during normal AGILAB execution while preserving compatibility
with existing MLflow tooling.

Inside a snippet or worker, prefer the AGILAB facade when you need custom
domain metrics:

.. code-block:: python

   from agilab.tracking import tracker

   tracker.log_metric("accuracy", 0.94)
   tracker.log_artifact("reports/confusion_matrix.png")

The tracking store is the directory configured by ``MLFLOW_TRACKING_DIR``.
Subprocess-based stages receive the same ``MLFLOW_TRACKING_URI`` as in-process
stages, so both execution paths are visible from the same MLflow UI.

HISTORY
~~~~~~~
Inspect or tweak the raw ``lab_stages.toml`` via the code editor. Saving the
file here immediately refreshes the assistant tab.

Troubleshooting and checks
--------------------------

Use these checks if Workflow stages are confusing or fail to execute:

- If numbered stage buttons do not match ``lab_stages.toml``, open **HISTORY** and
  confirm the selected file is the current module's lab file.
- If execution fails on a stale path, regenerate or re-import the snippet in
  WORKFLOW before rerunning the stage.
- If ``Run`` writes no dataframe, check the destination under
  ``${AGILAB_EXPORT_ABS}/<module>/lab_out.csv`` and ensure ``Write permissions``
  are enabled for the selected execution environment.
- If an imported notebook is not loaded, re-upload ``.ipynb`` and then reopen the
  stage editor to force a refresh.
- If MLflow stays empty after a run, confirm that the stage completed and that
  the tracking store under ``MLFLOW_TRACKING_DIR`` is writable.
- If MLflow link fails to open, verify ``activate_mlflow`` completed and port
  forwarding is not blocked locally.

See also
--------

- :doc:`agilab-help` for the overall page sequence.
- :doc:`distributed-workers` for the full distributed workflow from ORCHESTRATE configuration to imported WORKFLOW stage.
- :doc:`execute-help` for generating reliable snippets before running a stage.
- :doc:`apps-pages` for analysis-side visualisations after a successful run.
- :doc:`roadmap/versioned-pipeline-stages` for the proposed structured successor
  to raw generated snippets in ``lab_stages.toml``.
