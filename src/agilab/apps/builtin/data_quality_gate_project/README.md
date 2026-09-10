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
arguments for the first run, click `Deploy scheduler & workers`, then click `RUN`.

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
- `rules`: optional named checks on candidate rows (see below).

## Named Candidate Rules

Add rules to the existing `contract_json` file. For example, this contract keeps
the demo's default columns and checks the age and region fields:

```json
{
  "schema": "agilab.app.data_quality_gate.contract.v1",
  "rules": [
    {"id": "adult-age", "column": "age", "kind": "range", "min": 18, "max": 100},
    {"id": "known-region", "column": "region", "kind": "allowed_values",
     "values": ["north", "south", "east", "west"], "severity": "warn"}
  ]
}
```

Each rule needs a unique `id`, a declared `column`, and a `kind`:

| Kind | Additional fields | Meaning |
| --- | --- | --- |
| `required` | none | Reject missing values. |
| `range` | `min` and/or `max` | Inclusive finite numeric bounds; numeric strings and booleans fail. |
| `allowed_values` | non-empty `values` list | Exact string/boolean or numeric membership; `true` does not equal `1`. |
| `format` | `format`: `iso_date` or `email` | Calendar-valid `YYYY-MM-DD`, or basic email syntax. Email checks do not verify mailbox existence or full RFC compliance. |
| `compare` | `other_column`, `operator`: `eq`, `ne`, `lt`, `le`, `gt`, `ge` | Compare two declared columns row by row; types must be compatible. Strings compare lexicographically. |

Rules use `severity: "block"` by default; `"warn"` requires manual review.
Nulls fail by default. `on_null: "skip"` excludes rows with null operands from
the evaluated denominator, except for `required` rules, which cannot skip nulls.
An empty string is a value; missingness follows Pandas parsing/null semantics.
Rules run on the candidate only; the existing baseline/drift checks still run.

Missing columns produce `missing`, and empty or entirely skipped cohorts produce
`skipped`, with no pass rate. Every non-passing rule affects the decision at its
declared severity, so an unevaluated blocking rule cannot silently promote data.
Duplicate JSON keys, unknown kinds/fields, duplicate IDs, undeclared columns and invalid parameters
raise a configuration error. Formats are predefined; contracts do not execute
Python, SQL or user-supplied regular expressions.

## Rule Evidence and Verification

`rule_results.json` uses `agilab.app.data_quality_gate.rule_results.v1`. It records
the evaluator version, normalized rule IDs, status, severity, checked/passed/
failed/skipped counts, failure categories and up to ten failed row positions
per rule. Positions start at zero and exclude the CSV header; omitted positions
are counted. Observed cell values are not copied into this report. The existing
CSV artifacts still contain the dataset and need the same access controls.

Pass rates are fractions over evaluated rows; each row can fail multiple rules,
so summing rule failures does not give the number of distinct invalid records.
The report references the written candidate CSV and normalized `data_contract.json`
by relative path, byte size and SHA-256. `run_manifest.json` hashes the report.
The Markdown report and HTML dashboard show the same rule outcomes.

After a run, verify the persisted artifact bytes from the evidence directory:

```bash
uv run python - <<'PY'
import hashlib, json
from pathlib import Path
root = Path(".")  # directory containing run_manifest.json
manifest = json.loads((root / "run_manifest.json").read_text())
rules = json.loads((root / "rule_results.json").read_text())
for ref in [*manifest["artifacts"].values(), *rules["inputs"].values()]:
    data = (root / ref["path"]).read_bytes()
    assert len(data) == ref["bytes"]
    assert hashlib.sha256(data).hexdigest() == ref["sha256"]
print("Artifact hashes match")
PY
```

This detects changed artifact bytes against the stored hashes; it is not a
signature, independent attestation, or proof that the input is truthful. Replay
through the same app with the same input files and contract to re-evaluate rules.

## Expected Outputs

The worker writes:

- `baseline.csv`
- `candidate.csv`
- `baseline_profile.json`
- `candidate_profile.json`
- `data_contract.json`
- `rule_results.json`
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

## Example Quality Plan

- Review artifact: Review `data_quality_report.md` and `gate_decision.json` first; they explain why a dataset is allowed, warned, or blocked before model work starts.
- Practice change: Change one threshold or one missing-value count in the seeded input and confirm the gate moves from pass to warn or fail with an actionable reason.
- Quality check: A mature run leaves a stable gate report, a concise summary, and no hidden dependency on private data or external services.

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
