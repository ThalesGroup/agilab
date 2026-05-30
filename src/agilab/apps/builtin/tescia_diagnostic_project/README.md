# TeSciA Diagnostic Project

`tescia_diagnostic_project` turns a TeSciA-style engineering diagnostic into a
runnable AGILAB app and classroom-ready self-evaluation workflow.

## Purpose

Use this app to convert support/debugging reasoning into structured evidence:
symptoms, assumptions, root cause, stronger fix, regression plan, student score,
and classroom intervention signals.

## What You Learn

- How diagnostic cases are scored deterministically instead of by hidden chat
  state.
- How optional local AI generation is separated from validated scoring.
- How student answers produce `student_score`, feedback, and correction sheets.
- How classroom batches can be split into worker-friendly independent rows.
- How curriculum coverage is audited from explicit metadata.

## Run In AGILAB

1. Select `tescia_diagnostic_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `INSTALL`.
4. Keep the bundled cases for the first run, or select the bundled classroom
   sample.
5. Run `EXECUTE`, then open the TeSciA analysis tabs.

## Expected Inputs

The default input is
`tescia_diagnostic/cases/tescia_diagnostic_cases.json`. Classroom mode accepts a
JSON batch with classroom metadata and a `submissions` list containing
`student_id`, `case_id`, and answer fields.

## Expected Outputs

The app writes per-case diagnostic reports, summary CSV files,
`reduce_summary_worker_<id>.json`, correction sheets, a curriculum coverage
report, and classroom artifacts such as progress, heatmap, needs-attention,
student, curriculum, and intervention CSV files.

## Change One Thing

After the default run works, change one `student_answer` or add one diagnostic
case with a weaker proposed fix. The feedback should identify missing evidence,
wrong fix choice, or missing discriminator regression tests.

## Troubleshooting

If generated cases fail validation, inspect the schema error and rerun with the
bundled deterministic cases. If classroom live data is empty, confirm the latest
classroom artifact bundle exists before relying on the fallback preview.

## Scope

This app is a deterministic diagnostic and teaching workflow. It is not a
general LLM grading service and does not require cloud AI for its default run.
