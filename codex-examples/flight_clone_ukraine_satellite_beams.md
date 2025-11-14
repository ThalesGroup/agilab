# Flight Clone – Ukraine-Centered With Satellite Beams

This scenario describes (without executing anything) how to create a new app cloned from `flight_project`, add the antenna beam column from `flight_legacy_project`, center the routes over Ukraine, and reuse satellite trajectories from `sat_trajectory_project`.

## 1. Clone baseline (with beam-ready checklist)
1. Use the IDE “Clone app” flow (or `tools/clone_app.py`) to duplicate `src/agilab/apps/flight_project` into your new slug (for example `flight_clone_project`).
2. Immediately run:
   - `tools/generate_runconfig_scripts.py` so PyCharm/CLI entries exist.
   - `log/execute/<app>/AGI_get_distrib_<app>.py` + `AGI_run_<app>.py` to confirm the clone is healthy before edits.
3. While cloning, note every place that references the `flight_project` slug (Pyproject metadata, dataset archive names, `apps/<slug>/test`, `AGI_run_*` scripts) so the subsequent beam-related changes stay in sync.

## 2. Beam column enhancement (mirroring `flight_legacy_project`)
1. **Schema alignment**
   - Add the beam field to `app_settings.toml`, `app_args.py`, `app_args_form.py`, and `_load_dataframe`.
   - Ensure your data source (CSV or synthetic generator) actually emits that column.
2. **Computation logic**
   - Copy the helper (e.g., `compute_beam` / `antenna_id`) from `flight_legacy_project`’s manager/worker.
   - Wire it into the cloned manager so the column is populated before downstream steps.
3. **UI updates**
   - Copy Streamlit widgets (tables, charts, filters) referencing the beam from `flight_legacy_project/pages/...`.
   - Drop them into the EXECUTE/EXPLORE pages of the cloned app so the beam is visible everywhere.
4. **Config + docs**
   - Note the beam column in README/help text, `docs/html/<app>.html`, and any dataset descriptions.
   - After edits, rerun `docs/gen-docs.py` in `thales_agilab` so the published HTML reflects the new field.
5. **Tests**
   - Duplicate beam-related unit tests (`test_flight_legacy_manager.py`, worker tests) into the clone’s test suite, fixing imports to the new slug.
   - Run `app_test.py` + manager/worker tests to ensure the column is computed consistently.

## 3. Recenter data over Ukraine
1. Adjust the source dataset (CSV, synthetic generator, or `AGI_get_distrib_*` script) so the latitude/longitude distributions sit over Ukraine (e.g., bounding box around Kyiv / Dnipro).
2. Update default arguments (`app_settings.toml`, `app_args_form.py`) so map zoom centers on the Ukraine bounding box.
3. Rebuild packaged data archives if the project ships them (e.g., rerun `AGI_get_distrib_<app>.py`).

## 4. Reuse satellite trajectories
1. Identify the trajectory helper exposed by `sat_trajectory_project` (e.g., `sat_trajectory_worker.compute_trajectory`).
2. Import it into the new project (either by direct module import or copying the math and keeping attribution).
3. During preprocessing, call the helper for each flight route so you get a satellite path per flight.
4. Persist any derived metrics (look angle, beam id, etc.) in the dataframe so the UI can reference them.
5. Extend Streamlit maps to overlay trajectories and beam footprints.

## 5. Config + Doc alignment
1. Document the new fields and dependencies in the app README/help page.
2. Regenerate docs via `docs/gen-docs.py` in `thales_agilab` so the HTML picks up the new page sections.
3. Re-run unit tests + smoke tests (`AGI_run_<app>.py`, `app_test.py`, Streamlit smoke) before shipping.

---

### Prompt-first alternative (no clone tool)
If you *don’t* use the IDE clone function, a LLM-guided workflow could still get you to the same endpoint:
1. **Prompt 1 — Project scaffolding**  
   - Ask the assistant to generate a “new app skeleton” that follows the `flight_project` conventions (directory layout, pyproject, run configs).  
   - Manually copy the generated files into a new `apps/<slug>` folder and adjust imports/paths.
2. **Prompt 2 — Beam integration**  
   - Share snippets from `flight_legacy_project` and ask the assistant to produce patched versions of the manager/worker/UI files that include the beam column.  
   - Apply the suggested diff manually (or via `apply_patch`).
3. **Prompt 3 — Ukraine dataset + satellite reuse**  
   - Describe the target flight area and the need to reuse `sat_trajectory_project` helpers; ask for code that injects those computations and centers the dataset.  
   - Review and merge the assistant’s patches.
4. **Prompt 4 — Docs/tests**  
   - Request doc/test updates referencing the new column and region focus; apply them manually.  
   - Run lint/tests yourself to ensure the AI-generated patches compile.

This prompt-only route still demands careful review and manual file edits, but it avoids relying on the built-in clone wizard while following the same enhancement steps.

This plan is intentionally a text-only scenario. No commands were executed when drafting it.
