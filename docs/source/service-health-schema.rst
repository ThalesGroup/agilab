Service Health JSON Schema
==========================

Overview
--------

``AGI.serve(..., action="health")`` returns a machine-readable snapshot with schema
``agi.service.health.v1`` and writes the same payload to ``health.json``.

Core fields
-----------

.. list-table::
   :header-rows: 1
   :widths: 28 20 52

   * - Field
     - Type
     - Description
   * - ``schema``
     - string
     - Payload schema identifier. Current value: ``agi.service.health.v1``.
   * - ``timestamp``
     - number
     - Unix timestamp (seconds) when the snapshot was generated.
   * - ``app``
     - string
     - App name used to build ``AgiEnv``.
   * - ``target``
     - string
     - App target identifier used in AGILab paths/state.
   * - ``status``
     - string
     - Service status (typically ``running``, ``idle``, ``degraded``, ``error``, ``stopped``).
   * - ``workers_running``
     - array[string]
     - Workers currently considered running.
   * - ``workers_pending``
     - array[string]
     - Workers pending/not fully stopped during transition phases.
   * - ``workers_restarted``
     - array[string]
     - Workers auto-restarted during the latest status check.
   * - ``workers_healthy``
     - array[string]
     - Workers evaluated as healthy.
   * - ``workers_unhealthy``
     - array[string]
     - Workers evaluated as unhealthy.
   * - ``workers_running_count``
     - integer
     - Count of ``workers_running``.
   * - ``workers_pending_count``
     - integer
     - Count of ``workers_pending``.
   * - ``workers_restarted_count``
     - integer
     - Count of ``workers_restarted``.
   * - ``workers_healthy_count``
     - integer
     - Count of ``workers_healthy``.
   * - ``workers_unhealthy_count``
     - integer
     - Count of ``workers_unhealthy``.
   * - ``queue``
     - object
     - Pending/running/done/failed queue counts for service artifacts.

Optional fields
---------------

- ``client_status``: Dask client status when available.
- ``heartbeat_timeout_sec``: effective timeout used by health evaluation.
- ``queue_dir``: service queue root path.
- ``cleanup``: cleanup counters (done/failed/heartbeats removed).
- ``restart_reasons``: map ``worker -> reason`` for auto-restarts.
- ``worker_health``: per-worker detailed rows used in the ORCHESTRATE health table.
- ``path``: present on direct ``action="health"`` responses when JSON export succeeds.

Minimal monitoring rule
-----------------------

Fail the check when one of these conditions is true:

- ``status`` is ``error`` or ``degraded``.
- ``workers_unhealthy_count`` is greater than ``0``.
- ``status`` is ``idle`` and your operational policy requires an active service.
- ``workers_restarted_count / workers_running_count`` exceeds your restart-rate SLA.

CLI example
-----------

From the AGILab repository, run:

.. code-block:: bash

   uv run python tools/service_health_check.py \
     --app mycode_project \
     --apps-path src/agilab/apps/builtin

Optional flags:

- ``--format prometheus`` to emit Prometheus-friendly metrics.
- ``--allow-idle`` / ``--no-allow-idle`` to override app defaults.
- ``--max-unhealthy <N>`` and ``--max-restart-rate <R>`` to override app defaults.

By default, the checker reads thresholds from ``[cluster.service_health]`` in
the target app ``app_settings.toml``.
