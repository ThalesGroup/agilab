# TeSciA Diagnostic Project

`tescia_diagnostic_project` turns a TeSciA-style engineering diagnostic into a
runnable AGILAB app.

The scoring path is intentionally deterministic. By default the app packages a
small set of diagnostic cases, scores each diagnosis against concrete evidence,
and exports a clear root-cause, better-fix, and regression-plan artifact.
Optionally, the input cases can be generated first by a standalone local AI
engine such as GPT-OSS or Ollama, then validated before the deterministic
scorer runs.

## What It Shows

- how to encode a diagnostic review as data instead of a free-form chat answer
- how to use a standalone local AI engine to draft diagnostic cases without
  making CI or runtime scoring depend on a cloud service
- how to separate symptoms, evidence, weak assumptions, root cause, better fix,
  and regression plan
- how AGILAB can turn a support/debugging method into repeatable evidence
- how a diagnostic app can produce mergeable reduce-contract summaries

## Typical Flow

1. Select `tescia_diagnostic_project` in `PROJECT`.
2. Run `INSTALL` from `ORCHESTRATE`.
3. Run the app with the default sample cases.
4. Inspect exported artifacts under `tescia_diagnostic/reports`.

## Inputs

The default input is a bundled JSON file:

`tescia_diagnostic/cases/tescia_diagnostic_cases.json`

When `case_source = "standalone_ai"`, AGILAB writes a generated input file
instead:

`tescia_diagnostic/cases/tescia_diagnostic_cases.generated.json`

Each case contains:

- a symptom reported by a user or operator
- a proposed diagnosis to challenge
- evidence items with confidence and relevance
- candidate fixes with expected blast radius
- regression tests that should prove the fix

## Outputs

The app writes one artifact bundle per diagnostic case:

- `*_diagnostic_report.json`
- `*_diagnostic_summary.csv`
- `reduce_summary_worker_<id>.json`

The report is the main evidence artifact. The CSV exists for quick tabular
analysis and comparison across cases. Both include `student_score`, a
deterministic 0-100 score combining evidence quality, regression coverage,
selected-fix quality, and whether the case passed the actionable gates.

## Change One Thing

Add a case to the JSON input with one weaker diagnosis and two candidate fixes.
The app should keep the stronger fix only when the evidence supports it and the
regression plan can prove it.

Or switch `Diagnostic case source` to `Generate with standalone AI`, start the
configured local GPT-OSS/Ollama endpoint, and change the generation topic. If
the endpoint is not reachable or returns invalid JSON, the run fails clearly
instead of silently falling back to bundled cases.

## Scope

This app demonstrates the diagnostic method. It is not an autonomous incident
manager and it does not execute remediation commands.
