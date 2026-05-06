Industrial Optimization Examples
================================

Use this page when the lightweight first proof is complete and you want an
advanced example that shows AGILAB as an execution and evidence engine for
dynamic industrial AI workflows. These examples live in an optional apps
repository project, not in the default hosted first-run path.

What this proves
----------------

The reference project is ``sb3_trainer_project`` when it is available in your
apps repository. It now covers five complementary proof routes:

.. list-table::
   :header-rows: 1
   :widths: 28 34 38

   * - Example
     - What it proves
     - Primary output
   * - Active Mesh Optimization
     - UAV relays are active agents in a centralized PPO policy; the run shows
       movement decisions, topology changes, and network delivery evidence.
     - ``trainer_uav_active_mesh_ppo``
   * - MLflow Auto-Tracking
     - AGILAB runs the pipeline while MLflow remains the tracking system of
       record for parameters, metrics, artifacts, and model files.
     - ``trainer_uav_relay_queue_ppo_mlflow`` and ``mlflow_tracking.json``
   * - Multi-App DAG
     - Flight, satellite, link, network, trainer, and analysis stages exchange
       explicit artifacts instead of hidden notebook state.
     - ``lab_steps.toml`` and ``pipeline_view.dot``
   * - Resilience / Failure Injection
     - A degraded relay is injected, then fixed routing is compared with an
       adaptive policy on the same scenario contract.
     - ``trainer_uav_relay_queue_resilience`` and
       ``resilience_summary.json``
   * - Train-Then-Serve
     - A trained policy is loaded, sampled, and exported with a service
       contract and health gate before a production serving stack is involved.
     - ``trainer_uav_relay_queue_service`` with
       ``service_contract.json`` and ``service_health.json``

How to run it
-------------

1. Install or link the apps repository that contains ``sb3_trainer_project``.
2. Open AGILAB, select ``sb3_trainer_project`` in ``PROJECT``, then run
   ``INSTALL`` in ``ORCHESTRATE``.
3. Choose one of the trainer templates in the app args form:

   - ``Train • UAV Active Mesh • PPO``
   - ``Track • UAV Relay Queue • PPO + MLflow``
   - ``Evaluate • UAV Relay Queue • Resilience``
   - ``Serve • UAV Relay Queue • Policy Service``

4. Open ``PIPELINE`` to inspect the recipe and conceptual DAG view.
5. Open ``ANALYSIS`` on the exported allocation, queue, topology, or health
   artifacts.

What not to claim
-----------------

- The active mesh route is a compact centralized-policy teaching example. It
  is not yet a claim of full decentralized MARL certification.
- The MLflow route does not create a parallel AGILAB model registry. MLflow
  remains the tracking and registry integration point.
- The service route exports a contract and a health sample. It is not a
  production serving platform by itself.
- The multi-app DAG is a reproducible artifact contract. It should not be
  presented as a replacement for hardened production workflow schedulers.

Why it matters
--------------

Together these examples demonstrate AGILAB's intended product position:

- AGILAB owns setup, environments, workers, execution, DAG context, and
  operator-facing evidence.
- MLflow or downstream platforms own long-term tracking, registry, deployment,
  and production governance.
- Dynamic industrial systems can be evaluated by comparing baseline,
  adaptive, failure-injected, and service-contract outcomes through the same
  artifact layer.

Related pages
-------------

- :doc:`agilab-mlops-positioning`
- :doc:`advanced-proof-pack`
- :doc:`features`
- :doc:`experiment-help`
- :doc:`service-mode`
