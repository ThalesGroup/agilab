Notebook Migration Example
==========================

This example shows a lightweight migration path from a small notebook workflow
to an AGILAB project, using:

The goal is to show, in one pass, how a notebook-only workflow becomes a
reproducible AGILAB project without changing the forecasting logic.

- ``skforecast`` for local forecasting
- a small daily weather sample shaped like a Meteo-France export
- a reusable AGILAB ``ANALYSIS`` page over exported artifacts

Why this use case is useful:

- it keeps the same analysis idea while making execution deterministic,
- it demonstrates migration ROI with minimal refactoring, and
- it produces concrete files you can inspect and hand off.

Source material (notebook-first)
--------------------------------

- ``examples/notebook_migrations/skforecast_meteo_fr/notebooks/01_prepare_meteo_series.ipynb``
- ``examples/notebook_migrations/skforecast_meteo_fr/notebooks/02_backtest_temperature_forecast.ipynb``
- ``examples/notebook_migrations/skforecast_meteo_fr/notebooks/03_compare_predictions.ipynb``

Target AGILAB shape (same workflow made explicit):

- ``examples/notebook_migrations/skforecast_meteo_fr/migrated_project/lab_steps.toml``
- ``examples/notebook_migrations/skforecast_meteo_fr/migrated_project/pipeline_view.dot``
- ``examples/notebook_migrations/skforecast_meteo_fr/analysis_artifacts/forecast_metrics.json``
- ``examples/notebook_migrations/skforecast_meteo_fr/analysis_artifacts/forecast_predictions.csv``

Built-in project shipped in the repository:

- ``src/agilab/apps/builtin/meteo_forecast_project``
- ``src/agilab/apps/builtin/meteo_forecast_project/lab_steps.toml``
- ``src/agilab/apps/builtin/meteo_forecast_project/pipeline_view.dot``

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
- the same flow can then become a runnable built-in app instead of staying a notebook skeleton

The migration move is therefore:

1. keep notebooks as history,
2. export the key results to stable files,
3. express the execution sequence explicitly in ``lab_steps.toml``,
4. add a tiny analysis contract, and
5. run the same logic from AGILAB pages.

Migrated pipeline shape
-----------------------

Pilot pipeline semantics:

1. ``load_clean``
2. ``build_features``
3. ``backtest_forecaster``
4. ``forecast_next_days``

This is the key migration move: notebook chronology is preserved, but stages become
explicit artifacts and can be re-run consistently across machines.

Real built-in project
---------------------

The migration no longer stops at a conceptual skeleton. The repo now includes
``meteo_forecast_project`` as a built-in AGILAB app.

What it adds beyond the pilot folder:

- an app manager and a worker under ``src/agilab/apps/builtin/meteo_forecast_project/src``
- a real ``PROJECT`` form for station, target, lag, and horizon settings
- seeded local sample data for the first run
- stable artifacts exported to ``~/export/meteo_forecast/forecast_analysis``
- a default ``ANALYSIS`` page selection through ``view_forecast_analysis``

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

Suggested migration path (practical)
------------------------------------

1. Keep the original notebooks as source material.
2. Export stable CSV/JSON artifacts first.
3. Translate the notebook sequence into ``lab_steps.toml``.
4. Add one small ``ANALYSIS`` page that reads those artifacts.
5. Only then move notebook logic into manager or worker code if needed.

This sequence keeps the migration lightweight while still making the gain visible:

- identical behavior is preserved where possible,
- execution order is no longer hidden in cell history,
- analysis can be reviewed and shared without notebook state, and
- the project can evolve into a true reusable app when needed.

If the sequence is not clear in your own notebook set, apply the same schema to
your files: identify notebook intent per cell block, create one pipeline stage
per intent block, then map each exported artifact to one ``ANALYSIS`` input.
