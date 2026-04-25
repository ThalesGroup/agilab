[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)

# AGILAB

AGILAB is an open-source platform for reproducible AI and ML workflows.

The core idea is simple: keep one app on one control path from setup to run to
visible analysis instead of splitting the workflow across ad hoc scripts,
environments, and notebooks.

AGILAB is best evaluated as an AI/ML experimentation workbench, not as a
replacement for mature orchestration or production MLOps platforms. Its value is
keeping project setup, environment management, execution, and result analysis on
one coherent path before hardened assets move to deployment-focused systems.

## Quick Start

[![AGILAB Space](https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge)](https://huggingface.co/spaces/jpmorard/agilab)
[![agi-core notebook](https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge)](https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb)

The public AGILAB Space opens the lightweight built-in `flight_project` path by
default. Use it for the first proof that the web UI, execution path, and
analysis page work. The UAV Relay Queue demo (`uav_relay_queue_project`) is the
separate advanced RL/full-tour scenario referenced in the docs; it is not the
default landing app.

## First Run

Run the installable product path with the built-in `flight_project`:

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py
```

Follow the in-app pages from `PROJECT` to `ANALYSIS`. Success means fresh output
under `~/log/execute/flight/` and a visible analysis result. To collect the same
check as JSON:

```bash
uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --json
```

The JSON proof writes a stable `run_manifest.json` under
`~/log/execute/flight/`. That manifest records the proof command, Python and
platform context, active app, timing, artifact references, and validation
status so the wizard, compatibility report, KPI bundle, and release-decision
gate share one factual run record.

This path is intentionally CLI-first. PyCharm run configurations are maintained
for contributors who want IDE debugging, but they are not required for install,
execution, or analysis. The same flows are available from the web UI, shell
commands, and checked-in wrappers.

## Install The Published Package

```bash
pip install agilab
agilab
```

This is the thinnest public entry point. Use it for a quick package-level check.
For the most representative first proof, prefer the source-checkout
`flight_project` path above because it exercises the same app installation,
execution, and analysis flow documented in the web UI.

## Notebook Pipeline Import

AGILAB now exposes a notebook-to-pipeline import report:

```bash
uv --preview-features extra-build-dependencies run python tools/notebook_pipeline_import_report.py --compact
```

The report reads a checked-in `.ipynb`, projects markdown cells, code cells,
import hints, execution-count metadata, and artifact references into AGILAB
pipeline-step metadata, and writes a round-tripped JSON proof plus a richer
`lab_steps.toml` preview. The existing `PIPELINE` notebook upload path now uses
the same importer. This is a `not_executed_import` contract: it proves
notebook-to-pipeline import shape without executing notebook cells or claiming
a single-kernel union environment.

## Reduce Contract

AGILAB now exposes a first-class `agi_node` reduce contract for distributed
work-plan results. `ReducePartial` captures worker outputs, `ReduceContract`
declares merge semantics and validation hooks, and `ReduceArtifact` serializes
the named reducer result with a stable schema.

Existing apps can keep their app-owned aggregation while they migrate. The
`execution_pandas_project` and `execution_polars_project` built-in benchmark
apps, plus the user-facing `meteo_forecast_project`, `uav_queue_project`, and
`uav_relay_queue_project`, now emit named `reduce_summary_worker_<id>.json`
`ReduceArtifact` files. The public reducer benchmark validates 8 partials /
80,000 synthetic items in `0.003s` against a `5.0s` target:

```bash
uv --preview-features extra-build-dependencies run python tools/reduce_contract_benchmark.py --json
```

The compact public KPI evidence bundle reports this as
`reduce_contract_adoption_guardrail`. The
remaining scope is future adoption discipline, not the shared reducer interface,
migrated artifacts, artifact surfacing, or the public benchmark.

## Multi-app DAG Contract

AGILAB now includes a first cross-app orchestration contract. The checked-in
sample `docs/source/data/multi_app_dag_sample.json` links `uav_queue_project`
to `uav_relay_queue_project` through a `queue_metrics` artifact handoff, and:

```bash
uv --preview-features extra-build-dependencies run python tools/multi_app_dag_report.py --compact
```

validates schema, built-in app nodes, acyclic dependencies, and artifact
handoffs. This is a contract/report baseline, not a full cross-app runner yet.

## Global Pipeline DAG Report

AGILAB also exposes the first product-level DAG evidence view. It combines the
multi-app DAG sample with the checked-in `pipeline_view.dot` files for
`uav_queue_project` and `uav_relay_queue_project`:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_dag_report.py --compact
```

The report emits one read-only graph with app nodes, app-local pipeline steps,
and the cross-app `queue_metrics` artifact edge. It does not execute the apps,
schedule retries, or provide operator UI state yet.

## Global DAG Execution Plan

The next runner-facing contract turns that graph into ordered runnable units
without executing them:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_execution_plan_report.py --compact
```

The report marks `queue_baseline` and `relay_followup` as
`pending/not_executed`, records `relay_followup` as blocked on the
`queue_metrics` artifact from `queue_baseline`, and keeps provenance back to
the multi-app DAG sample plus each app-local `pipeline_view.dot`.

## Global DAG Runner State

AGILAB now projects that execution plan into read-only dispatch and operator
state without executing apps:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_runner_state_report.py --compact
```

The report marks `queue_baseline` as `runnable` and `relay_followup` as
`blocked`, models `pending -> runnable -> completed/failed` plus retry and
partial-rerun transitions, and records operator-facing readiness messages with
provenance back to the execution plan, DAG sample, and `pipeline_view.dot`
files. Full live operator UI remains future work.

## Global DAG Dispatch Persistence

AGILAB also includes the first persisted dispatch-state proof:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_dispatch_state_report.py --compact
```

The report writes and reads back a persisted run-state JSON proof. It records
`queue_baseline completed`, publishes `queue_metrics`, moves
`relay_followup runnable`, and keeps timestamps, retry counters,
partial-rerun flags, operator messages, and provenance. This is durable state
transition evidence; the follow-on smoke below covers the real app-entry
dispatch path across both DAG units.

## Global DAG App Dispatch Smoke

AGILAB now executes the two-unit global DAG through checked-in app entries:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_app_dispatch_smoke_report.py --compact
```

The report runs real `queue_baseline` execution through `uav_queue_project`,
then real `relay_followup` execution through `uav_relay_queue_project`. It
writes `queue_metrics`, `relay_metrics`, and reducer artifacts into a temp
workspace, persists the dispatch-state JSON, and records real queue_baseline
and relay_followup execution. This is a full-DAG app-dispatch smoke, not live
operator UI.

## Global DAG Operator State

AGILAB also projects that persisted full-DAG dispatch state into an
operator-facing state contract:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_operator_state_report.py --compact
```

The report reads the persisted full-DAG dispatch smoke state, exposes
operator-visible state for both completed units, shows the queue-to-relay
artifact handoff, and lists retry/partial-rerun actions available for future
operator flows. This is a state contract, not live UI.

## Global DAG Dependency View

AGILAB now projects the operator-state proof into a cross-app dependency view:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_dependency_view_report.py --compact
```

The report exposes upstream/downstream dependency visualization for
`queue_baseline -> relay_followup`, including the `queue_metrics` artifact
edge, producer/consumer apps, adjacency lists, artifact flow, and linkage back
to the persisted operator-state proof. This is a dependency-view contract, not
a live UI component.

## Global DAG Live State Updates

AGILAB now projects the dependency view into live orchestration-state updates:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_live_state_updates_report.py --compact
```

The report emits a deterministic update stream for the full DAG: graph-ready,
unit-state, artifact-state, dependency-state, and operator-action refresh
payloads for `queue_baseline`, `relay_followup`, and `queue_metrics`. This is
an update-payload contract, not a streaming service or UI renderer.

## Global DAG Operator Actions

AGILAB now executes persisted operator action requests through real app-entry
replays:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_operator_actions_report.py --compact
```

The report reads live-state update payloads, accepts `queue_baseline:retry` and
`relay_followup:partial_rerun`, runs the corresponding queue and relay app
entries, and persists the action outcomes plus output artifacts. This is retry
and partial-rerun action execution, not a UI control surface.

## Global DAG Operator UI

AGILAB now renders the persisted global-DAG state into operator UI components:

```bash
uv --preview-features extra-build-dependencies run python tools/global_pipeline_operator_ui_report.py --compact
```

The report builds status, unit-card, dependency-graph, update-timeline,
action-control, and artifact-table components, writes a static HTML proof, and
verifies those operator UI components render persisted state and support
operator actions. The components are reusable evidence; product page placement
can evolve without changing the contract.

## Evaluation Snapshot

CODEX 5.5 working scores, not production MLOps claims:

| KPI | Score | Evidence | Limit |
|---|---|---:|---|
| Ease of adoption | `3.5 / 5` | Hosted Space, CLI-first local `flight_project` path, opt-in installer tests, local smoke: `5.86s` vs `600s`, and fresh external-machine smoke on April 25, 2026: `26.87s` vs `600s`. | Validated locally, on one external macOS machine, on AI Lightning, on Hugging Face, on one bare-metal cluster, and on one VM-based cluster. Remaining validation gap: Azure, AWS, and GCP cloud deployments. |
| Research experimentation | `4.0 / 5` | Templates, isolated `uv`, `lab_steps.toml`, MLflow-tracked runs, analysis pages, shared `agi_node` reduce contract, surfaced pandas/polars benchmark, flight, meteo forecast, and UAV queue-family reduce artifacts, a non-template built-in app guardrail, public reduce benchmark: `0.003s` vs `5.0s`, multi-app DAG report, global pipeline DAG report, global execution-plan report, global runner-state report, global dispatch-state persistence report, global app-dispatch smoke report, global operator-state report, global dependency-view report, global live-update report, global operator-action report, global operator-UI report, and notebook-to-pipeline import report. | Future apps/templates must opt in when they produce concrete merge outputs. |
| Engineering prototyping | `4.0 / 5` | `app_args_form.py`, `pipeline_view`, reusable history, analysis-page templates, a guided in-product first-proof wizard, stable `run_manifest.json` evidence consumed by the KPI bundle, the multi-app DAG contract, a read-only global pipeline graph, pending execution-plan units, read-only runnable/blocked operator state, persisted queue-to-relay dispatch-state transition proof, real two-unit global DAG app dispatch smoke, operator-visible retry/partial-rerun action state, cross-app upstream/downstream dependency visualization, deterministic full-DAG live-update payloads, retry/partial-rerun real app-entry action replay, reusable operator UI components, and the notebook-to-pipeline import contract. | Additional external replication beyond the current public first-proof paths is not claimed. |
| Production readiness | `3.0 / 5` | Release preflight, CI/coverage, service health gates, connector-registry release paths, provenance-tagged manifest-indexing, cross-release, and cross-run release-decision page export, security hardening checklist. | Production model serving, feature stores, online monitoring, drift detection, and enterprise governance are outside scope. |
| Overall public evaluation | `3.6 / 5` | Mean of the four scored public KPIs: `(3.5 + 4.0 + 4.0 + 3.0) / 4 = 3.625`. Cross-KPI evidence bundle and workflow-backed compatibility report documented in the compatibility matrix. | Alpha-stage software; not a production MLOps platform. |

## Read Next

- Demo chooser: https://thalesgroup.github.io/agilab/demos.html
- Quick start: https://thalesgroup.github.io/agilab/quick-start.html
- Notebook quickstart: https://thalesgroup.github.io/agilab/notebook-quickstart.html
- Documentation: https://thalesgroup.github.io/agilab
- Flight project guide: https://thalesgroup.github.io/agilab/flight-project.html
- Source repository: https://github.com/ThalesGroup/agilab
- Issues: https://github.com/ThalesGroup/agilab/issues
