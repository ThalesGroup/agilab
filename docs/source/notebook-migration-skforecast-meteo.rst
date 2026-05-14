Notebook Migration Example
==========================

This example shows a lightweight migration path from a small notebook workflow
to an AGILAB project, using:

- ``skforecast`` for local forecasting
- a small daily weather sample shaped like a Meteo-France export
- a reusable AGILAB ``ANALYSIS`` page over exported artifacts

Repository material
-------------------

The source material lives in:

- ``src/agilab/examples/notebook_migrations/skforecast_meteo_fr/notebooks/01_prepare_meteo_series.ipynb``
- ``src/agilab/examples/notebook_migrations/skforecast_meteo_fr/notebooks/02_backtest_temperature_forecast.ipynb``
- ``src/agilab/examples/notebook_migrations/skforecast_meteo_fr/notebooks/03_compare_predictions.ipynb``

The migrated AGILAB shape is illustrated by:

- ``src/agilab/examples/notebook_migrations/skforecast_meteo_fr/migrated_project/lab_stages.toml``
- ``src/agilab/examples/notebook_migrations/skforecast_meteo_fr/migrated_project/pipeline_view.dot``
- ``src/agilab/examples/notebook_migrations/skforecast_meteo_fr/analysis_artifacts/forecast_metrics.json``
- ``src/agilab/examples/notebook_migrations/skforecast_meteo_fr/analysis_artifacts/forecast_predictions.csv``

The same migration material is mirrored under
``src/agilab/examples/notebook_migrations/skforecast_meteo_fr`` so packaged
installs include the notebooks, sample data, exported artifacts, lab stages, and
pipeline view instead of only the runnable app scripts.

The repo now also ships the same idea as a real built-in project:

- ``src/agilab/apps/builtin/weather_forecast_project``
- ``src/agilab/apps/builtin/weather_forecast_project/lab_stages.toml``
- ``src/agilab/apps/builtin/weather_forecast_project/pipeline_view.dot``
- ``src/agilab/apps/builtin/weather_forecast_project/notebook_import_views.toml``

Why migrate
-----------

The notebook version is fine for exploration, but it keeps important workflow
state implicit:

- the execution order is only visible through notebook history
- parameters are spread across cells
- outputs depend on the active kernel state
- non-notebook users do not get a reusable analysis view

The AGILAB version makes the same workflow explicit:

- the semantic stages live in ``lab_stages.toml``
- the conceptual pipeline is readable in ``pipeline_view.dot``
- metrics and predictions are exported as stable files
- ``ANALYSIS`` can render the result without reopening the notebooks
- the same flow can then become a runnable built-in app instead of staying a notebook skeleton

Migrated pipeline shape
-----------------------

The pilot uses four semantic stages:

1. ``load_clean``
2. ``build_features``
3. ``backtest_forecaster``
4. ``forecast_next_days``

This is the key migration move: the notebook sequence is preserved, but the
stages become explicit and rerunnable.

Real built-in project
---------------------

The migration no longer stops at a conceptual skeleton. The repo now includes
``weather_forecast_project`` as a built-in AGILAB app.

What it adds beyond the pilot folder:

- an app manager and a worker under ``src/agilab/apps/builtin/weather_forecast_project/src``
- a real ``PROJECT`` form for station, target, lag, and horizon settings
- seeded local sample data for the first run
- stable artifacts exported to ``~/export/weather_forecast/forecast_analysis``
- a default ``ANALYSIS`` page selection through ``view_forecast_analysis``
- app-owned notebook import view declarations for ``view_forecast_analysis``
  and ``view_release_decision``

ANALYSIS page
-------------

The repo now ships a reusable page bundle for this artifact contract:

- ``src/agilab/apps-pages/view_forecast_analysis``

It reads:

- ``forecast_metrics.json``
- ``forecast_predictions.csv``

By default it looks under ``~/export/<app_target>/forecast_analysis``. You can
also point it at any directory containing those files.

This makes the benefit of migration visible immediately:

- exported metrics become comparable across runs
- observed vs predicted curves become reusable outside the notebook
- the same page now serves both the migration pilot and the built-in forecast app

Suggested migration path
------------------------

1. Keep the original notebooks as source material.
2. Export stable CSV/JSON artifacts first.
3. Translate the notebook sequence into ``lab_stages.toml``.
4. Add one small ``ANALYSIS`` page that reads those artifacts.
5. Only then move notebook logic into manager or worker code if needed.

This sequence keeps the migration lightweight while already showing what AGILAB
adds over a notebook-only workflow.
