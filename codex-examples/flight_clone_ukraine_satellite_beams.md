# Scenario 1 – Clone-Based Workflow (Ukraine + Beams + Satellite Paths)
Text-only plan; nothing was executed.

## Step 1 – Clone baseline
- Run the IDE “Clone app” flow (or `tools/clone_app.py`) to copy `flight_project` into a fresh slug (example: `flight_clone_project`).  
- Immediately regenerate run configs (`tools/generate_runconfig_scripts.py`), seed `log/execute/<slug>`, and run `AGI_get_distrib_<slug>.py` + `AGI_run_<slug>.py` once to confirm the clone works before edits.

## Step 2 – Add antenna beam support
- **Schema**: copy the beam column definitions from `flight_legacy_project` into `app_settings.toml`, `app_args.py`, `app_args_form.py`, and `_load_dataframe`. Ensure the dataset source emits that field.  
- **Computation**: port helpers such as `compute_beam` / `antenna_id` from the legacy manager/worker and integrate them into the clone so the column is filled during preprocessing.  
- **UI**: replicate the Streamlit tables/charts/filters that expose the beam from `flight_legacy_project/pages/...` into the clone’s EXECUTE/EXPLORE pages.  
- **Docs/config**: mention the beam column in README/help text, rerun `docs/gen-docs.py` from `thales_agilab`, and keep `app_settings.toml`/dataset descriptions in sync.  
- **Tests**: copy the unit tests that cover the beam column (manager + worker) into the new app and adapt imports; run them plus `app_test.py`.

## Step 3 – Recenter flights over Ukraine
- Adjust the dataset generator/CSV (or `AGI_get_distrib_*` script) to produce coordinates within a Ukraine bounding box (e.g., Kyiv/Dnipro).  
- Update default map zoom/args in `app_settings.toml` and `app_args_form.py`.  
- Rebuild packaged archives if the project distributes data bundles.

## Step 4 – Reuse `sat_trajectory_project`
- Import the trajectory helper (e.g., `sat_trajectory_worker.compute_trajectory`) and call it during preprocessing to assign a satellite path/beam footprint per flight.  
- Persist derived metrics (look angle, beam id, etc.) so Streamlit and tests can use them.  
- Extend the map components to overlay the satellite path and highlight the active beam.

## Step 5 – Final cleanup
- Update README/help text with the Ukraine focus, beam column, and satellite overlay.  
- Rebuild docs, rerun smoke/unit tests (`AGI_run_<slug>.py`, `app_test.py`, worker tests, Streamlit smoke`), and only then commit the clone.

---
