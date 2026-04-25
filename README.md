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

The public AGILAB Space is the fastest browser preview. It opens the lightweight
`flight_project` path by default; advanced scenarios such as
`uav_relay_queue_project` are documented in the demo guide.

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
uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --json
```

The JSON proof writes `run_manifest.json` under `~/log/execute/flight/`. For
installer flags, IDE run configs, and troubleshooting, use the Quick Start docs.

## Published Package

The PyPI package is the thinnest public entry point:

```bash
pip install agilab
agilab
```

Use it for a quick package-level check. For the most representative first proof,
prefer the source-checkout `flight_project` path above because it exercises the
same app installation, execution, and analysis flow documented in the web UI.

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
- [Compatibility matrix](https://thalesgroup.github.io/agilab/compatibility-matrix.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Future work](https://thalesgroup.github.io/agilab/roadmap/agilab-future-work.html)

<!-- Evidence anchors for local public-evidence checks; rendered docs remain the
source of truth for explanations.
tools/newcomer_first_proof.py --json
run_manifest.json
tools/reduce_contract_benchmark.py --json
tools/revision_traceability_report.py --compact
tools/public_certification_profile_report.py --compact
tools/supply_chain_attestation_report.py --compact
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
tools/data_connector_app_catalogs_report.py --compact
-->

## Evaluation Snapshot

Current CODEX 5.5 working scores, out of 5 and refreshed from the public KPI
bundle, not production MLOps claims:

| KPI | Current score (/5) | Evidence | Limit |
|---|---|---:|---|
| Ease of adoption | `4.0 / 5` | Hosted Space, CLI-first local `flight_project` path, opt-in installer tests, local smoke: `5.86s` vs `600s`, fresh external-machine smoke on April 25, 2026: `26.87s` vs `600s`, plus AI Lightning, Hugging Face, bare-metal cluster, and VM-based cluster validation. | Remaining validation gap: Azure, AWS, and GCP cloud deployments. |
| Research experimentation | `4.0 / 5` | Isolated `uv`, `lab_steps.toml`, MLflow-tracked runs, analysis pages, reduce artifacts, public reduce benchmark, notebook reports, connector reports, and multi-app/global DAG evidence summarized by the KPI bundle. | Future apps/templates must opt in when they produce concrete merge outputs. |
| Engineering prototyping | `4.0 / 5` | `app_args_form.py`, `pipeline_view`, reusable history, analysis-page templates, first-proof wizard/manifest evidence, connector provenance UI contracts, and global DAG operator-state/action/UI contracts. | Additional external replication beyond the current public first-proof paths is not claimed. |
| Production readiness | `3.0 / 5` | Release preflight, CI/coverage, service health gates, connector-registry release paths, provenance-tagged manifest-indexing, cross-release, and cross-run release-decision page export, security hardening checklist. | Production model serving, feature stores, online monitoring, drift detection, and enterprise governance are outside scope. |
| Overall public evaluation | `3.8 / 5` | Mean of the four scored public KPIs: `(4.0 + 4.0 + 4.0 + 3.0) / 4 = 3.75`. Cross-KPI evidence bundle and workflow-backed compatibility report documented in the compatibility matrix. | Alpha-stage software; not a production MLOps platform. |

## Read Next

- [Newcomer troubleshooting](https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Documentation](https://thalesgroup.github.io/agilab)
- [Flight project guide](https://thalesgroup.github.io/agilab/flight-project.html)
- [Releases](https://github.com/ThalesGroup/agilab/releases)
- [Changelog](CHANGELOG.md)
- [Developer runbook](AGENTS.md)
