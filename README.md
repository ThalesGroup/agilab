<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/pypi-version-agilab.svg" alt="PyPI version" /></a>
  <a href="https://opensource.org/licenses/BSD-3-Clause"><img src="https://img.shields.io/badge/License-BSD%203--Clause-blue.svg" alt="License: BSD 3-Clause" /></a>
  <a href="https://thalesgroup.github.io/agilab"><img src="https://img.shields.io/badge/Documentation-online-brightgreen.svg" alt="Documentation" /></a>
  <a href="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml"><img src="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
</p>

# AGILAB

AGILAB is a reproducible AI/ML workbench for engineering teams.

It turns notebooks and scripts into reproducible apps with:

- **one-command setup**
- **controlled environments**
- **local or distributed execution**
- **visible experiment evidence**
- **optional MLflow integration**

AGILAB complements MLflow. It is not a replacement for MLflow or production
MLOps platforms.

It owns the execution and reproducibility layer around tracking, packaging, and
analysis.

## Central demo

Notebook/script → AGILAB app → execution (local/distributed) → MLflow →
Streamlit UI

Start with the public browser preview or the demo chooser:

- [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab)
- [Demo chooser](https://thalesgroup.github.io/agilab/demos.html)
- [Local quick start](https://thalesgroup.github.io/agilab/quick-start.html)
- [Demo capture guide](https://thalesgroup.github.io/agilab/demo_capture_script.html)

## [Quick Start](https://thalesgroup.github.io/agilab/quick-start.html)

<p>
  <a href="https://huggingface.co/spaces/jpmorard/agilab"><img src="https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge" alt="AGILAB Space" /></a>
  <a href="https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb"><img src="https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge" alt="agi-core notebook" /></a>
</p>

### Recommended positioning

- **AGILAB = environment + execution + reproducibility**
- **MLflow = experiment tracking + model registry + deployment metadata**

### Try this first

```bash
pip install agilab
agilab first-proof --json
agilab
```

The public AGILAB Space is the fastest browser preview. It opens the
lightweight `flight_project` path by default and also exposes the
`meteo_forecast_project` notebook-migration demo with forecast analysis views.
Advanced scenarios such as `data_io_2026_project`,
`execution_pandas_project`, `execution_polars_project`, and
`uav_relay_queue_project` are collected in the
[Advanced Proof Pack](https://thalesgroup.github.io/agilab/advanced-proof-pack.html).

### Maturity snapshot

| Capability | Status |
|---|---|
| Local run | Stable |
| UI Streamlit | Stable |
| Distributed (Dask) | Beta |
| MLflow | Beta |
| Production | Experimental |
| Agents RL | Roadmap |

AGILAB is most mature in the bridge between notebook experimentation and
reproducible AI applications: local execution, environment control, and
analysis. Production-grade MLOps features are delivered through integrations
and are not yet a packaged platform claim.

## Choose Your Path

1. Preview the product quickly: [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab)
2. Learn notebook migration: [Notebook Migration Demo](https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html)
3. Prove local flow: [First Run](#first-run)
4. Verify package installation: [Published Package](#published-package)
5. Audit external apps and evidence: [App Repository Updates](#app-repository-updates) and [Release Proof](https://thalesgroup.github.io/agilab/release-proof.html)

For a single-page adoption checklist, use [ADOPTION.md](ADOPTION.md).

## First Run

Run the installable product path with the built-in `flight_project`:

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py
```

Follow the in-app pages from `PROJECT` to `ANALYSIS`. To collect the same check
as JSON:

```bash
uv --preview-features extra-build-dependencies run agilab first-proof --json
```

The JSON proof writes `run_manifest.json` under `~/log/execute/flight/`. For
installer flags, IDE run configs, and troubleshooting, use the Quick Start docs.

## Published Package

The PyPI package is the thinnest public entry point:

```bash
mkdir ~/agi-workspace && cd ~/agi-workspace
uv venv
source .venv/bin/activate
uv pip install agilab
agilab first-proof --json --max-seconds 60
uv run agilab
```

Use `agilab first-proof --json --max-seconds 60` for a quick package-level
check. The clean-install CI matrix enforces that runtime budget on Linux and
macOS. For the most representative full product run, prefer the source-checkout
`flight_project` path above because it exercises the same app installation,
execution, and analysis flow documented in the web UI.

Optional feature stacks stay out of the base package install. Add
`agilab[ai]` for AI assistant features such as OpenAI, Mistral, and
OpenAI-compatible endpoints like vLLM, and `agilab[viz]` for optional
Plotly/matplotlib visualizations:

```bash
uv pip install "agilab[ai,viz]"
```

## App Repository Updates

When `APPS_REPOSITORY` points at an external apps repository, rerun the
installer after app changes:

```bash
./install.sh --non-interactive --apps-repository /path/to/apps-repository --install-apps all
```

During an update, the apps repository is treated as the source of truth. If the
target app/page already exists as a real directory instead of a symlink, AGILAB
backs it up as `<name>.previous.<timestamp>`, then links the repository copy in
its place. After the update, AGILAB runs the repository version; the
`.previous` directory is kept only for manual recovery. See
[Service mode and paths](https://thalesgroup.github.io/agilab/service_mode_and_paths.html)
for the full path contract.

## Evidence And Scope

The README is only the entry page. Detailed capability evidence, compatibility
status, and roadmap scope live in:

- [Features](https://thalesgroup.github.io/agilab/features.html)
- [Release proof](https://thalesgroup.github.io/agilab/release-proof.html)
- [Compatibility matrix](https://thalesgroup.github.io/agilab/compatibility-matrix.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Future work](https://thalesgroup.github.io/agilab/roadmap/agilab-future-work.html)

<!-- Evidence anchors for local public-evidence checks; rendered docs remain the
source of truth for explanations.
tools/newcomer_first_proof.py --json
agilab first-proof --json
run_manifest.json
tools/reduce_contract_benchmark.py --json
tools/revision_traceability_report.py --compact
tools/public_certification_profile_report.py --compact
tools/supply_chain_attestation_report.py --compact
tools/public_proof_scenarios.py --compact
tools/repository_knowledge_report.py --compact
tools/run_diff_evidence_report.py --compact
tools/ci_artifact_harvest_report.py --compact
tools/github_actions_artifact_index.py --archive <artifact.zip> --output artifact_index.json
tools/ci_provider_artifact_index.py --provider gitlab_ci --archive <artifact.zip> --output artifact_index.json
tools/ci_provider_artifact_index.py --live-gitlab --project <group/project> --pipeline-id <id> --output artifact_index.json
tools/multi_app_dag_report.py --compact
tools/global_pipeline_dag_report.py --compact
tools/global_pipeline_execution_plan_report.py --compact
tools/global_pipeline_runner_state_report.py --compact
tools/global_pipeline_dispatch_state_report.py --compact
tools/global_pipeline_app_dispatch_smoke_report.py --compact
tools/global_pipeline_operator_state_report.py --compact
tools/global_pipeline_dependency_view_report.py --compact
tools/global_pipeline_live_state_updates_report.py --compact
tools/global_pipeline_operator_actions_report.py --compact
tools/global_pipeline_operator_ui_report.py --compact
tools/notebook_import_preflight.py --compact
tools/notebook_pipeline_import_report.py --compact
tools/notebook_roundtrip_report.py --compact
tools/notebook_union_environment_report.py --compact
tools/data_connector_facility_report.py --compact
tools/data_connector_resolution_report.py --compact
tools/data_connector_health_report.py --compact
tools/data_connector_health_actions_report.py --compact
tools/data_connector_runtime_adapters_report.py --compact
tools/data_connector_live_endpoint_smoke_report.py --compact
tools/data_connector_ui_preview_report.py --compact
tools/data_connector_live_ui_report.py --compact
tools/data_connector_view_surface_report.py --compact
tools/data_connector_app_catalogs_report.py --compact
-->

## Evaluation Snapshot

<!-- AGILAB_PUBLIC_KPI_SUMMARY_START -->
Current CODEX 5.5 working summary, refreshed from the public KPI bundle:

- `4.0 / 5` for ease of adoption, research experimentation, and engineering prototyping.
- `3.0 / 5` for production readiness.
- `4.2 / 5` for strategic potential.
- Overall public evaluation, rounded category average: `3.8 / 5`.
<!-- AGILAB_PUBLIC_KPI_SUMMARY_END -->

These are public experimentation-workbench scores, not production MLOps claims.
The evidence and limits are maintained in the
[compatibility matrix](https://thalesgroup.github.io/agilab/compatibility-matrix.html)
and [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html).
The strategic score movement rule is tracked in the
[strategic scorecard](https://thalesgroup.github.io/agilab/strategic-potential.html).

One forward-looking improvement area is elasticity. AGILAB is currently strongest
at the `Train -> Test -> Evidence` loop: run a pipeline, inspect artifacts, and
compare outcomes. A later differentiator would be multi-agent reinforcement
learning for active mesh optimization, where aircraft, UAVs, or satellites are
not just moving nodes but active agents that can adapt flight paths or routing
to improve network evidence. That is a roadmap direction, not a shipped
capability claim.

## Read Next

- [Newcomer troubleshooting](https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Strategic scorecard](https://thalesgroup.github.io/agilab/strategic-potential.html)
- [Documentation](https://thalesgroup.github.io/agilab)
- [Flight project guide](https://thalesgroup.github.io/agilab/flight-project.html)
- [Adoption guide](ADOPTION.md)
- [Releases](https://github.com/ThalesGroup/agilab/releases)
- [Changelog](CHANGELOG.md)
- [Developer runbook](AGENTS.md)
