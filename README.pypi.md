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

## Reduce Contract

AGILAB now exposes a first-class `agi_node` reduce contract for distributed
work-plan results. `ReducePartial` captures worker outputs, `ReduceContract`
declares merge semantics and validation hooks, and `ReduceArtifact` serializes
the named reducer result with a stable schema.

Existing apps can keep their app-owned aggregation while they migrate. The
`execution_pandas_project` and `execution_polars_project` built-in benchmark
apps, plus the user-facing `uav_queue_project` and `uav_relay_queue_project`,
now emit named `reduce_summary_worker_<id>.json` `ReduceArtifact` files. The
public reducer benchmark validates 8 partials / 80,000 synthetic items in
`0.003s` against a `5.0s` target:

```bash
uv --preview-features extra-build-dependencies run python tools/reduce_contract_benchmark.py --json
```

The Release Decision evidence view discovers those reduce artifacts, validates
their schema, and shows reducer name, partial count, artifact path, benchmark
row/source/execution fields, and UAV queue-family packet/PDR fields when
present. The remaining scope is wider adoption beyond the benchmark pair and
the first two user-facing apps, not the shared reducer interface, migrated
artifacts, artifact surfacing, or the public benchmark.

## Evaluation Snapshot

CODEX 5.5 working scores, not production MLOps claims:

| KPI | Score | Evidence | Limit |
|---|---|---:|---|
| Ease of adoption | `3.5 / 5` | Hosted Space, CLI-first local `flight_project` path, opt-in installer tests, local smoke: `5.86s` vs `600s`, and fresh external-machine smoke on April 25, 2026: `26.87s` vs `600s`. | Validated locally and on one external macOS machine; broader OS/network certification is not claimed. |
| Research experimentation | `4.0 / 5` | Templates, isolated `uv`, `lab_steps.toml`, MLflow-tracked runs, analysis pages, shared `agi_node` reduce contract, surfaced pandas/polars benchmark and UAV queue-family reduce artifacts, and public reduce benchmark: `0.003s` vs `5.0s`. | Broader app migrations beyond the benchmark pair and first two user-facing apps are not complete. |
| Engineering prototyping | `4.0 / 5` | `app_args_form.py`, `pipeline_view`, reusable history, analysis-page templates, and tested in-product first-proof onboarding. | Additional external replication and full guided-wizard polish are not claimed. |
| Production readiness | `3.0 / 5` | Release preflight, CI/coverage, service health gates, release-decision page, security hardening checklist. | Production model serving, feature stores, online monitoring, drift detection, and enterprise governance are outside scope. |
| Overall public evaluation | `3.6 / 5` | Mean of the four scored public KPIs: `(3.5 + 4.0 + 4.0 + 3.0) / 4 = 3.625`. Cross-KPI evidence bundle documented in the compatibility matrix. | Alpha-stage software; not a production MLOps platform. |

## Read Next

- Demo chooser: https://thalesgroup.github.io/agilab/demos.html
- Quick start: https://thalesgroup.github.io/agilab/quick-start.html
- Notebook quickstart: https://thalesgroup.github.io/agilab/notebook-quickstart.html
- Documentation: https://thalesgroup.github.io/agilab
- Flight project guide: https://thalesgroup.github.io/agilab/flight-project.html
- Source repository: https://github.com/ThalesGroup/agilab
- Issues: https://github.com/ThalesGroup/agilab/issues
