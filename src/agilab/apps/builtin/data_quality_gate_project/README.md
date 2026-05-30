# Data Quality Gate Project

`data_quality_gate_project` is a built-in AGILAB app for a production-adjacent
data contract and drift gate. It turns the common "is this candidate dataset
safe to promote?" review into a deterministic run with machine-readable
evidence, a human report, and a clear gate decision.

## Purpose

Use this project when you want a fast, understandable proof that AGILAB can
protect an AI/ML workflow before model training or promotion. The app generates
a baseline dataset and a candidate dataset, validates the contract, measures
quality and drift, then writes a gate decision that can be reviewed or wired
into a later CI/promotion step.

## Run In AGILAB

Select `data_quality_gate_project`, then open `ORCHESTRATE`. Keep the default
arguments for the first run, click `INSTALL`, then click `RUN`.

The default configuration creates a deterministic candidate dataset with a small
business distribution shift. The run should complete locally and write the data
quality evidence under `data_quality_gate/evidence`.

## Expected Inputs

No external data, API key, cloud service, notebook, model registry, or LLM is
required. The app generates deterministic baseline and candidate datasets from
the configured seed, row counts, and drift strength.

## Expected Outputs

The worker writes:

- `baseline.csv`
- `candidate.csv`
- `baseline_profile.json`
- `candidate_profile.json`
- `data_contract.json`
- `drift_metrics.csv`
- `gate_decision.json`
- `data_quality_report.md`
- `run_manifest.json`
- `data_quality_gate_summary.json`

The same evidence bundle is mirrored under the app analysis export directory so
generic artifact readers can inspect it later.

## Change One Thing

After the default run works, change only `drift_strength`. Lower values should
move the gate toward `promote`; higher values should move it toward
`manual-review` or `block`. Keep `seed=2026` so the artifact deltas remain easy
to explain.

## Scope

This app is a deterministic data-quality and drift gate example. It is not a
full data observability platform, feature store, model registry, or production
governance system. Its job is to make one candidate dataset review reproducible,
portable, and evidence-backed before another system takes ownership.
