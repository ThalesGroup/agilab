AGILAB Demo
===========

Use this sidebar-visible counterpart when you want the public hosted AGILAB web
UI first. This is the hosted web UI counterpart to :doc:`notebook-quickstart`,
which is the notebook-first ``agi-core`` demo.

Start here
----------

Open the public Hugging Face Space:

.. image:: https://img.shields.io/badge/AGILAB-demo-0F766E?style=for-the-badge
   :target: https://huggingface.co/spaces/jpmorard/agilab
   :alt: AGILAB demo

- `Open AGILAB Space <https://huggingface.co/spaces/jpmorard/agilab>`_
- `Open the notebook migration walkthrough <https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html>`_

What will happen
----------------

The hosted demo publishes two lightweight built-in paths:

- confirm ``flight_telemetry_project`` is selected in ``PROJECT``
- inspect the generated execution snippet in ``ORCHESTRATE``
- inspect the packaged recipe in ``WORKFLOW``
- open ``ANALYSIS`` and finish on the ``view_maps`` operator view
- switch to ``weather_forecast_project`` to inspect the notebook-migration style
  workflow, then open ``view_forecast_analysis`` or ``view_release_decision``
  from ``ANALYSIS``
- use :doc:`notebook-migration-skforecast-meteo` as the companion walkthrough
  when you want to show the source notebooks, migrated ``lab_stages.toml``,
  ``pipeline_view.dot``, and exported artifacts behind that hosted app

This is a public preview route. It is not a replacement for the local
:doc:`quick-start` proof when you need to validate your own machine,
environment, or app repository.

After the hosted first proof
----------------------------

Use :doc:`advanced-proof-pack` when the first proof is complete and you want to
show the deeper built-in assets without making the newcomer route longer:

- ``mission_decision_project`` for a deterministic mission-decision workflow.
- ``execution_pandas_project`` and ``execution_polars_project`` for
  execution-model benchmarking, including the Cython typed-kernel proof.
- ``uav_relay_queue_project`` for queue analysis, topology, trajectories, and
  ``view_maps_network``.
- ``service_mode`` and data connector reports for operator and integration
  evidence.
- :doc:`release-proof` for the trust close-out.

What success looks like
-----------------------

You are past the hosted-demo hurdle when the Space loads, ``flight_telemetry_project`` and
``weather_forecast_project`` are available from the AGILAB UI, ``WORKFLOW`` can
show recipe context, and ``ANALYSIS`` opens the ``view_maps`` and
``view_forecast_analysis`` routes without a startup error. For evidence scope,
use :doc:`compatibility-matrix`; it separates validated public routes from
cloud/provider combinations that remain open.

Related pages
-------------

- :doc:`demos` for the public demo chooser.
- :doc:`quick-start` for the recommended local first proof.
- :doc:`notebook-quickstart` for the ``agi-core`` notebook demo.
- :doc:`notebook-migration-skforecast-meteo` for the notebook-to-AGILAB demo.
- :doc:`advanced-proof-pack` for deeper packaged proof routes.
- :doc:`compatibility-matrix` for the validation status of public routes.
