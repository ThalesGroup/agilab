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

This app shows how to turn a subjective data review into a repeatable AGILAB
stage contract. You learn how manager arguments select input files and
thresholds, how the worker produces normalized evidence, and how a reducer can
summarize pass/fail status without hiding the detailed artifact trail. The
important pattern is reusable: keep the business decision small, keep the raw
evidence inspectable, and export a manifest that another tool can consume.

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

If the app reports missing CSV files, confirm that `baseline_csv` and
`candidate_csv` are relative to the AGILAB share, not absolute paths on your
desktop. If the gate fails on the default synthetic run, inspect
`gate_decision.json` first: the failure is usually an intentional drift signal,
not an execution error. If your own data fails schema validation, start by
running with the default contract, then add only the column rules you need.

## Scope

This app is a deterministic data-quality and drift gate example. It is not a
full data observability platform, feature store, model registry, or production
governance system. Its job is to make one candidate dataset review reproducible,
portable, and evidence-backed before another system takes ownership.
