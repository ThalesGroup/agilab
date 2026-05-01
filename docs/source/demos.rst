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

What each route is for
----------------------

- **AGILAB demo**: use :doc:`agilab-demo` for the self-serve public Hugging Face
  Spaces route for the AGILAB web UI. It publishes the lightweight
  ``flight_project`` and ``meteo_forecast_project`` paths, so use it as the
  public first proof for ``PROJECT`` -> ``ORCHESTRATE`` -> ``PIPELINE`` ->
  ``ANALYSIS``, including ``view_maps``, ``view_forecast_analysis``, and
  ``view_release_decision``.
- **agi-core demo**: notebook-first runtime path. Use this if you want the
  smaller ``AgiEnv`` / ``AGI.run(...)`` surface before the web UI.
- **Quick start**: the safest truthful first proof of the full product path.
  Use :doc:`quick-start` if you want the recommended local run instead of a
  public demo.

Three short demos
-----------------

Use these as narrow product demos. They are intentionally generic and should
not depend on private apps or app-specific claims.

The static scenario contract is available as JSON:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/public_proof_scenarios.py --compact

**Local app proof**
  Install the released package or use the source checkout, then run the public
  first proof:

  .. code-block:: bash

     python -m pip install agilab
     agilab first-proof --json --max-seconds 60

  Stop when the command exits successfully and writes ``run_manifest.json``.
  The same route is available in the UI by following ``PROJECT`` ->
  ``ORCHESTRATE`` -> ``ANALYSIS`` with ``flight_project``.

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
  Use a project with pipeline steps, enable MLflow tracking in the run
  environment, then execute the pipeline and open ANALYSIS. The demo objective
  is to show that AGILAB keeps setup, execution, artifacts, and visible results
  together while MLflow remains the tracking system of record when it is used.

  Stop when the pipeline artifacts and the MLflow run link point to the same
  experiment evidence.

Demo naming
-----------

Keep the two public AGILAB demo lanes separate:

- ``flight_project`` is the default hosted/newcomer demo. It is a lightweight
  data-generation path used to prove the core UI and local execution flow
  quickly.
- ``meteo_forecast_project`` is the second hosted demo. It is a lightweight
  notebook-migration path with forecast artifacts and release-decision views.
- ``uav_relay_queue_project`` is the UAV Relay Queue RL demo. It is the
  advanced domain scenario and should not be described as the default hosted
  app.

See also
--------

- :doc:`quick-start`
- :doc:`architecture-five-minutes`
- :doc:`agilab-demo`
- :doc:`notebook-quickstart`
- :doc:`newcomer-guide`
- :doc:`compatibility-matrix`
