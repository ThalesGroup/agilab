# TeSciA Diagnostic Project

`tescia_diagnostic_project` turns a TeSciA-style engineering diagnostic into a
runnable AGILAB app and student self-evaluation exercise.

The scoring path is intentionally deterministic. By default the app packages a
small set of diagnostic cases, scores each diagnosis against concrete evidence,
and exports a clear root-cause, better-fix, and regression-plan artifact.
Optionally, the input cases can be generated first by a standalone local AI
engine such as GPT-OSS or Ollama, then validated before the deterministic
scorer runs.

For student use, each case can also include catalog metadata and a
`student_answer` block. AGILAB then grades the learner response against the
reference evidence, best fix, and regression-plan contract, producing a
`student_score`, score band, and targeted feedback.

For classroom use, TeSciA also accepts a classroom submission batch where each
student answer references an exercise id. The batch expands into independent
scoring rows, so local or cluster workers can process submissions concurrently
and export a teacher-facing progress table, heatmap table, and needs-attention
list. It also writes per-student rollups and a deterministic intervention plan
so a teacher can decide who to help, which curriculum area to reteach, and which
exercise to review next. The `Classroom live` ANALYSIS tab reads the latest
exported classroom run first and falls back to the bundled preview when no run
exists yet.

The bundled exercises now include a 2026 French mathematics-program coverage
contract at top-level domain granularity. The contract tracks the official 2026
rollout for cycle 4 `5e`, lycee `seconde` GT, and lycee `premiere`
mathematics paths, then verifies that every declared curriculum id is covered by
at least two TeSciA exercises.

## What It Shows

- how to encode a diagnostic review as data instead of a free-form chat answer
- how to use a standalone local AI engine to draft diagnostic cases without
  making CI or runtime scoring depend on a cloud service
- how to separate symptoms, evidence, weak assumptions, root cause, better fix,
  and regression plan
- how to package diagnostic cases as self-evaluation exercises for students
- how to process classroom submissions as independent cluster-friendly scoring
  units
- how to audit a self-evaluation catalog against a declared mathematics
  curriculum coverage matrix
- how AGILAB can turn a support/debugging method into repeatable evidence
- how a diagnostic app can produce mergeable reduce-contract summaries

## Typical Flow

1. Select `tescia_diagnostic_project` in `PROJECT`.
2. Run `INSTALL` from `ORCHESTRATE`.
3. Open the argument form and review the `Student self-evaluation contract`
   expander.
4. Run the app with the default sample exercises, or edit the case JSON to add a
   learner answer.
   For a live classroom dry run, select `Bundled classroom sample` as the
   diagnostic case source before `EXECUTE`.
5. Inspect exported artifacts under `tescia_diagnostic/reports`, including
   printable correction sheets, classroom progress artifacts, and the
   mathematics coverage report.

## Inputs

The default input is a bundled JSON file:

`tescia_diagnostic/cases/tescia_diagnostic_cases.json`

When `case_source = "standalone_ai"`, AGILAB writes a generated input file
instead:

`tescia_diagnostic/cases/tescia_diagnostic_cases.generated.json`

Each case contains:

- catalog metadata for student-facing exercise lists
- optional `curriculum_ids` for mathematics-program coverage checks
- a symptom reported by a user or operator
- a proposed diagnosis to challenge
- evidence items with confidence and relevance
- candidate fixes with expected blast radius
- regression tests that should prove the fix
- an optional `student_answer` with the learner diagnosis, selected evidence,
  chosen fix, regression checks, and confidence

For live classroom batches, use schema
`agilab.tescia_diagnostic.classroom.v1`. A batch contains classroom metadata and
a `submissions` list. Each submission carries a `student_id`, `case_id`, and
answer object. Student identifiers are anonymized by default in exported
teacher artifacts.

## Outputs

The app writes one artifact bundle per diagnostic case:

- `*_diagnostic_report.json`
- `*_diagnostic_summary.csv`
- `reduce_summary_worker_<id>.json`

The report is the main evidence artifact. The CSV exists for quick tabular
analysis and comparison across cases. Both include `student_score`, a
deterministic 0-100 score combining evidence quality, regression coverage,
selected-fix quality, and whether the case passed the actionable gates.

When a `student_answer` is present, `student_score` becomes the self-evaluation
score for that submitted answer. The report also keeps `case_quality_score` so
the exercise quality remains visible. Summary CSV files include:

- `case_title`
- `difficulty`
- `topic_tags`
- `curriculum_ids`
- `case_quality_score`
- `student_score`
- `self_evaluation_status`
- `self_evaluation_band`
- `feedback_count`

The worker also writes printable correction sheets under
`correction_sheets/`, a `correction_sheets_index.md`, and
`math_program_2026_coverage.json`.

When the input is a classroom batch, the worker also writes:

- `classroom/classroom_run_report.json`
- `classroom/classroom_teacher_summary.md`
- `classroom/classroom_progress.csv`
- `classroom/classroom_heatmap.csv`
- `classroom/classroom_needs_attention.csv`
- `classroom/classroom_students.csv`
- `classroom/classroom_curriculum.csv`
- `classroom/classroom_interventions.csv`

During live or distributed runs, workers can also publish partial progress under
`classroom/partials/` as `classroom_partial_worker_<id>_<source>.json` and
`classroom_partial_worker_<id>_<source>_progress.csv`.

The `Classroom live` ANALYSIS tab reads the latest exported classroom run when
one exists, merges partial worker artifacts while a run is still progressing,
and otherwise falls back to the bundled sample preview. It exposes a manual
refresh control plus optional live refresh and can download the printable
teacher summary.

## Change One Thing

Add a case to the JSON input with one weaker diagnosis and two candidate fixes.
The app should keep the stronger fix only when the evidence supports it and the
regression plan can prove it.

For a student exercise, change only the `student_answer` fields and rerun. The
feedback should identify missing evidence ids, an incorrect selected fix, or
missing discriminator regression tests without calling an LLM.

For a classroom run, either select `Bundled classroom sample`, upload/drop a
classroom JSON batch into `tescia_diagnostic/submissions`, or point the input
directory and file glob at your own classroom file. Inbox files are scored
before the bundled sample when `Read submission inbox` is enabled. With cluster
execution enabled, each submission remains an independent deterministic scoring
unit.

For a 2026 mathematics-program coverage check, change a case `curriculum_ids`
entry and rerun the tests. Unknown ids fail immediately, and missing required
ids appear in `math_program_2026_coverage.json`.

Or switch `Diagnostic case source` to `Generate with standalone AI`, start the
configured local GPT-OSS/Ollama endpoint, and change the generation topic. If
the endpoint is not reachable or returns invalid JSON, the run fails clearly
instead of silently falling back to bundled cases.

## Scope

This app demonstrates the diagnostic method and a deterministic self-evaluation
rubric. It is not an autonomous incident manager and it does not execute
remediation commands.

The 2026 mathematics-program coverage is a top-level-domain contract, not a
complete bank of every possible exercise from the official programs.
