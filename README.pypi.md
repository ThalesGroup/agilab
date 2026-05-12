[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)
[![Version alignment](https://img.shields.io/badge/version%20alignment-release%20proof-0F766E)](https://thalesgroup.github.io/agilab/release-proof.html)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)

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

Notebook/script -> AGILAB app -> execution (local/distributed) -> MLflow ->
Streamlit UI

Start with the public browser preview or the demo chooser:

- [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab)
- [Demo chooser](https://thalesgroup.github.io/agilab/demos.html)
- [Local quick start](https://thalesgroup.github.io/agilab/quick-start.html)
- [Demo capture guide](https://thalesgroup.github.io/agilab/demo_capture_script.html)

## Quick Start

[![AGILAB Space](https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge)](https://huggingface.co/spaces/jpmorard/agilab)
[![agi-core notebook](https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge)](https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb)

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

If startup fails, run a progressive fallback:

```bash
agilab dry-run
agilab first-proof --json --with-ui
```

`agilab dry-run` is the fast alias for `agilab first-proof --dry-run`; it
checks only CLI/core readiness.
`agilab first-proof --json --with-ui` runs the full onboarding contract and
writes `run_manifest.json` for the local UI path.

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
| `ui` extra | Streamlit UI, page helpers, pandas/network graph utilities, `agi-apps` public built-in projects, and `agi-pages` analysis page bundles. | Running the local product UI with the public demo projects and analysis views available. |
| `examples` extra | `agi-apps` public built-in apps/examples plus notebook/demo helper dependencies such as JupyterLab and optional plotting packages. | Running packaged notebooks, demos, learning examples, and package first-proof routes. |
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

The source repository intentionally keeps runtime packages, UI, built-in apps,
examples, release tooling, agent workflows, and docs together so release proof
can validate one coherent tree. Their stability differs:

| Area | Role | Stability contract |
|---|---|---|
| `src/agilab/core/*` | Runtime packages and compact API. | Stable where documented. |
| `src/agilab/lib/agi-gui`, `src/agilab/pages` | Streamlit UI. | Beta product surface. |
| `src/agilab/lib/agi-apps` | PyPI package carrying public built-in apps/examples. | Packaged asset surface for the `ui` and `examples` extras. |
| `src/agilab/lib/agi-pages` | PyPI package carrying public analysis page bundles. | Packaged page-bundle surface for the `ui` and `pages` extras. |
| `src/agilab/apps/builtin` | First-proof and demo apps. | Packaged examples, not deployment templates. |
| `src/agilab/examples` | Learning scripts and notebooks. | Educational examples with optional dependencies. |
| `tools`, `.github`, IDE and agent folders | Contributor/release automation. | Maintainer tooling, not runtime API. |

Local source checkouts can grow after runs because app `.venv` directories,
build outputs, caches, logs, and datasets are created locally. Those artifacts
are not the package contract. Public wheels exclude virtual environments,
tests, `docs/html`, build directories, generated C files, `__pycache__`, `.pyc`,
and `.egg-info` artifacts.

## Choose Your Path

1. Preview the product quickly: [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab)
2. Understand notebook-to-app migration: [Notebook Migration Demo](https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html)
3. Prove the full source-checkout flow: [Source Checkout](#source-checkout)
4. Verify a CLI-only package install: [Published Package](#published-package)
5. Audit external apps and evidence: [App Repository Updates](#app-repository-updates) and [Release Proof](https://thalesgroup.github.io/agilab/release-proof.html)

For a single-page adoption checklist, use
[ADOPTION.md](https://github.com/ThalesGroup/agilab/blob/main/ADOPTION.md).

## Source Version vs Package Version

AGILAB publishes from the GitHub repository, but each public surface has a
distinct role:

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

Follow the in-app pages from `PROJECT` to `ANALYSIS`. To collect the same check
as JSON:

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

The PyPI README is only the install entry page. Detailed capability evidence,
compatibility status, and roadmap scope live in:

- [Features](https://thalesgroup.github.io/agilab/features.html)
- [Release proof](https://thalesgroup.github.io/agilab/release-proof.html)
- [Compatibility matrix](https://thalesgroup.github.io/agilab/compatibility-matrix.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Package publishing policy](https://thalesgroup.github.io/agilab/package-publishing-policy.html)
- [Future work](https://thalesgroup.github.io/agilab/roadmap/agilab-future-work.html)

## Evaluation Snapshot

Current public evaluation summary, refreshed from the public KPI bundle:

- `4.0 / 5` for ease of adoption, research experimentation, and engineering prototyping.
- `3.0 / 5` for production readiness.
- `4.2 / 5` for strategic potential.

These are AI/ML workbench scores, not production MLOps claims.
They cover project setup, environment management, execution, and result analysis.
The overall score is the rounded category average, not a strategic score.

## Read Next

- [Demo chooser](https://thalesgroup.github.io/agilab/demos.html)
- [Demo capture guide](https://thalesgroup.github.io/agilab/demo_capture_script.html)
- [Quick start](https://thalesgroup.github.io/agilab/quick-start.html)
- [Adoption guide](https://github.com/ThalesGroup/agilab/blob/main/ADOPTION.md)
- [Notebook quickstart](https://thalesgroup.github.io/agilab/notebook-quickstart.html)
- [Documentation](https://thalesgroup.github.io/agilab)
- [Flight project guide](https://thalesgroup.github.io/agilab/flight-project.html)
- [Source repository](https://github.com/ThalesGroup/agilab)
- [Issues](https://github.com/ThalesGroup/agilab/issues)
