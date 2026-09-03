# TeSciA Diagnostic Project

`tescia_diagnostic_project` turns TeSciA-style engineering and data-scientist
diagnostics into a runnable AGILAB app and classroom-ready self-evaluation
workflow.

This example teaches evidence-based diagnostic reasoning. It does not process
acoustic, vibration, or telemetry signals.

## Purpose

Use this app to convert support/debugging reasoning into structured evidence:
symptoms, assumptions, root cause, stronger fix, regression plan, student score,
and classroom intervention signals. The bundled catalog also includes a 12-case
2026 data-scientist interview evaluation inspired by the legacy QCM format and
current AI-engineering interview practice: modern Python/pandas workflows,
leakage-free model evaluation, scaling choices, RAG retrieval design, agent
memory, LLM evaluation, uncertainty and drift, data-centric limited-label
strategy, open-weight model review, and inference or token-cost optimization.

## Learning Paths

Choose one path in ANALYSIS before opening the catalog or self-check:

- **AGILAB diagnostics**: distinguish symptoms, causes, fixes, and regressions.
- **Mathematics 2026**: audit curriculum coverage and target a second practice round.
- **Data science 2026**: diagnose modern ML, RAG, agent, uncertainty, and cost failures.

The bundled bank contains 2 AGILAB cases, 10 mathematics cases, and 12 data-science
cases. Custom or locally generated cases use the **General diagnostics** path unless
they declare another supported path.

## What You Learn

- How diagnostic cases are scored deterministically instead of by hidden chat
  state.
- How optional local AI generation is separated from validated scoring.
- How student answers produce `student_score`, feedback, and correction sheets.
- How classroom batches can be split into worker-friendly independent rows.
- How curriculum coverage is audited from explicit metadata.
- How progress is aggregated by explicit learning path for teacher review.
- How a drift or coverage gate selects a deterministic normal or fallback action.
- How a data-scientist interview bank can be refreshed as compact
  one-concept, one-trap, one-proof scenarios without relying on outdated
  library APIs or unverified model claims.

## Run In AGILAB

1. Select `tescia_diagnostic_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `Deploy scheduler & workers`.
4. Keep the bundled cases for the first run, or select the bundled classroom
   sample.
5. Run `RUN`, then open the TeSciA analysis tabs.

## Expected Inputs

The default input is
`tescia_diagnostic/cases/tescia_diagnostic_cases.json`. Classroom mode accepts a
JSON batch with classroom metadata and a `submissions` list containing
`student_id`, `case_id`, and answer fields.

## Expected Outputs

The app writes per-case diagnostic reports, summary CSV files,
`reduce_summary_worker_<id>.json`, correction sheets, a curriculum coverage
report, and classroom artifacts such as progress, heatmap, needs-attention,
student, curriculum, learning-path, and intervention CSV files. Reports include
`decision_status`, `decision_action`, and decision triggers when a case defines a
deterministic guard.

## Change One Thing

After the default run works, filter the catalog to `data-scientist candidate`,
change one `student_answer`, or add one diagnostic case with a weaker proposed
fix. The feedback should identify missing evidence, wrong fix choice, or
missing discriminator regression tests.

For the drift exercise, change `drift_score` and `empirical_coverage` across their
declared thresholds. The report must switch deterministically between monitored
serving and abstention to human review.

## Example Quality Plan

- Review artifact: Review the structured diagnostic report first: symptoms, assumptions, root cause, fix, and regression evidence.
- Practice change: Change one symptom or log fragment and confirm the diagnosis updates without losing the required evidence fields.
- Quality check: A mature run turns support reasoning into auditable artifacts instead of a free-form chat transcript.

## Troubleshooting

If generated cases fail validation, inspect the schema error and rerun with the
bundled deterministic cases. If classroom live data is empty, confirm the latest
classroom artifact bundle exists before relying on the fallback preview.

## Scope

This app is a deterministic diagnostic and teaching workflow. It is not a
general LLM grading service, a signal-processing application, or a substitute
for domain-qualified assessment. It does not require cloud AI for its default run.
