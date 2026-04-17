Service Mode
============

Purpose
-------

Service mode keeps persistent worker loops alive so you can reuse the same
execution context across multiple runs. This avoids paying startup cost for each
request and makes health/SLA checks explicit.

When to use it
--------------

Use service mode when you need one or more of the following:

- repeated requests on the same app with low latency;
- controlled worker lifecycle (start/status/health/stop);
- machine-readable health output for monitoring.

Fast path in ORCHESTRATE (web interface)
----------------------------------------

1. Open **ORCHESTRATE** and select your project.
2. In **System settings**, configure cluster mode, scheduler, and workers.
3. In **Service mode (persistent workers)**, click **START service** once.
4. Use **STATUS service** to inspect running/pending workers.
5. Use **HEALTH gate** to enforce SLA thresholds from ``app_settings.toml``.
6. Use **EXPORT snapshot** to write the current operator summary, health rows,
   and gate thresholds to a JSON file under ``~/log/execute/<app_target>/``.
7. Use **STOP service** before changing topology or ending the session.

Action semantics
----------------

- ``action="start"``: provisions workers and starts persistent loops.
- ``action="status"``: returns runtime state (running/degraded/idle/stopped/error).
- ``action="health"``: same status snapshot plus JSON export (schema
  ``agi.service.health.v1``).
- ``action="stop"``: requests loop termination and optionally shuts down the
  Dask cluster.

The ORCHESTRATE panel also provides a UI-only export action for operators:

- ``EXPORT snapshot`` writes ``service_operator_snapshot.json`` under
  ``~/log/execute/<app_target>/`` with the current status, cached worker health,
  and effective SLA thresholds.

End-to-end CLI example
----------------------

.. code-block:: python

   import asyncio
   from agi_cluster.agi_distributor import AGI
   from agi_env import AgiEnv

   APPS_PATH = "src/agilab/apps/builtin"
   APP = "mycode_project"

   async def main():
       env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)

       started = await AGI.serve(env, action="start")
       print("START:", started["status"])

       status = await AGI.serve(env, action="status")
       print("STATUS:", status["status"], status.get("workers_running_count", 0))

       health = await AGI.serve(env, action="health")
       print("HEALTH:", health["status"], health.get("workers_unhealthy_count", 0))

       stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
       print("STOP:", stopped["status"])

   if __name__ == "__main__":
       asyncio.run(main())

SLA thresholds
--------------

Per-app defaults are stored in ``[cluster.service_health]``:

.. code-block:: toml

   [cluster.service_health]
   allow_idle = false
   max_unhealthy = 0
   max_restart_rate = 0.25

These values are used by the ORCHESTRATE **HEALTH gate** and by
``tools/service_health_check.py`` unless overridden on the command line.

Operational checks
------------------

Use this checker for automation/monitoring:

.. code-block:: bash

   uv run python tools/service_health_check.py \
     --app mycode_project \
     --apps-path src/agilab/apps/builtin

Health JSON is written by default to:

- ``${AGI_SHARE_DIR}/service/<app_target>/health.json``

Operator snapshot JSON written from the ORCHESTRATE page is stored at:

- ``~/log/execute/<app_target>/service_operator_snapshot.json``

Common pitfalls
---------------

- Calling ``start`` twice without ``stop`` first: stop the existing service
  before restarting.
- Health status is ``idle`` but policy requires activity: set
  ``allow_idle = false`` and enforce with **HEALTH gate**.
- Missing health file in external monitor: call ``action="health"`` and verify
  permissions on the target output path.

Related pages
-------------

- :doc:`execute-help`
- :doc:`service-health-schema`
- :doc:`troubleshooting`
