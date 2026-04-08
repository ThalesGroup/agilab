Distributed Workers
===================

AGILAB supports distributed execution across remote worker machines, but the
usual workflow is UI-driven rather than handwritten.

.. important::

   You usually do not write ``AGI.install(...)`` or ``AGI.run(...)`` by hand.
   Configure the cluster in **ORCHESTRATE**, let AGILAB generate the snippet,
   then import or regenerate that generated step in **PIPELINE**.

For most users, the recommended sequence is:

1. Configure scheduler, workers, and execution flags in :doc:`execute-help`.
2. Let **ORCHESTRATE** generate the ``AGI.install(...)``,
   ``AGI.get_distrib(...)``, or ``AGI.run(...)`` snippet for the current setup.
3. Reuse that generated snippet in :doc:`experiment-help` when you want the
   distributed run to become a reproducible pipeline step.

You normally do not start by writing cluster orchestration code from scratch.

.. figure:: diagrams/distributed_orchestrate_pipeline_handoff.svg
   :alt: Diagram showing the UI-driven workflow from ORCHESTRATE to PIPELINE for distributed workers.
   :align: center
   :class: diagram-panel diagram-wide

   The supported workflow is configure in ORCHESTRATE, generate the snippet there, then reuse that generated step in PIPELINE.

Prerequisites
-------------

Before configuring distributed workers, make sure the environment is ready:

- The machine running AGILAB can reach every worker over the network.
- SSH access works non-interactively from the manager to every worker.
- A shared writable cluster path is mounted on every node with the same
  effective location. In cluster mode, do not rely on ``AGI_LOCAL_SHARE`` as a
  fallback.
- ``uv`` and the required Python runtime are available on the manager and the
  remote workers.
- The target app can be installed cleanly before you scale it to more nodes.

Use :doc:`key-generation`, :doc:`environment`, and :doc:`troubleshooting` if
any of those assumptions are not already true.

Step 1: Configure Distributed Execution in ORCHESTRATE
------------------------------------------------------

Open :doc:`execute-help` and use **System settings** as the source of truth for
cluster execution.

Typical distributed settings include:

- enabling the Dask / cluster execution path
- choosing the scheduler host
- defining the worker host map (for example ``{"192.168.1.21": 1, "192.168.1.22": 1}``)
- enabling or disabling ``pool``, ``cython``, and ``rapids`` according to the
  worker capabilities

These values are persisted in the per-user workspace copy of
``app_settings.toml``, so future snippet generations stay aligned with the same
cluster definition.

Step 2: Let ORCHESTRATE Generate the Snippet
--------------------------------------------

Once the distributed settings are configured, ORCHESTRATE generates the
deployment and execution code for you.

Use the generated sections in this order:

- **Install** to generate and run the ``AGI.install(...)`` snippet that stages
  the worker runtime on the selected nodes
- **Distribute** to generate ``AGI.get_distrib(...)`` and inspect how the work
  plan is partitioned before running it
- **Run** to generate the final ``AGI.run(...)`` snippet for the configured
  distributed setup

Treat these snippets as generated operational artifacts, not as examples you
must manually reconstruct first.

Quick UI Walkthrough
--------------------

Use this short checklist the first time:

1. In **ORCHESTRATE**, open **System settings** and enter the scheduler host and
   worker map.
2. Use **INSTALL** to stage the worker runtime on the selected machines.
3. Use **CHECK DISTRIBUTE** to inspect the generated ``AGI.get_distrib(...)``
   plan and confirm the partitions land on the intended workers.
4. Use **RUN** to generate the current ``AGI.run(...)`` snippet for that setup.
5. In **PIPELINE**, open **Add step** or **New step**, then import or regenerate
   that generated run step instead of rewriting it manually.

Equivalent Generated Snippet
----------------------------

ORCHESTRATE emits a snippet equivalent to the current UI configuration. A
distributed ``AGI.run(...)`` snippet typically looks like this:

.. code-block:: python

   import asyncio

   from agi_cluster.agi_distributor import AGI
   from agi_env import AgiEnv

   async def main():
       app_env = AgiEnv(app="mycode_project", verbose=1)
       workers = {
           "192.168.1.21": 1,
           "192.168.1.22": 1,
       }
       result = await AGI.run(
           app_env,
           scheduler="192.168.1.10",
           workers=workers,
           mode=4,
       )
       print(result)

   asyncio.run(main())

In normal usage, you get this from ORCHESTRATE after setting the scheduler and
worker hosts in the UI.

Step 3: Validate the Distribution Before Running
------------------------------------------------

Before launching a large distributed run, use **CHECK DISTRIBUTE** in
ORCHESTRATE.

This gives you:

- the generated ``AGI.get_distrib(...)`` snippet
- a **Distribution tree** view of the current work plan
- the **Workplan** editor so you can reassign partitions to different workers

This step is the fastest way to catch obvious mismatches such as:

- too many partitions for the selected workers
- all partitions being assigned to one host
- cluster settings changed in the UI but an old run snippet still being reused

Step 4: Reuse the Generated Snippet in PIPELINE
-----------------------------------------------

When the distributed run should become part of a repeatable workflow, move to
:doc:`experiment-help`.

The normal reuse path is:

1. Generate the install / distribute / run snippet in ORCHESTRATE.
2. On **PIPELINE**, open **Add step** (or **New step** on a fresh lab).
3. Import the generated snippet as the step source, or regenerate it from the
   latest current settings.
4. Run the imported step from PIPELINE so the distributed orchestration becomes
   part of ``lab_steps.toml`` and the tracked experiment history.

Important: imported snippets are snapshots. If you change worker hosts,
execution flags, or app arguments in ORCHESTRATE, regenerate or re-import the
snippet before running it again in PIPELINE.

Best Practices
--------------

Use these habits to keep distributed runs predictable:

- Start with one local scheduler and one remote worker before scaling to many
  nodes.
- Keep ``AGI_CLUSTER_SHARE`` mounted and writable on every node at the same
  effective path.
- Keep cluster share and local share conceptually separate. In cluster mode,
  outputs should land on the shared cluster path, not silently on local-only
  storage.
- Re-run **INSTALL** after dependency changes, worker-environment changes, or
  app updates that affect imports.
- Use **CHECK DISTRIBUTE** before expensive runs so the partitioning matches the
  intended worker layout.
- Size worker counts to the actual workload. More workers do not automatically
  mean better performance if the work plan is small or heavily serialized.
- Keep generated snippets in sync with the current UI state. Do not assume an
  older exported script still matches the latest app configuration.

Troubleshooting
---------------

Common distributed setup failures usually fall into one of these categories:

- **INSTALL hangs or never starts remotely**: verify SSH reachability, keys, and
  host trust.
- **Workers do not join the scheduler**: verify the scheduler host is reachable
  from the workers and that the worker host definitions are correct.
- **Outputs go to the wrong place**: verify cluster mode is enabled and the
  shared cluster path is mounted consistently across nodes.
- **Remote import errors after a successful install**: verify the worker
  environment was rebuilt from the current app and that dependencies are
  declared in the correct ``pyproject.toml`` scope.
- **PIPELINE runs stale cluster code**: regenerate or re-import the snippet from
  ORCHESTRATE after changing worker or app settings.

See also:

- :doc:`execute-help`
- :doc:`experiment-help`
- :doc:`cluster`
- :doc:`key-generation`
- :doc:`troubleshooting`
