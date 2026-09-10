# Learning & Assessment

Canonical project: `learning_assessment_project`. Install the standalone app
with `pip install agi-app-learning-assessment`. The former
`agi-app-tescia-diagnostic` package redirects to the new distribution; its
project discovery aliases remain supported. TeSciA names the original
diagnostic collection within the broader learning and assessment workflow.
Existing user workspace data and settings remain in place.

`learning_assessment_project` turns TeSciA-style engineering and data-scientist
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
- **Data science 2026**: read the ML landscape, distinguish algorithm families,
  and diagnose modern ML, RAG, agent, uncertainty, and cost failures.

The bundled bank contains 2 AGILAB cases, 10 mathematics cases, and 24 data-science
cases (12 interview cases plus 12 ML landscape exercises).
Custom or locally generated cases use the **General diagnostics** path unless
they declare another supported path.

### ML landscape: map, explanation and self-check

In **ANALYSIS → Data science 2026**, open **ML landscape — map and practice**.
The [packaged SVG](src/learning_assessment/resources/ml_landscape_axes.svg) separates
eight complementary questions: task, signal, algorithm, representation,
combination, adaptation, training and evaluation.

Choose **Concept family** to read the principle, covered concepts and a common
misconception. **Use this exercise in Self-check** selects its diagnostic case;
open **Self-check** to answer, evaluate and export the correction as usual.
The [reading guide](src/learning_assessment/curriculum/ml_landscape_2026.json)
maps 54 grouped landscape concepts and probability-density foundations to 12 exercises, including classical supervised
models, ensembles, clustering, projection, probabilistic models, representations,
neural architectures, optimization, evaluation and limited-label strategies.
The probability-density module includes an [area plot](src/learning_assessment/resources/ml_probability_density.svg):
a density of 2 s⁻¹ over a 0.1-second interval gives probability 0.2.
Self-check identifies these as worked examples with model answers; explain the
choices and change them to compare feedback.

The map uses French terminology; the guided explanations and diagnostic cases
use English like the existing app. All resources ship inside the package and
work offline. The cases are synthetic reasoning exercises with proposed
regression checks, not executed model benchmarks or proof of operational performance.

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

