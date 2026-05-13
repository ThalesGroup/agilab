<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/pypi-version-agilab.svg" alt="PyPI version" /></a>
  <a href="https://thalesgroup.github.io/agilab/release-proof.html"><img src="https://img.shields.io/badge/version%20alignment-release%20proof-0F766E" alt="Version alignment release proof" /></a>
  <a href="https://opensource.org/licenses/BSD-3-Clause"><img src="https://img.shields.io/badge/License-BSD%203--Clause-blue.svg" alt="License: BSD 3-Clause" /></a>
  <a href="https://thalesgroup.github.io/agilab"><img src="https://img.shields.io/badge/Documentation-online-brightgreen.svg" alt="Documentation" /></a>
  <a href="https://github.com/ThalesGroup/agilab"><img src="https://img.shields.io/github/stars/ThalesGroup/agilab?style=flat&label=stars" alt="GitHub stars" /></a>
  <a href="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml"><img src="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
</p>

<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/pyversions/agilab.svg" alt="Supported Python Versions" /></a>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/dm/agilab" alt="PyPI downloads" /></a>
  <a href="https://github.com/ThalesGroup/agilab/issues"><img src="https://img.shields.io/github/issues/ThalesGroup/agilab" alt="Open issues" /></a>
  <a href="https://github.com/ThalesGroup/agilab/pulse"><img src="https://img.shields.io/github/commit-activity/m/ThalesGroup/agilab.svg" alt="Commit activity" /></a>
  <a href="tools/agent_workflows.md"><img src="https://img.shields.io/badge/Agents-codex%20%26%20claude%20%26%20aider%20%26%20opencode-0F766E" alt="Agents Codex Claude Aider and OpenCode" /></a>
  <a href=".codex/skills/README.md"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/skills-codex.svg" alt="Codex skills" /></a>
  <a href=".claude/skills/README.md"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/skills-claude.svg" alt="Claude skills" /></a>
  <a href="docs/source/environment.rst"><img src="https://img.shields.io/badge/Language-python%20free--threaded%20%26%20cythonized-5B6CFF" alt="Language Python free-threaded and Cythonized" /></a>
  <a href="https://github.com/ThalesGroup/agilab/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome" /></a>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/badge/wheel-yes-0F766E" alt="Wheel: yes" /></a>
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

# AGILAB

AGILAB is a reproducible AI/ML workbench for engineering teams.
It turns notebooks and scripts into controlled, executable apps with:

- **one-command setup**
- **controlled environments**
- **local or distributed execution**
- **visible experiment evidence**
- **optional MLflow integration**

AGILAB complements MLflow and production MLOps platforms. It owns the
reproducible execution and analysis layer around them.
In short: MLflow tracks experiments; AGILAB transforms notebooks and scripts
into reproducible executable AI applications.

## Core Flow

Notebook/script → AGILAB app → execution (local/distributed) → MLflow →
Streamlit UI

Start with the public browser preview or the demo chooser:

