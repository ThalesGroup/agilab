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

- ``examples/notebook_migrations/skforecast_meteo_fr/notebooks/01_prepare_meteo_series.ipynb``
- ``examples/notebook_migrations/skforecast_meteo_fr/notebooks/02_backtest_temperature_forecast.ipynb``
- ``examples/notebook_migrations/skforecast_meteo_fr/notebooks/03_compare_predictions.ipynb``

The migrated AGILAB shape is illustrated by:

- ``examples/notebook_migrations/skforecast_meteo_fr/migrated_project/lab_steps.toml``
- ``examples/notebook_migrations/skforecast_meteo_fr/migrated_project/pipeline_view.dot``
- ``examples/notebook_migrations/skforecast_meteo_fr/analysis_artifacts/forecast_metrics.json``
- ``examples/notebook_migrations/skforecast_meteo_fr/analysis_artifacts/forecast_predictions.csv``

Why migrate
-----------

The notebook version is fine for exploration, but it keeps important workflow
state implicit:

- the execution order is only visible through notebook history
- parameters are spread across cells
- outputs depend on the active kernel state
- non-notebook users do not get a reusable analysis view

The AGILAB version makes the same workflow explicit:

- the semantic stages live in ``lab_steps.toml``
- the conceptual pipeline is readable in ``pipeline_view.dot``
- metrics and predictions are exported as stable files
- ``ANALYSIS`` can render the result without reopening the notebooks

Migrated pipeline shape
-----------------------

The pilot uses four semantic stages:

1. ``load_clean``
2. ``build_features``
3. ``backtest_forecaster``
4. ``forecast_next_days``

This is the key migration move: the notebook sequence is preserved, but the
stages become explicit and rerunnable.

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
- the same page can later serve a full AGILAB app, not only the pilot

Suggested migration path
------------------------

1. Keep the original notebooks as source material.
2. Export stable CSV/JSON artifacts first.
3. Translate the notebook sequence into ``lab_steps.toml``.
4. Add one small ``ANALYSIS`` page that reads those artifacts.
5. Only then move notebook logic into manager or worker code if needed.

This sequence keeps the migration lightweight while already showing what AGILAB
adds over a notebook-only workflow.
