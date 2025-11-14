# Flight Clone via Prompted Agent (Runtime-Oriented Scenario)

This scenario outlines how a future agent-driven workflow might replace the “Clone app” button entirely—building the new project, applying beam/trajectory logic, and validating outputs through conversational prompts at runtime. It is a text-only concept; nothing here was executed.

## Phase 1 – Describe the target
1. **Prompt**: “I need a new AGILab app derived from `flight_project` but centered over Ukraine, with antenna beam columns like `flight_legacy_project`, and satellite trajectories from `sat_trajectory_project`.”  
2. **Agent response**: propose the directory layout, pyproject metadata, run configurations, and initial dataset tweaks.
3. **Human action**: copy/paste or apply the generated patch set to create the `apps/flight_clone_project` skeleton.

## Phase 2 – Schema & computation via prompts
1. **Prompt**: “Add the beam schema and computation logic from `flight_legacy_project` into this new app; here are the relevant files…”  
2. **Agent response**: produce diffs for `app_settings.toml`, `app_args.py`, `_load_dataframe`, and the manager/worker methods.  
3. **Human action**: review the diffs, apply them, and confirm that datasets now emit the beam column.

## Phase 3 – UI + docs via prompts
1. **Prompt**: “Mirror the Streamlit changes that surface the beam column, and update docs/test references.”  
2. **Agent response**: supply patches for `pages/▶️ EXECUTE.py`, `pages/EXPLORE.py`, README/help files, and tests.  
3. **Human action**: merge the patches, regenerate docs/tests locally.

## Phase 4 – Satellite integration via prompts
1. **Prompt**: “Integrate the satellite trajectory helper from `sat_trajectory_project` so each flight row shows the expected path over Ukraine.”  
2. **Agent response**: provide code for importing the helper, invoking it in preprocessing, and extending visualizations.  
3. **Human action**: apply changes, seed new datasets (or remote fetchers), rerun tests.

## Phase 5 – Runtime validation
1. **Prompt**: “Generate smoke-test scripts and AGI_run scenarios to prove the clone works.”  
2. **Agent response**: deliver test scripts, CLI commands, and expected outputs.  
3. **Human action**: execute the suggested commands, feed logs back to the agent if corrections are needed.

In this agent-centric future, the cloning step is effectively replaced by a conversational loop—the agent synthesizes patches, the developer validates/runs them, and together they reach parity with the legacy clone (beam columns, Ukraine focus, satellite integration) without relying on a dedicated “Clone app” wizard.

Again, this is a narrative scenario only; no commands were executed while drafting it.