- [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab)
- [Demo chooser](https://thalesgroup.github.io/agilab/demos.html)
- [Local quick start](#quick-start)
- [Demo capture guide](https://thalesgroup.github.io/agilab/demo_capture_script.html)

## [Quick Start](https://thalesgroup.github.io/agilab/quick-start.html)

<p>
  <a href="https://huggingface.co/spaces/jpmorard/agilab"><img src="https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge" alt="AGILAB Space" /></a>
  <a href="https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb"><img src="https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge" alt="agi-core notebook" /></a>
</p>

### Local PyPI UI Proof

```bash
uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"
agilab
```

For a zero-install browser preview, open the public
[AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab). It opens the
lightweight `flight_project` path by default and exposes the
`meteo_forecast_project` notebook-migration demo with forecast analysis views.
Advanced scenarios such as `data_io_2026_project`,
`execution_pandas_project`, `execution_polars_project`, and
`uav_relay_queue_project` are collected in the
[Advanced Proof Pack](https://thalesgroup.github.io/agilab/advanced-proof-pack.html).
The default hosted flight journey covers `PROJECT`, `ORCHESTRATE`, `WORKFLOW`,
and `ANALYSIS`, including bundled flight analysis views.

If startup fails, run a progressive fallback:

```bash
agilab dry-run
agilab first-proof --json --with-ui
```

`agilab dry-run` is the fast alias for `agilab first-proof --dry-run`; it
verifies CLI/core readiness only.
`agilab first-proof --json --with-ui` does the local onboarding contract
including manifest generation for the UI path.

### Maturity snapshot

| Capability | Status |
|---|---|
| Local run | Stable |
| Distributed (Dask) | Stable |
| UI Streamlit | Beta |
| MLflow | Beta |
| Production | Experimental |
| RL examples | Example available |

AGILAB is most mature in the bridge between notebook experimentation and
reproducible AI applications: local execution, environment control, and
analysis. Distributed execution is mature in the core runtime; remote cluster
mounts, credentials, and hardware stacks remain environment-dependent.
Production-grade MLOps features are delivered through integrations and are not
yet a packaged platform claim.

## Production Boundary

AGILAB should be adopted as an experimentation and validation workbench first.
Use this boundary before deploying it in sensitive environments:

| Boundary | Status | Required controls |
|---|---|---|
| Safe for production-like use | Local research sandboxes, internal demos, notebook-to-app migration, reproducible validation with non-sensitive data. | Normal repository hygiene and local proof evidence. |
| Conditional use only | Shared team workspaces, SSH/Dask clusters, external apps, LLM connectors, or sensitive datasets. | Per-user isolation, explicit secrets management, TLS/auth for exposed services, SBOM plus vulnerability scan evidence, and a deployment threat model. |
| Not safe as-is | Sole production MLOps control plane, public Streamlit exposure, regulated production model serving, enterprise governance, online monitoring, drift detection, or audit-trail ownership. | Pair AGILAB with a hardened production stack such as MLflow/Kubeflow/SageMaker/Dagster/Airflow or an internal platform. |

## Dependency And Supply-Chain Boundaries

The public package is intentionally profile-based so operators can install only
what they need:

| Profile | Dependency scope | Use when |
|---|---|---|
| Base package | `agilab` plus `agi-core`, which wires `agi-env`, `agi-node`, and `agi-cluster`. This includes the core local/distributed runtime dependencies but not the built-in app or page-bundle payload. | CLI/core tooling, source-checkout validation, and worker-runtime development. |
| `ui` extra | Streamlit UI, page helpers, pandas/network graph utilities, `agi-apps` plus per-app project packages, and `agi-pages` analysis page bundles. | Running the local product UI with the public demo projects and analysis views available. |
| `examples` extra | `agi-apps` app catalog/examples plus notebook/demo helper dependencies such as JupyterLab and optional plotting packages. | Running packaged notebooks, demos, learning examples, and package first-proof routes. |
| `pages` extra | `agi-pages` public analysis page bundles without the full UI profile. | Installing or validating sidecar page bundles separately from built-in app projects. |
| `agents` extra | API client dependency boundary for packaged agent workflow helpers. | Reproducible coding-agent and assistant-backed workflows. |
| `mlflow` extra | MLflow tracking integration. | Recording runs, metrics, artifacts, or model registry handoff evidence. |
| `ai` and `viz` extras | API LLM clients and optional plotting packages. | Assistant-backed workflows or richer visual analysis. |
| `local-llm` / `offline` extras | Local/offline model stacks such as Torch, Transformers, GPT-OSS, and MLX where supported. | Isolated local-model experiments; expect a larger supply-chain and hardware footprint. |
| `dev` extra | Contributor test/build/audit tooling only. | Validating a source checkout or release candidate; avoid it for runtime installs. |

Agent workflows can now produce AGILAB evidence directly. Use
`agilab agent-run --agent codex --label "Review current diff" -- codex review`
to execute a local coding-agent command and write a redacted
`agilab.agent_run.v1` manifest plus local stdout/stderr artifacts under
`~/log/agents/`. Command arguments are redacted by default and represented by
an argv hash; pass `--include-command-args` only when the prompt/arguments are
safe to store.

Cluster/Dask dependencies are currently part of the base package through
`agi-core`; a smaller cluster-specific package split is a packaging roadmap item,
not a current release claim.

Release and adoption supply-chain evidence is explicit: Dependabot watches
Python and GitHub Actions manifests, release workflows publish per-profile
`pip-audit` JSON and CycloneDX SBOM artifacts, and
`tools/profile_supply_chain_scan.py` can regenerate the same profile evidence
locally.

## Evidence Taxonomy

AGILAB separates public claims by evidence type:

| Evidence type | What it proves | What it does not prove |
|---|---|---|
| Automated proof | Commands such as `agilab first-proof --json`, workflow parity checks, coverage, release proof, and UI robot evidence ran successfully. | Independent certification or coverage of every deployment topology. |
| Integration tests | A specific source path, package route, app, or workflow contract is exercised by tests. | Production SLA, security certification, or external operator acceptance. |
| Benchmarks | Timings for declared hardware, datasets, modes, and benchmark scripts. | General performance across arbitrary hardware, networks, or datasets. |
| Self-assessment | KPI scores such as production readiness and strategic potential are maintained from repository evidence. | External validation or third-party certification. |
| External validation | Only claimed when a named external artifact, reviewer, CI provider, or hosted demo proof is linked. | Implied endorsement beyond the linked evidence. |

## Repository Map And Stability Boundaries

AGILAB is a monorepo, but it is not a single stability surface:

| Area | Role | Stability contract |
|---|---|---|
| `src/agilab/core/agi-env`, `agi-node`, `agi-cluster`, `agi-core` | Runtime packages for environment setup, worker packaging, distributed execution, and the compact API. | Stable where documented; changes require focused regression evidence. |
| `src/agilab/lib/agi-gui`, `src/agilab/pages` | Streamlit UI and page helpers. | Beta product surface; useful for operators, still evolving. |
| `src/agilab/lib/agi-apps` | PyPI umbrella that carries app catalog/example assets and depends on per-app project packages. | Packaged asset surface for the `ui` and `examples` extras. |
| `src/agilab/lib/agi-pages` | PyPI package that carries public analysis page bundles. | Packaged page-bundle surface for the `ui` and `pages` extras. |
| `src/agilab/apps/builtin` | Public built-in apps used for first proof, demos, workflow examples, and regression coverage. | Packaged examples, not enterprise deployment templates. |
| `src/agilab/examples` | Learning scripts, notebooks, and preview examples. | Educational material; optional helper dependencies live behind extras. |
| `tools`, `.github`, `pycharm`, `.codex`, `.claude`, `dev` | Contributor, release, agent, and IDE automation. | Maintainer tooling, not runtime API. |
| `docs/source` | Public documentation mirror. | Published docs source; canonical docs are synchronized before release. |

This split is intentional. Treat AGILAB as an AI engineering reproducibility
workbench first: stable runtime contracts, beta UI, packaged examples, and
maintainer automation live together so release proof can validate the same
source tree users install from.

## Package Surface Contract

Local source checkouts can grow after runs because built-in apps can create
`.venv` directories, build outputs, caches, datasets, and local logs.
Those local artifacts are not the package contract. Public wheels are bounded
by `pyproject.toml` package data rules and exclude virtual environments,
tests, `docs/html`, build directories, generated C files,
`__pycache__`, `.pyc`, and `.egg-info` artifacts.

Current packaging policy is conservative:

- Base `agilab` keeps CLI/core proof dependencies separate from UI, page bundles,
  examples, agents, MLflow, visualization, local-LLM, offline, and dev profiles.
- Built-in app payloads live in per-app packages such as
  `agi-app-flight-project` and `agi-app-mycode-project`; `agi-apps` is the
  umbrella catalog/example package pulled in by the `ui` and `examples` extras.
- Public analysis page bundles live in the `agi-pages` wheel and are pulled in
  by the `ui` and `pages` extras.
- Larger optional stacks must stay behind extras, and release evidence must
  include SBOM / `pip-audit` data for the actual enabled profile.
- Further cluster/runtime splitting is a roadmap item; it is not claimed as
  complete in the current release.

## Choose Your Path

1. Preview the product quickly: [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab)
2. Understand notebook-to-app migration: [Notebook Migration Demo](https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html)
3. Prove the full source-checkout flow: [Source Checkout](#source-checkout)
4. Verify a CLI-only package install: [Published Package](#published-package)
5. Contribute safely: [Contributor onboarding](CONTRIBUTING.md)
6. Audit external apps and evidence: [App Repository Updates](#app-repository-updates) and [Release Proof](https://thalesgroup.github.io/agilab/release-proof.html)

For a single-page adoption checklist, use [ADOPTION.md](ADOPTION.md).

## Source Version vs Package Version

AGILAB publishes from this repository, but each public surface has a distinct
role:

| Surface | Meaning | Source of truth |
|---|---|---|
| `main` branch and root `pyproject.toml` | Active source checkout and next release candidate. It can move after a package has already been published. | GitHub source tree |
| Release tag | Immutable source snapshot used for a public release. Use this for reproducible source installs. | GitHub tag and GitHub Release |
| PyPI package | Latest installable public wheel/sdist for `agilab` and the `agi-*` packages. | PyPI project and PyPI version badge |
| Release proof | Public evidence tying the release tag, PyPI package version, docs, CI, coverage, and demo proof together. | [Release Proof](https://thalesgroup.github.io/agilab/release-proof.html) |

For development, use `main`. For reproducible release validation, use the
release tag or the PyPI package version recorded in the release proof.

## Source Checkout

Run the installable product path with the built-in `flight_project`:

```bash
CHECKOUT="${AGILAB_CHECKOUT:-$HOME/agilab-src}"
git clone https://github.com/ThalesGroup/agilab.git "$CHECKOUT"
cd "$CHECKOUT"
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py
```

Follow the in-app pages from `PROJECT` to `ORCHESTRATE`, `PIPELINE`, and
`ANALYSIS`. To collect the same check as JSON:

```bash
uv --preview-features extra-build-dependencies run agilab first-proof --json
```

The JSON proof writes `run_manifest.json` under `~/log/execute/flight/`. For
installer flags, IDE run configs, and troubleshooting, use the Quick Start docs.

## Published Package

For a CLI-only package smoke without Streamlit:

```bash
uv --preview-features extra-build-dependencies tool install --upgrade "agilab[examples]"
agilab first-proof --json --max-seconds 60
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
- [Package publishing policy](https://thalesgroup.github.io/agilab/package-publishing-policy.html)
- [Future work](https://thalesgroup.github.io/agilab/roadmap/agilab-future-work.html)

## Evaluation Snapshot

<!-- AGILAB_PUBLIC_KPI_SUMMARY_START -->
Current public evaluation summary, refreshed from the public KPI bundle:

- `4.0 / 5` for ease of adoption, research experimentation, and engineering prototyping.
- `3.0 / 5` for production readiness.
- `4.2 / 5` for strategic potential.
- Overall public evaluation, rounded category average: `3.8 / 5`.
<!-- AGILAB_PUBLIC_KPI_SUMMARY_END -->

These are public experimentation-workbench scores, not production MLOps claims.
They cover project setup, environment management, execution, and result analysis.
The evidence and limits are maintained in the
[compatibility matrix](https://thalesgroup.github.io/agilab/compatibility-matrix.html)
and [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html).
The strategic score movement rule is tracked in the
[strategic scorecard](https://thalesgroup.github.io/agilab/strategic-potential.html).

## Read Next

- [Newcomer troubleshooting](https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Strategic scorecard](https://thalesgroup.github.io/agilab/strategic-potential.html)
- [Documentation](https://thalesgroup.github.io/agilab)
- [Contributor onboarding](CONTRIBUTING.md)
- [Flight project guide](https://thalesgroup.github.io/agilab/flight-project.html)
- [Adoption guide](ADOPTION.md)
- [Releases](https://github.com/ThalesGroup/agilab/releases)
- [Changelog](CHANGELOG.md)
- [Developer runbook](AGENTS.md)