1. Select `learning_assessment_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `Deploy scheduler & workers`.
4. Keep the bundled cases for the first run, or select the bundled classroom
   sample.
5. Run `RUN`, then open the Learning & Assessment analysis tabs.

## Expected Inputs

The default input is
`learning_assessment/cases/tescia_diagnostic_cases.json`. Classroom mode accepts a
JSON batch with classroom metadata and a `submissions` list containing
`student_id`, `case_id`, and answer fields.

Regression-test entries must be JSON objects. Their optional `automated` and
`discriminator` flags must be JSON booleans (`true` or `false`), not strings or
numbers. An omitted flag means `false`. Invalid entries are rejected before
scoring so malformed data cannot inflate a learner's score.

Custom mathematics curricula may set `required_min_cases_per_id` to a positive
JSON integer. Omitting it keeps the default of one case per curriculum item;
invalid values are rejected instead of silently lowering the coverage threshold.

## Expected Outputs

The app writes per-case diagnostic reports, summary CSV files,
`reduce_summary_worker_<id>.json`, correction sheets, a curriculum coverage
report, and classroom artifacts such as progress, heatmap, needs-attention,
student, curriculum, learning-path, and intervention CSV files. Reports include
`decision_status`, `decision_action`, and decision triggers when a case defines a
deterministic guard.

Lowercase alphanumeric case IDs with single `_` or `-` separators (up to 96
characters) keep their existing artifact filenames. Other nonblank string IDs
use a readable prefix and a stable SHA256 suffix so punctuation or letter-case
differences do not cause reports to overwrite one another. Reports retain the
original case ID, and rerunning the same case reuses its filename. Explicitly
empty or whitespace-only IDs are rejected.

## External Assessment Programs

The bundled cases are a sample, not an exhaustive AI curriculum. A separately
maintained diagnostic bank can add an optional `assessment_program` object to
the existing case-file envelope. No external content is bundled or fetched by
the app. Keep restricted banks and their exported reports in an appropriately
restricted workspace; reports contain source references and assessment rubrics.

Use the existing `data_in` and `files` arguments to select that bank. With
`case_source = "bundled"`, existing matching input files are used as supplied;
the demo bank is seeded only when none exist. Use a dedicated input directory
and an exact filename so unrelated JSON manifests are not scored as case banks.
The interactive teaching demo still displays the bundled cases; external banks
are processed through the worker and inspected in its exported artifacts.

An assessment program declares schema `tescia-assessment-program.v1`, an ID,
title, version, and sources with revision and SHA256 fingerprints. Competencies
have stable IDs, observable outcomes, explicit source sections, prerequisite
IDs, and links to existing diagnostic case IDs. Each can also include a
`practical_assessment`: instructions, expected deliverables, criterion-based
rubric, and optional local artifact references. References are descriptive:
the app neither opens nor executes them. The schema and a complete synthetic
example are exercised in `test/test_tescia_assessment_program.py` and
`test/test_tescia_program_integration.py` in the source checkout.

Do not put external competency IDs in `curriculum_ids`: that field remains
reserved for the existing Mathematics 2026 contract. Program competencies link
to diagnostic cases through `diagnostic_case_ids` instead.

The worker preserves program coverage through its DataFrame transport and
writes content-addressed JSON reports under `assessment_programs/` in both
output locations. Each report includes a SHA256 of the normalized input bank.
Different bank versions remain distinct; repeated identical runs reuse the
same report filename. These are bank-material reports, not per-student grades.

`curriculum_ready` means every declared competency has diagnostic cases and
practical assessment material. Missing material gives `incomplete`; malformed
references, duplicate IDs, prerequisite cycles, and invalid types are errors.
Neither status proves the source inventory is exhaustive: the bank owner must
audit the source-to-competency map and recheck it when source fingerprints
change. Practical mastery remains `not_assessed` until actual learner work is
reviewed against the rubric. A worked answer or a high diagnostic score is not
proof that a lab was executed or a competency was mastered.

## Change One Thing

### Guided drift lesson

Open **ANALYSIS → Guided lesson** with **All paths** or **Data science 2026**
selected. This lesson uses the bundled uncertainty-and-drift case and its
existing deterministic decision evaluator. It runs locally without a model,
network service, or worker deployment.

1. Predict the action for the healthy baseline: drift `0.10`, coverage `0.95`.
2. Select **Run baseline** to record the actual policy decision.
3. Change exactly one observation and predict again. For example, change drift
   to `0.30` while keeping coverage at `0.95`, then select **Run changed input**.
4. Compare the recorded inputs, predictions, decisions, and threshold triggers.
   Explain why the action changed or stayed the same, including what happens at
   equality, then select **Save explanation**.
5. Select **Download lesson evidence** to keep `drift_decision_lesson.json`.
   **Resume saved lesson** accepts this same file, including partially completed
   lessons. Browser-session progress alone does not survive a server restart.

The `agilab.guided_lesson.v1` export contains the source case and evaluator
fingerprints, timestamped predictions and observed decisions, explanation,
review queue, and next-practice suggestion. A checksum covers the payload.
Incorrect predictions select threshold practice; completing the activity keeps
`learner_mastery = "not_assessed"` and the explanation pending human review.

From the AGILAB source checkout, verify a downloaded file with:

```bash
PYTHONPATH=src/agilab/apps/builtin/learning_assessment_project/src \
uv --preview-features extra-build-dependencies run python \
  -m learning_assessment.domain.guided_lesson \
  --verify /path/to/drift_decision_lesson.json
```

Verification checks the checksum, source fingerprints, checkpoint order,
single-input change, replayed decisions, and derived progress. It rejects stale
or inconsistent evidence instead of replacing it. Keep the old export and start
a new lesson when the source case or evaluator changes.

This evidence demonstrates deterministic policy behavior on synthetic inputs.
It does not establish forecasting quality, conformal coverage on a real dataset,
learner identity, independently attested execution, or practical mastery. The
checksum detects changes; it is not a digital signature. The guided sequence is
inspired by the predict/run/explain/check pattern in
[AI Engineering from Scratch's learning skills](https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/skills);
the case and evaluator remain AGILAB-owned.

### Adapt the diagnostic cases

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
