Demos
=====

.. toctree::
   :hidden:

   demo_capture_script

Use this page to choose a public AGILAB demo route. It is a router, not a
quick-start guide.

Choose a demo
-------------

.. image:: https://img.shields.io/badge/agi--core-demo-1D4ED8?style=for-the-badge
   :target: https://thalesgroup.github.io/agilab/notebook-quickstart.html
   :alt: agi-core demo

.. image:: https://img.shields.io/badge/AGILAB-demo-0F766E?style=for-the-badge
   :target: https://huggingface.co/spaces/jpmorard/agilab
   :alt: AGILAB demo

.. image:: https://img.shields.io/badge/notebook--migration-demo-7C3AED?style=for-the-badge
   :target: https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html
   :alt: notebook migration demo

.. image:: https://img.shields.io/badge/advanced--proof-pack-B45309?style=for-the-badge
   :target: https://thalesgroup.github.io/agilab/advanced-proof-pack.html
   :alt: advanced proof pack

What each route is for
----------------------

- **AGILAB demo**: use :doc:`agilab-demo` for the self-serve public Hugging Face
  Spaces route for the AGILAB web UI. It publishes the lightweight
  ``flight_telemetry_project`` and ``weather_forecast_project`` paths, so use it as the
  public first proof for ``PROJECT`` -> ``ORCHESTRATE`` -> ``WORKFLOW`` ->
  ``ANALYSIS``, including ``view_maps``, ``view_forecast_analysis``, and
  ``view_release_decision``.
- **agi-core demo**: notebook-first runtime path. Use this if you want the
  smaller ``AgiEnv`` / ``AGI.run(...)`` surface before the web UI.
- **Notebook migration demo**: use :doc:`notebook-migration-skforecast-meteo`
  when you want the notebook-to-AGILAB story: source notebooks, migrated
  ``lab_stages.toml``, ``pipeline_view.dot``, exported forecast artifacts, and
  the hosted ``weather_forecast_project`` analysis route.
- **Advanced Proof Pack**: use :doc:`advanced-proof-pack` after the first demo
  when you want the deeper packaged proof routes: ``mission_decision_project``,
  ``execution_pandas_project`` / ``execution_polars_project``, UAV queue
  analysis with ``uav_relay_queue_project``, ``service_mode`` previews,
  ``inter_project_dag`` previews, ``mlflow_auto_tracking`` previews,
  ``resilience_failure_injection`` previews, ``train_then_serve`` previews,
  :doc:`data-connectors`, and :doc:`release-proof`.
- **Industrial optimization examples**: use
  :doc:`industrial-optimization-examples` when your apps repository includes
  ``sb3_trainer_project`` and you want the advanced SB3 routes: Active Mesh
  Optimization, MLflow auto-tracking, multi-app DAGs, resilience/failure
  injection, and train-then-serve contracts.
- **Quick start**: the safest truthful first proof of the full product path.
  Use :doc:`quick-start` if you want the recommended local run instead of a
  public demo.

Four short demos
----------------

Use these as narrow product demos. They are intentionally generic and should
not depend on private apps or app-specific claims.

The static scenario contract is available as JSON:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/public_proof_scenarios.py --compact
   uv --preview-features extra-build-dependencies run python tools/public_proof_scenarios.py --first-proof-json first-proof.json --hf-smoke-json hf-space-smoke.json --output public-proof-scenarios.json

**Local app proof**
  Install the released examples profile or use the source checkout, then run the
  public first proof:

  .. code-block:: bash

     python -m pip install "agilab[examples]"
     python -m agilab.lab_run first-proof --json --max-seconds 60

  Stop when the command exits successfully and writes ``run_manifest.json``.
  This package route uses ``agi-apps`` as the public app umbrella and resolves
  the built-in project from the matching per-app package. Install
  ``agilab[ui]`` and rerun with ``--with-ui`` when you also want to boot the
  packaged local pages and ``agi-pages`` analysis views.
  The same route is available in the UI by following ``PROJECT`` ->
  ``ORCHESTRATE`` -> ``ANALYSIS`` with ``flight_telemetry_project``.

