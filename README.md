<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/pypi-version-agilab.svg" alt="PyPI version" /></a>
  <a href="https://opensource.org/licenses/BSD-3-Clause"><img src="https://img.shields.io/badge/License-BSD%203--Clause-blue.svg" alt="License: BSD 3-Clause" /></a>
  <a href="https://thalesgroup.github.io/agilab"><img src="https://img.shields.io/badge/Documentation-online-brightgreen.svg" alt="Documentation" /></a>
  <a href="https://github.com/ThalesGroup/agilab"><img src="https://img.shields.io/github/stars/ThalesGroup/agilab.svg" alt="GitHub stars" /></a>
</p>

<details>
<summary>More project badges</summary>

<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/pyversions/agilab.svg" alt="Supported Python Versions" /></a>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/dm/agilab" alt="PyPI downloads" /></a>
  <a href="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml"><img src="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/ThalesGroup/agilab/issues"><img src="https://img.shields.io/github/issues/ThalesGroup/agilab" alt="Open issues" /></a>
  <a href="https://github.com/ThalesGroup/agilab/pulse"><img src="https://img.shields.io/github/commit-activity/m/ThalesGroup/agilab.svg" alt="Commit activity" /></a>
  <a href="tools/agent_workflows.md"><img src="https://img.shields.io/badge/Agents-codex%20%26%20claude%20%26%20aider%20%26%20opencode-0F766E" alt="Agents Codex Claude Aider and OpenCode" /></a>
  <a href=".codex/skills/README.md"><img src="badges/skills-codex.svg" alt="Codex skills" /></a>
  <a href=".claude/skills/README.md"><img src="badges/skills-claude.svg" alt="Claude skills" /></a>
  <a href="docs/source/environment.rst"><img src="https://img.shields.io/badge/Language-python%20free--threaded%20%26%20cythonized-5B6CFF" alt="Language Python free-threaded and Cythonized" /></a>
  <a href="https://github.com/ThalesGroup/agilab/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome" /></a>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/format/agilab" alt="PyPI format" /></a>
  <a href="https://github.com/ThalesGroup/agilab"><img src="https://img.shields.io/github/repo-size/ThalesGroup/agilab" alt="Repo size" /></a>
  <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Black code style" /></a>
  <a href="https://orcid.org/0009-0003-5375-368X"><img src="https://img.shields.io/badge/ORCID-0009--0003--5375--368X-A6CE39?logo=orcid" alt="ORCID" /></a>
</p>
<p>
  <a href="https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml"><img src="https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml/badge.svg?branch=main" alt="Coverage workflow" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agilab.svg" alt="agilab coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-gui"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-gui.svg" alt="agi-gui coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-env"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-env.svg" alt="agi-env coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-node"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-node.svg" alt="agi-node coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-cluster"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-cluster.svg" alt="agi-cluster coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-core"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-core.svg" alt="agi-core coverage" /></a>
</p>

</details>

# AGILAB

AGILAB is an open-source platform for reproducible AI and ML workflows.

The core idea is simple: keep one app on one control path from setup to run to visible analysis instead of splitting the workflow across ad hoc scripts, environments, and notebooks.

AGILAB is best evaluated as an AI/ML experimentation workbench, not as a replacement for mature orchestration or production MLOps platforms. Its value is keeping project setup, environment management, execution, and result analysis on one coherent path before hardened assets move to deployment-focused systems.

## [Quick Start](https://thalesgroup.github.io/agilab/quick-start.html)

<p>
  <a href="https://huggingface.co/spaces/jpmorard/agilab"><img src="https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge" alt="AGILAB Space" /></a>
  <a href="https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb"><img src="https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge" alt="agi-core notebook" /></a>
</p>

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

Follow the in-app pages from `PROJECT` to `ANALYSIS`. Success means fresh output under `~/log/execute/flight/` and a visible analysis result. To collect the same check as JSON:

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
commands, and checked-in wrappers under `tools/run_configs/`.

To keep the first install bounded, AGILAB does not run the full test suite by
default. Add `--test-root`, `--test-apps`, or `--test-core` only when you want
installer-time validation rather than the fastest first proof.

## Published Package

