ORCHESTRATE
==============

.. toctree::
   :hidden:

Introduction
------------
Orchestrate walks through the lifecycle required to ship and operate an AGILab
application. It generates ready-to-run snippets, streams logs back into the UI
and keeps the per-user ``app_settings.toml`` workspace copy synchronised so
that installs, distribution checks and runs are reproducible. The mutable file
now lives under ``~/.agilab/apps/<app>/app_settings.toml`` and is seeded from
the app's versioned ``src/app_settings.toml`` on first use.

Sidebar
-------
- Project selector that keeps the page in lockstep with the active app.
- ``Verbosity level`` changes the ``verbose`` flag injected into every generated
  snippet (0–3) and is persisted under ``[cluster].verbose``.

Main Content Area
-----------------
- ``System settings`` groups the cluster configuration. Toggle support for
  ``pool``, ``cython`` and ``rapids``, enable the Dask scheduler and provide IP
  definitions for workers. The calculated mode hint clarifies how the chosen
  combination will execute and the settings are written back to
  ``~/.agilab/apps/<app>/app_settings.toml``.
- ``Install`` renders the install snippet that provisions the project's virtual
  environments. ``INSTALL`` streams stdout/stderr into ``Install logs`` so you
  know when the worker is ready. A successful install automatically enables the
  ``Run`` section.
- ``Distribute`` is split into two parts:

    * ``<module> args``: edit the run arguments managed in ``app_args.py``. You
      can toggle between the generated form UI and the optional custom snippet
      saved in ``app_args_form.py``. Saved values update ``[args]`` in
      ``~/.agilab/apps/<app>/app_settings.toml``. Custom forms may also surface derived preview
      metrics computed from the current inputs and the latest generated summary
      artefacts. When they do, the preview should match the metric written back
      by the app after ``RUN`` so the UI and exported reports stay aligned.
    * ``Distribute details``: generates the ``AGI.get_distrib`` snippet and the
      ``CHECK DISTRIBUTE`` action. When the command succeeds the ``Distribution
      tree`` expander plots the resulting work plan (DAG or tree) and ``Workplan``
      lets you reassign partitions to different workers before saving the
      modified plan.

- ``Run`` exposes the ``AGI.run`` snippet together with a ``Benchmark all
  modes`` toggle if you want to iterate through every execution path. ``RUN``
  streams logs into the ``Run logs`` expander and stores the output timings in
  ``benchmark.json``, which is summarised under ``Benchmark results``.
- ``Service mode (persistent workers)`` keeps long-lived worker loops alive and
  lets you trigger ``START/STATUS/HEALTH gate/STOP`` without rebuilding the execution
  context every time.
- ``LOAD DATA`` fetches the latest dataframe path configured for the project and
  shows an in-place preview. The preview is available even after a rerun.
- ``Prepare Data for Pipeline and Analysis`` creates (or updates) the CSV that
  powers the Pipeline and Analysis pages. Use the column selector with
  ``Select all`` support to decide which fields are persisted to
  ``${AGILAB_EXPORT_ABS}/<module>/export.csv``.

Snippet Handoff to Pipeline
---------------------------
For newcomers, keep Orchestrate and Pipeline in sync with this workflow:

1. Generate the snippet in **Orchestrate** (typically ``AGI.run``).
2. On **PIPELINE**, open **Add step** (or **New step** when starting fresh),
   pick ``Step source = gen step`` for a fresh generation, or ``Step source =``
   an existing snippet (for example ``AGI_run.py`` or ``lab_snippet.py``) to
   import it directly.
3. For app updates, update ``<module> args`` in the per-user workspace
   ``app_settings.toml`` / ``[args]`` then regenerate or re-import the matching
   snippet in Pipeline.

This avoids running stale code that still references old app argument values.
For example, ``sat_trajectory_project`` snippets now use
``total_satellites_wanted``; older exports using ``number_of_sat`` or
``number_of_tle_satellites`` will fail fast until you regenerate them.

Service Mode Health
-------------------

For a complete operator workflow (web and CLI), see :doc:`service-mode`.

Use these defaults as a stable baseline for most projects:

- ``Heartbeat timeout``: ``10s``.
- ``Done artifacts TTL``: ``168h`` (7 days).
- ``Failed artifacts TTL``: ``336h`` (14 days).
- ``Heartbeat artifacts TTL``: ``24h``.
- ``Done/Failed max files``: ``2000`` each.
- ``Heartbeat max files``: ``1000``.

Health gate defaults are persisted per app in the workspace
``app_settings.toml`` under ``[cluster.service_health]``:

- ``allow_idle`` (default ``false``).
- ``max_unhealthy`` (default ``0``).
- ``max_restart_rate`` (default ``0.25``).

When STATUS runs, Orchestrate displays a health table:

- ``worker``: Dask worker address.
- ``healthy``: overall health evaluation for that worker loop.
- ``reason``: why the worker is unhealthy (empty when healthy).
- ``future_state``: Dask future state for the loop task.
- ``heartbeat_state``: latest worker heartbeat-reported state.
- ``heartbeat_age_sec``: seconds since latest heartbeat.

Use ``HEALTH gate`` to run ``AGI.serve(..., action="health")`` and immediately
validate the current state against the per-app SLA thresholds above.

Auto-restart reason values currently include:

- ``loop-finished`` / ``loop-error`` / ``loop-cancelled``.
- ``missing-heartbeat``.
- ``stale-heartbeat(<N>s)``.

Service health JSON export
--------------------------

Each ``AGI.serve`` service action writes a machine-readable health snapshot
(``agi.service.health.v1``), and ``action="health"`` returns that payload
directly.

Default output path:

- ``${AGI_SHARE_DIR}/service/<app_target>/health.json``.

Custom output path:

.. code-block:: python

   health = await AGI.serve(
       app_env,
       action="health",
       health_output_path="service/custom_health.json",
   )
   print(health["status"], health["workers_unhealthy_count"])

Field reference:

- :doc:`service-health-schema`

Troubleshooting and checks
--------------------------

Use these checks if Orchestrate actions do not behave as expected:

- If ``INSTALL`` stays stuck, check cluster host reachability, SSH credentials,
  and whether ``~/.agilab/.env`` still points to valid venv paths.
- If the generated snippet looks wrong, compare ``[args]`` in
  ``~/.agilab/apps/<project>/app_settings.toml`` with the values shown in
  ``app_args_form.py``. If the workspace copy is missing, AGILab will reseed it
  from ``src/<project>/src/app_settings.toml``.
- If ``RUN`` returns import errors, verify the target virtual environment contains
  the same versions as ``src/<project>/pyproject.toml`` and re-run install.
- If no logs appear, confirm the log expansion is expanded and that the runtime
  has write access to ``~/log/execute/<app>``.
- If an external monitor cannot read service health, call
  ``AGI.serve(..., action="health")`` and verify that ``health.json`` is written
  at the expected path.

See also
--------

- :doc:`agilab-help` to place Orchestrate in the full page flow.
- :doc:`experiment-help` for running the generated snippet in the Pipeline assistant.
- :doc:`explore-help` for launching result views.
