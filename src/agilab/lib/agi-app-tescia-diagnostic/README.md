# agi-app-tescia-diagnostic

[![PyPI version](https://img.shields.io/pypi/v/agi-app-tescia-diagnostic.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-tescia-diagnostic/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-tescia-diagnostic.svg)](https://pypi.org/project/agi-app-tescia-diagnostic/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-tescia-diagnostic)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-tescia-diagnostic` packages the `tescia_diagnostic_project`
AGILAB app. It is a diagnostic-method example that turns weak assumptions,
evidence, candidate fixes, and regression plans into structured artifacts.
It can also be used as a student self-evaluation exercise: cases expose
student-facing metadata and optional submitted answers that are graded with a
deterministic rubric.
For classroom use, a submission batch can reference exercise ids and expand
into independent scoring rows for local or cluster execution.

## Purpose

Use this package to test a TeSciA-style engineering diagnostic workflow. The
default path scores bundled cases deterministically; optional local AI engines
can draft new cases, but validated scoring remains explicit and reproducible.
When a case contains `student_answer`, the exported `student_score` reflects the
learner response while `case_quality_score` keeps the reference exercise score.
Bundled cases also carry a 2026 French mathematics-program coverage matrix at
top-level domain granularity for the 2026-2027 rollout, with at least two
exercises required per declared curriculum id.
Classroom batches export anonymized teacher artifacts: progress, heatmap,
needs-attention, curriculum-level CSV files, and a printable teacher summary.

## Installed Project

The distribution name is `agi-app-tescia-diagnostic`; the AGILAB
project name is `tescia_diagnostic_project`. The package exposes both
`tescia_diagnostic` and `tescia_diagnostic_project` through the `agilab.apps`
entry point group, so `AgiEnv(app="tescia_diagnostic_project")` resolves the
project without a monorepo checkout.

## Install

```bash
pip install agi-app-tescia-diagnostic
```

The `agi-apps` umbrella pulls this package on Python 3.13+ because the TeSciA
diagnostic app uses the same Python floor as its packaged worker environment.
Install it directly when validating the diagnostic app package from an index or
a locally built wheel.

## Run In AGILAB

Select `tescia_diagnostic_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE` with bundled cases. Inspect the exported reports under `ANALYSIS` or
the project output directory. The argument form includes the student-answer JSON
contract used for self-evaluation.
For a classroom batch, select `Bundled classroom sample` in ORCHESTRATE, or
place a `agilab.tescia_diagnostic.classroom.v1` JSON file in the input
directory and set the file glob to that payload.

## Expected Inputs

The default input is a bundled JSON case file with exercise metadata. Optional
local-AI generation requires a configured local endpoint and fails closed if the
generated JSON does not match the expected schema. Student submissions can be
added through a `student_answer` object in the case JSON. Mathematics cases can
also include `curriculum_ids`; unknown ids are rejected by the coverage helper.
Classroom submission files contain `classroom` metadata plus a `submissions`
list of `student_id`, `case_id`, and answer objects. Student ids are anonymized
by default in teacher artifacts.

## Expected Outputs

The app writes diagnostic reports, summary CSV files, reducer summaries, and a
`student_score` field that records whether the diagnosis, better fix, and
regression plan are supported by evidence. With a submitted answer, the report
also exports a score band and targeted feedback for missing evidence, fix, or
regression-test selections.
The worker also writes printable correction sheets and
`math_program_2026_coverage.json` so a catalog can prove whether every declared
2026 top-level mathematics curriculum id meets the minimum exercise count.
For classroom batches it also writes:

- `classroom/classroom_run_report.json`
- `classroom/classroom_teacher_summary.md`
- `classroom/classroom_progress.csv`
- `classroom/classroom_heatmap.csv`
- `classroom/classroom_needs_attention.csv`
- `classroom/classroom_curriculum.csv`

During live or distributed runs, workers can also publish partial progress under
`classroom/partials/` as `classroom_partial_worker_<id>_<source>.json` and
`classroom_partial_worker_<id>_<source>_progress.csv`. The ANALYSIS classroom tab
reads the latest completed run artifact when present, merges partial worker
artifacts while a run is still progressing, falls back to the bundled preview
otherwise, and includes manual plus optional live refresh.

## Change One Thing

Add one diagnostic case with a deliberately weak proposed fix and two candidate
regression tests. The app should keep the stronger fix only when the evidence
and tests support it.

For mathematics-program coverage, add or remove a `curriculum_ids` entry and
run the focused TeSciA tests. Missing required ids, undercovered ids, and
invented ids fail the coverage contract.

For classroom mode, upload/drop a classroom JSON batch into
`tescia_diagnostic/submissions`, or add a second submission for the same
exercise with a different `student_id`; the exported heatmap should add a new
row without changing the exercise definition. Inbox files are scored before the
bundled sample when `Read submission inbox` is enabled.

## Scope

This is a repeatable diagnostic example. It does not execute remediation
commands, replace incident management, or silently trust model-generated
content.

The mathematics-program coverage is a domain-level audit contract, not a full
official exercise bank.