**Distributed worker route**
  Use the same public app, then switch ORCHESTRATE from the local path to the
  configured worker or SSH-host path. Keep the demo bounded: prove that worker
  packaging is staged, service health gates report status, and outputs land
  under the normal log directory.

  .. code-block:: bash

     uv --preview-features extra-build-dependencies run python tools/service_health_check.py --format json

  Stop when the health gate is explicit. This is a worker/operator demo, not a
  certification of every possible remote topology.

**MLflow tracking route**
  Start with the packaged preview when you want a short, deterministic proof:

  .. code-block:: bash

     uv --preview-features extra-build-dependencies run python src/agilab/examples/mlflow_auto_tracking/preview_mlflow_auto_tracking.py --output-dir /tmp/mlflow_auto_tracking_preview

  Add ``--with mlflow`` to the ``uv`` command when you want the same evidence
  logged into a local MLflow store. The demo objective is to show that AGILAB
  keeps setup, execution, artifacts, and visible results together while MLflow
  remains the tracking system of record when it is used.

  Stop when the pipeline artifacts and the MLflow run link point to the same
  experiment evidence.

**Resilience failure-injection route**
  Use the packaged preview when the demo objective is strategy comparison under
  a controlled degradation event:

  .. code-block:: bash

     uv --preview-features extra-build-dependencies run python src/agilab/examples/resilience_failure_injection/preview_resilience_failure_injection.py --output /tmp/resilience_preview.json

  Stop when the route ranking before failure, route ranking after failure, and
  recommended fixed/replanned/search/policy response are visible in the same
  JSON payload. The preview is deterministic and does not train a real policy.

**Train-then-serve route**
  Use the packaged preview when the demo objective is the handoff from
  experiment evidence to a service-ready contract:

  .. code-block:: bash

     uv --preview-features extra-build-dependencies run python src/agilab/examples/train_then_serve/preview_train_then_serve.py --output-dir /tmp/train_then_serve_preview

  Stop when ``service_contract.json``, ``prediction_sample.json``, and
  ``service_health.json`` are visible. The preview is deterministic and does
  not start persistent workers.

**Notebook migration route**
  Use the packaged migration example when the demo objective is notebook
  consolidation rather than execution speed:

  .. code-block:: bash

     uv --preview-features extra-build-dependencies run python src/agilab/examples/notebook_to_dask/preview_notebook_to_dask.py --output /tmp/notebook_to_dask_preview.json

  Then open :doc:`notebook-migration-skforecast-meteo` or switch the hosted UI
  to ``weather_forecast_project`` and open ``view_forecast_analysis``. Stop when
  the notebook source, migrated pipeline shape, exported artifacts, and reusable
  analysis view are visible together.

Demo naming
-----------

Keep the two public AGILAB demo lanes separate:

- ``flight_telemetry_project`` is the default hosted/newcomer demo. It is a lightweight
  data-generation path used to prove the core UI and local execution flow
  quickly.
- ``weather_forecast_project`` is the second hosted demo. It is a lightweight
  notebook-migration path with source notebooks, forecast artifacts, and
  release-decision views.
- ``uav_relay_queue_project`` is the UAV Relay Queue RL demo. It is the
  advanced domain scenario and should not be described as the default hosted
  app.
- ``mission_decision_project`` and the execution playground apps are advanced proof
  routes. They are public built-in demos, but they should not replace
  ``flight_telemetry_project`` as the default hosted/newcomer app.

See also
--------

- :doc:`quick-start`
- :doc:`release-proof`
- :doc:`architecture-five-minutes`
- :doc:`agilab-demo`
- :doc:`notebook-quickstart`
- :doc:`notebook-migration-skforecast-meteo`
- :doc:`advanced-proof-pack`
- :doc:`industrial-optimization-examples`
- :doc:`newcomer-guide`
- :doc:`compatibility-matrix`