The PyPI package is the thinnest public entry point:

```bash
pip install agilab
agilab
```

Use it for a quick package-level check. For the most representative first proof,
prefer the source-checkout `flight_project` path above because it exercises the
same app installation, execution, and analysis flow documented in the web UI.

## Reduce Contract

AGILAB now exposes a first-class `agi_node` reduce contract for distributed
work-plan results. `ReducePartial` captures worker outputs, `ReduceContract`
declares merge semantics and validation hooks, and `ReduceArtifact` serializes
the named reducer result with a stable schema.

Existing apps can keep their app-owned aggregation while they migrate. The
`execution_pandas_project` and `execution_polars_project` built-in benchmark
apps, plus the user-facing `flight_project`, `meteo_forecast_project`,
`uav_queue_project`, and `uav_relay_queue_project`, now emit named
`reduce_summary_worker_<id>.json` `ReduceArtifact` files. The public reducer
benchmark validates 8 partials / 80,000 synthetic items in `0.003s` against a
`5.0s` target:

```bash
uv --preview-features extra-build-dependencies run python tools/reduce_contract_benchmark.py --json
```

The Release Decision evidence view discovers those reduce artifacts, validates
their schema, and shows reducer name, partial count, artifact path, benchmark
row/source/execution fields, flight trajectory row/aircraft/speed fields,
meteo forecast MAE/RMSE/MAPE fields, and UAV queue-family packet/PDR fields
when present.

A repository guardrail now requires every non-template built-in app to expose a
reducer contract. `mycode_project` is the only template-only exemption because
it has placeholder worker hooks and no concrete merge output; future apps or
templates must opt in when they start producing durable worker summaries.
The compact public KPI evidence bundle reports this as
`reduce_contract_adoption_guardrail`. The
remaining scope is future adoption discipline, not the shared reducer interface,
migrated artifacts, artifact surfacing, or the public benchmark.

## Evaluation Snapshot

CODEX 5.5 working scores, not production MLOps claims:

| KPI | Score | Evidence | Limit |
|---|---|---:|---|
| Ease of adoption | `3.5 / 5` | Hosted Space, CLI-first local `flight_project` path, opt-in installer tests, local smoke: `5.86s` vs `600s`, and fresh external-machine smoke on April 25, 2026: `26.87s` vs `600s`. | Validated locally, on one external macOS machine, one bare-metal cluster, and one VM-based cluster. Remaining validation gap: Azure, AWS, and GCP cloud deployments. |
| Research experimentation | `4.0 / 5` | Templates, isolated `uv`, `lab_steps.toml`, MLflow-tracked runs, analysis pages, shared `agi_node` reduce contract, surfaced pandas/polars benchmark, flight, meteo forecast, and UAV queue-family reduce artifacts, a non-template built-in app guardrail, and public reduce benchmark: `0.003s` vs `5.0s`. | Future apps/templates must opt in when they produce concrete merge outputs. |
| Engineering prototyping | `4.0 / 5` | `app_args_form.py`, `pipeline_view`, reusable history, analysis-page templates, a guided in-product first-proof wizard, and stable `run_manifest.json` evidence consumed by the KPI bundle. | Additional external replication beyond the current public first-proof paths is not claimed. |
| Production readiness | `3.0 / 5` | Release preflight, CI/coverage, service health gates, connector-registry release paths, provenance-tagged manifest-indexing, cross-release, and cross-run release-decision page export, security hardening checklist. | Production model serving, feature stores, online monitoring, drift detection, and enterprise governance are outside scope. |
| Overall public evaluation | `3.6 / 5` | Mean of the four scored public KPIs: `(3.5 + 4.0 + 4.0 + 3.0) / 4 = 3.625`. Cross-KPI evidence bundle and workflow-backed compatibility report documented in the compatibility matrix. | Alpha-stage software; not a production MLOps platform. |

## Read Next

- [Newcomer troubleshooting](https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Documentation](https://thalesgroup.github.io/agilab)
- [Flight project guide](https://thalesgroup.github.io/agilab/flight-project.html)
- [Releases](https://github.com/ThalesGroup/agilab/releases)
- [Changelog](CHANGELOG.md)
- [Developer runbook](AGENTS.md)
