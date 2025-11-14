# Scenario 2 – Runtime Prompting (Agent-Guided Build)
Narrative only; no commands executed.

## Step 1 – Describe the target
- Prompt the agent: “Create a `flight_project`-style app centered over Ukraine with antenna beams (like `flight_legacy_project`) and satellite trajectories (from `sat_trajectory_project`).”  
- Let the agent outline the directory tree, pyproject metadata, run configs, and dataset notes. Apply those patches manually to generate the base app.

## Step 2 – Ask for beam schema/computation
- Provide the relevant files from `flight_legacy_project` and prompt the agent to merge the schema + helper logic.  
- Review the diff it produces, apply it, and check that your dataset now includes the beam column.

## Step 3 – Ask for Ukraine dataset + satellite hooks
- Prompt: “Inject the Ukraine-centric dataset changes and reuse the satellite trajectory helper.”  
- Apply the suggested edits that adjust bounding boxes, call the helper, and persist the new metrics.

## Step 4 – Ask for UI/docs/tests
- Prompt the agent to update Streamlit pages, docs, and unit tests to reference the new column and satellite overlay.  
- Apply the patches manually, regenerate docs, and run the tests yourself.

## Step 5 – Runtime validation loop
- Ask the agent for smoke-test commands, run them locally, then feed the logs back if adjustments are needed.  
- Iterate until all suggested tests pass, then commit.

This illustrates a pure prompt-driven approach (no clone button) while staying aligned with the structured format used in Scenario 1.
