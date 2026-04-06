[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![GitHub stars](https://img.shields.io/github/stars/ThalesGroup/agilab.svg)](https://github.com/ThalesGroup/agilab)
[![PyPI downloads](https://img.shields.io/pypi/dm/agilab)](https://pypi.org/project/agilab/)

[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agilab.svg)](https://codecov.io/gh/ThalesGroup/agilab)
[![Open issues](https://img.shields.io/github/issues/ThalesGroup/agilab)](https://github.com/ThalesGroup/agilab/issues)
[![Commit activity](https://img.shields.io/github/commit-activity/m/ThalesGroup/agilab.svg)](https://github.com/ThalesGroup/agilab/pulse)
[![Agent-friendly](https://img.shields.io/badge/agent-friendly%20repo-00A67E)](tools/codex_workflow.md)
[![Free-threaded aware](https://img.shields.io/badge/python-free--threaded%20aware-5B6CFF)](docs/source/environment.rst)

<details>
<summary>More project badges</summary>

[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ThalesGroup/agilab/pulls)
[![Codex skills](https://img.shields.io/badge/Codex-15%20skills-00A67E)](tools/codex_workflow.md)
[![Coverage workflow](https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml)
[![agilab](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agilab.svg)](https://codecov.io/gh/ThalesGroup/agilab)
[![agi-gui](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-gui.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-gui)
[![agi-env](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-env.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-env)
[![agi-node](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-node.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-node)
[![agi-cluster](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-cluster.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-cluster)
[![agi-core](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-core.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-core)
[![PyPI - Format](https://img.shields.io/pypi/format/agilab)](https://pypi.org/project/agilab/)
[![Repo size](https://img.shields.io/github/repo-size/ThalesGroup/agilab)](https://github.com/ThalesGroup/agilab)
[![black](https://img.shields.io/badge/code%20style-black-000000.svg)]()
[![ORCID](https://img.shields.io/badge/ORCID-0009--0003--5375--368X-A6CE39?logo=orcid)](https://orcid.org/0009-0003-5375-368X)

</details>


# AGILAB Open Source Project

AGILAB is an open-source platform for **reproducible AI/ML workflows** that takes you from local experimentation to
distributed execution and long-lived services. It combines app scaffolding, environment isolation, workflow
orchestration, and service health gates in one stack so teams can move from prototype to production-like operation
without rebuilding their tooling at every stage.

AGILAB is maintained by the Thales Group and released under the
[BSD 3-Clause License](https://github.com/ThalesGroup/agilab/blob/main/LICENSE).

## Why teams use AGILAB

- **One control path** from Streamlit or CLI entrypoints to isolated local and distributed workers.
- **Reproducible execution** through managed environments, explicit execution pipelines, and per-app settings.
- **Persistent service mode** through `AGI.serve` (`start` / `status` / `health` / `stop`) with machine-readable health gates.
- **Production-style orchestration** using `agi-node` and `agi-cluster` for packaging, dispatch, and remote execution.
- **Free-threaded Python aware** when both the selected environment and worker declare support.
- **Agent-friendly developer workflow** through `AGENTS.md`, `.codex/skills`, run configs, and Codex helpers.
- **Ready-to-adapt examples** for applied AI/ML scenarios such as flight simulation, network traffic, industrial IoT,
  and optimization workloads.

## Where AGILAB fits in production ML

AGILAB is best understood as a **workflow and orchestration layer** for applied machine learning:

- **Model Training & Orchestration**: build and run multi-step workflows locally or over SSH-managed clusters.
- **Deployment & Serving**: operate persistent workers with health snapshots and restart policies.
- **Experiment Reproducibility**: keep environments, app settings, logs, and execution history aligned.

If you are evaluating AGILAB for an MLOps stack, the core idea is simple: the same application can be driven from a
developer-friendly UI, from CLI automation, or from distributed worker execution without inventing a different control
plane for each stage.

## Quick links

- **Documentation:** https://thalesgroup.github.io/agilab
- **Execution Playground guide:** https://thalesgroup.github.io/agilab/execution-playground.html
- **Service mode guide:** https://thalesgroup.github.io/agilab/service-mode.html
- **Flight project guide:** https://thalesgroup.github.io/agilab/flight-project.html
- **PyPI package:** https://pypi.org/project/agilab
- **Discussions:** https://github.com/ThalesGroup/agilab/discussions
- **Developer runbook:** [AGENTS.md](AGENTS.md)
- **Demo capture workflow:** [docs/source/demo_capture_script.md](docs/source/demo_capture_script.md)

## See the stack in one picture

![AGILAB runtime stack](docs/source/Agilab-Overview.svg)

## Quick start

### Try the published package

```bash
pip install agilab
agilab --help
```

### Run from source

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps --test-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py
```

The installer uses [Astral’s uv](https://github.com/astral-sh/uv) to provision isolated Python interpreters, link
bundled applications into the workspace, and validate the setup with tests and coverage-aware tooling.

See the [documentation](https://thalesgroup.github.io/agilab) for alternative installation modes and end-user
deployment instructions.

The public repository is self-contained for the built-in apps and documentation. An external apps repository is
optional and only needed when you want to add extra internal or private app templates on top of the public AGILAB
stack.

## Start here: 3-minute tour

If you want to understand AGILAB quickly, use the built-in `flight_project` as the reference path:

![AGILAB 3-minute tour](docs/source/diagrams/agilab_readme_tour.svg)

Shareable visual:
- [Social card SVG](docs/source/diagrams/agilab_social_card.svg)

Local explainer generation:
- [Demo capture workflow](docs/source/demo_capture_script.md)
- `uv --preview-features extra-build-dependencies run --with imageio --with imageio-ffmpeg python tools/build_demo_explainer.py`

1. Launch the AGILAB UI from source:

   ```bash
   uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py
   ```

2. In **PROJECT**, select `src/agilab/apps/builtin/flight_project`.
3. In **ORCHESTRATE**, run the install/distribute/run flow to package and execute the worker pipeline.
4. In **PIPELINE**, inspect or replay the generated steps.
5. In **ANALYSIS**, open one of the built-in Streamlit views over the exported data.

What this shows in one pass:

- one app definition
- one environment bootstrap
- one orchestration path from UI to workers
- one analysis path over the produced artifacts

Useful references:

- [Execution Playground guide](https://thalesgroup.github.io/agilab/execution-playground.html)
- [Flight project overview](https://thalesgroup.github.io/agilab/flight-project.html)
- [Apps-pages quick start](src/agilab/apps-pages/README.md)
- [Service mode and paths](https://thalesgroup.github.io/agilab/service_mode_and_paths.html)

## Killer example: Execution Playground

If you want one example that shows why AGILAB is different, use the built-in execution playground:

- `execution_pandas_project`
- `execution_polars_project`

They run the same synthetic workload on the same generated dataset, but through different worker paths:

- `PandasWorker` highlights a process-based execution path
- `PolarsWorker` highlights an in-process threaded execution path

This makes the benchmark more useful than a simple "library A vs library B" comparison: AGILAB shows which
execution model wins for the same workload, then keeps the orchestration path reproducible from UI to outputs.

Measured local benchmark

Generated with `uv --preview-features extra-build-dependencies run python tools/benchmark_execution_playground.py --repeats 3 --warmups 1 --worker-counts 1,2,4 --rows-per-file 100000 --compute-passes 8 --n-partitions 16`
on macOS / Python `3.13.9` with a heavier default workload (`16` partitions, `100000` rows per file, `8` compute passes):

| App | Worker path | Mode | 1 worker | 2 workers | 4 workers |
| --- | --- | --- | ---: | ---: | ---: |
| execution_pandas_project | pandas / process | mono | 1.607 | 1.416 | 1.457 |
| execution_pandas_project | pandas / process | parallel | 7.411 | 4.563 | 3.301 |
| execution_polars_project | polars / threads | mono | 1.225 | 1.287 | 1.381 |
| execution_polars_project | polars / threads | parallel | 1.232 | 1.252 | 1.383 |

This is the extra point the example now makes visible: results change with the number of workers, and not in the same way for both execution models.

- `pandas / process` benefits materially from more workers on this heavier workload: `7.411s` at `1` worker, `4.563s` at `2`, `3.301s` at `4`.
- `polars / threads` is already near its steady-state result with `1` worker and remains almost flat as workers increase.
- AGILAB therefore makes two things explicit at once: the execution model and the worker-count scaling behavior.

Raw benchmark data:
- [execution_playground_benchmark.json](docs/source/data/execution_playground_benchmark.json)

## Why star AGILAB

Star AGILAB if you care about one or more of these:

- **Reproducible AI/ML workflows** instead of hand-wired notebooks, shell scripts, and scattered env setup.
- **Agent-friendly engineering** with repo-native guidance through `AGENTS.md`, `.codex/skills`, and documented Codex workflows.
- **Free-threaded Python readiness** where environment and worker compatibility is explicit rather than accidental.
- **Execution model benchmarking** that shows whether the same workload wins with process-based or in-process/threaded execution paths.
- **One control path** from app selection to orchestration, pipeline inspection, analysis, and service mode.

## Who this is for

- Teams moving from local experimentation toward distributed or service-style execution.
- Engineers who want a visible control path from UI or CLI to worker packaging and outputs.
- Developers who want a repo that works well with coding agents, not just with humans.

## Who this is not for

- Teams looking only for experiment tracking without execution orchestration.
- Users who want a notebook-only workflow with no packaging or deployment concerns.
- Organizations expecting a finished all-in-one enterprise platform out of the box.

## What makes AGILAB different

| Capability | What AGILAB gives you |
| --- | --- |
| Unified control plane | Launch the same app from Streamlit, CLI wrappers, or distributed workers. |
| Managed execution envs | Package worker dependencies into isolated environments instead of relying on one shared Python install. |
| Persistent operation | Use `AGI.serve` with health gates and structured status snapshots for long-lived workloads. |
| Free-threaded Python support | Opt into free-threaded Python when both the chosen environment and worker declare compatibility. |
| Execution model visibility | Benchmark the same workload across worker/runtime paths and make the winning execution model explicit. |
| Agentic development | Use repo-native guidance through `AGENTS.md`, `.codex/skills`, and Codex workflow helpers instead of ad hoc prompts. |
| Modular adoption | Install the full stack or adopt `agi-env`, `agi-node`, `agi-cluster`, and `agi-core` separately. |

## AGILAB vs manual orchestration

| Workflow step | Manual approach | AGILAB approach |
| --- | --- | --- |
| Environment setup | Hand-build Python environments and keep them aligned across machines. | Use managed environments and packaged workers. |
| Running an experiment | Glue together scripts, shell commands, and remote execution by hand. | Drive the same flow from Streamlit, CLI wrappers, or worker dispatch. |
| Scaling out | Recreate dependencies and SSH conventions for each remote target. | Reuse `agi-node` / `agi-cluster` packaging and dispatch logic. |
| Service continuity | Invent your own start/status/health/stop checks. | Use `AGI.serve` with health snapshots and gate thresholds. |
| Artifact traceability | Logs and outputs end up scattered across scripts and machines. | Keep run history, logs, and app outputs on a documented control path. |

The point is not that AGILAB replaces every production platform. The point is that it removes a large amount of
hand-written orchestration during experimentation and validation, then makes the handoff to a broader stack cleaner.

In practice, that also means AGILAB can show when a performance win comes from the execution model itself. For example,
the same workload can be benchmarked through `PandasWorker` using a process-based path and through `PolarsWorker` using
an in-process threaded path, so the benchmark explains more than "library A vs library B".

## Repository layout

The monorepo hosts several tightly-coupled packages:

| Package | Location | Purpose |
| --- | --- | --- |
| `agilab` | `src/agilab` | Top-level Streamlit experience, tooling, and reference applications |
| `agi-env` | `src/agilab/core/agi-env` | Environment bootstrap, configuration helpers, and pagelib utilities |
| `agi-node` | `src/agilab/core/agi-node` | Local/remote worker orchestration and task dispatch |
| `agi-cluster` | `src/agilab/core/agi-cluster` | Multi-node coordination, distribution, and deployment helpers |
| `agi-core` | `src/agilab/core/agi-core` | Meta-package bundling the environment/node/cluster components |

Each package can be installed independently via `pip install <package-name>`, but the recommended development path is
to clone this repository and use the provided scripts.

## Developer workflow

For development mode, the strongly recommended tools are:

- **PyCharm (Professional)** with repository-specific settings.
- Community-only workflows can still work through CLI wrappers and manual entry points,
  but Pro is required for the full IDE-oriented setup flow.
- **Codex CLI** configured from repository-specific guidance (`AGENTS.md` and
  repository `.codex/skills`/workflow settings).

For a professional Codex workflow, use the repo helper:

- `./tools/codex_workflow.sh review` before coding changes.
- `./tools/codex_workflow.sh exec "..."` for implementation tasks.
- `./tools/codex_workflow.sh apply <task-id>` for generated task patch application.
- Configuration and usage details: `tools/codex_workflow.md`.

Use macOS or Linux when you need to validate or reuse Linux-dependent code paths.

## Framework execution flow

- **Entrypoints**: Streamlit (`src/agilab/About_agilab.py`) and CLI mirrors call `AGI.run`/`AGI.install`, which hydrate an `AgiEnv` and load app manifests via `agi_core.apps`.
- **Environment bootstrap**: `agi_env` resolves paths (`agi_share_path`, `wenv`), credentials, and uv-managed interpreters before any worker code runs; config precedence is env vars → `~/.agilab/.env` → app settings.
- **Planning**: `agi_core` builds a WorkDispatcher plan (datasets, workers, telemetry) and emits structured status to Streamlit widgets/CLI for live progress.
- **Dispatch**: `agi_cluster` schedules tasks locally or over SSH; `agi_node` packages workers, validates dependencies, and executes workloads in isolated envs.
- **Telemetry & artifacts**: run history and logs are written under `~/log/execute/<app>/`, while app-specific outputs land relative to `agi_share_path` (see app docs for locations).
- **Service mode**: `AGI.serve` manages persistent workers and returns machine-readable health snapshots (`agi.service.health.v1`) for gating and monitoring.

## Web interface workflow

The main interface is organized around four pages:

- **PROJECT**: project/app selection, settings, and source/config editing.
- **ORCHESTRATE**: install/distribute/run workflows, service controls, and health gate checks.
- **PIPELINE**: compose and replay step sequences, including locked snippets imported from ORCHESTRATE.
- **ANALYSIS**: launch built-in and custom Streamlit page bundles for post-run analysis.

## AGI.serve and health gates

`AGI.serve` is the persistent service API used by ORCHESTRATE service mode.

- Actions: `start`, `status`, `health`, `stop`.
- `health` writes/returns a JSON snapshot with schema `agi.service.health.v1`.
- Default gate thresholds are read from app settings under `[cluster.service_health]`:
  `allow_idle`, `max_unhealthy`, `max_restart_rate`.
- Health gates can be executed from ORCHESTRATE or from CLI:

```bash
uv --preview-features extra-build-dependencies run python tools/service_health_check.py \
  --app mycode_project \
  --apps-path src/agilab/apps/builtin \
  --format json
```

## Documentation & resources

- 📘 **Docs:** https://thalesgroup.github.io/agilab
- ⚙️ **Service mode guide:** https://thalesgroup.github.io/agilab/service-mode.html
- 💬 **Discussions:** https://github.com/ThalesGroup/agilab/discussions
- 📦 **PyPI:** https://pypi.org/project/agilab
- 🧩 **Core package index:** https://pypi.org/search/?q=agi-
- 🧪 **Test matrix:** refer to `.github/workflows/ci.yml`
- ✅ **Coverage snapshot:** see badges above (auto-updated after the dedicated `coverage` workflow)
- 🧾 **Runbook:** [AGENTS.md](AGENTS.md)
- 🛠️ **Developer tools:** scripts in `tools/` and application templates in `src/agilab/apps`
