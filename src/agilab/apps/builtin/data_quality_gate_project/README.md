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

## What You Learn

The first run shows how AGILAB turns a data-readiness question into replayable
evidence rather than a spreadsheet note. You see the app produce source data,
profile both sides of the comparison, apply a contract, score drift, and write a
decision card that names the failing or passing gate. It is a compact example of
how an experiment workbench can protect a downstream model workflow before
training begins.

## Run In AGILAB

Select `data_quality_gate_project`, then open `ORCHESTRATE`. Keep the default
arguments for the first run, click `INSTALL`, then click `RUN`.

The default configuration creates a deterministic candidate dataset with a
small business distribution shift. The run should complete locally and write
the data quality evidence under `data_quality_gate/evidence`.

To gate your own data, place two CSV files under the AGILAB share and set
`baseline_csv` plus `candidate_csv` to their relative paths. Optional
`contract_json` and `thresholds_json` files can override the default column
contract and promotion thresholds without editing Python code.

## Expected Inputs

No external data, API key, cloud service, notebook, model registry, or LLM is
required for the first run. The app can also read user-provided baseline and
candidate CSV files from the AGILAB share. Contract JSON accepts:

- `columns`: mapping from column name to `{kind, role, required, drift}`.
- `allow_unexpected_columns`: whether extra candidate columns are accepted.
- `target_column`, `identifier_columns`, and `leakage_name_patterns`.
- `thresholds`: optional overrides for PSI, KS, null-rate, duplicate-rate, row
  count, mean-shift, and category-delta thresholds.

## Expected Outputs

The worker writes:

- `baseline.csv`
- `candidate.csv`
- `baseline_profile.json`
- `candidate_profile.json`
- `data_contract.json`
- `drift_metrics.csv`
- `gate_decision.json`
- `decision_card.json`
- `data_quality_dashboard.html`
- `input_sources.json`
- `data_quality_report.md`
- `run_manifest.json`
- `data_quality_gate_summary.json`

The same evidence bundle is mirrored under the app analysis export directory so
generic artifact readers can inspect it later.

## Change One Thing

After the default run works, change only one thing:

- Raise or lower `drift_strength` to see the synthetic decision move.
- Or set `baseline_csv` and `candidate_csv` to your own share-relative files.
- Or set `thresholds_json` to tighten/relax the gate without code changes.

Keep `seed=2026` for synthetic comparisons so artifact deltas remain easy to
explain.

## Troubleshooting

If custom CSV inputs fail, first run the defaults again to confirm the app and
worker install are healthy. Then check that `baseline_csv`, `candidate_csv`,
`contract_json`, and `thresholds_json` are relative to the AGILAB share, not to
the repository checkout. Contract errors usually mean a required column is
missing, a numeric column was parsed as text, or a threshold override used a name
that is not present in the generated `data_contract.json`.

## Scope

This app is a deterministic data-quality and drift gate example. It is not a
full data observability platform, feature store, model registry, or production
governance system. Its job is to make one candidate dataset review reproducible,
portable, and evidence-backed before another system takes ownership.
