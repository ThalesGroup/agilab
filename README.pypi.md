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
agilab first-proof --json --with-ui
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
uv --preview-features extra-build-dependencies tool install --upgrade agilab
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
