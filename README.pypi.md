[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)

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

Try this first:

```bash
pip install "agilab[ui]"
agilab first-proof --json --with-ui
agilab
```

## Quick Start

[![AGILAB Space](https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge)](https://huggingface.co/spaces/jpmorard/agilab)
[![agi-core notebook](https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge)](https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb)

The public AGILAB Space is the fastest browser preview. It opens the lightweight
`flight_project` path by default and also exposes the
`meteo_forecast_project` notebook-migration demo with forecast analysis views.
Understand notebook-to-app migration with the Notebook Migration Demo:
https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html
Advanced scenarios such as `data_io_2026_project`,
`execution_pandas_project`, `execution_polars_project`, and
`uav_relay_queue_project` are collected in the Advanced Proof Pack:
https://thalesgroup.github.io/agilab/advanced-proof-pack.html

### Maturity snapshot

| Capability | Status |
|---|---|
| Local run | Stable |
| UI Streamlit | Stable |
| Distributed (Dask) | Beta |
| MLflow | Beta |
| Production | Experimental |
| Agents RL | Roadmap |

AGILAB is strongest in the bridge between notebook experimentation and
reproducible AI applications: local execution, controlled environments, and
analysis views. Broader production MLOps claims are intentionally limited and
should be delivered with specialized production stacks.

## First Run

Run the installable product path with the built-in `flight_project`:

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py
```

Follow the in-app pages from `PROJECT` to `ANALYSIS`. To collect the same check
as JSON:

```bash
uv --preview-features extra-build-dependencies run agilab first-proof --json --with-ui
```

The JSON proof writes `run_manifest.json` under `~/log/execute/flight/`. For
installer flags, IDE run configs, and troubleshooting, use the Quick Start docs.

## Install The Published Package

```bash
pip install agilab
agilab first-proof --json
pip install "agilab[ui]"
agilab first-proof --json --with-ui
agilab
```

The base install is the thinnest public CLI/core entry point. Use
`agilab first-proof --json` for a quick package-level check. Install
`agilab[ui]` before launching the local Streamlit app or running
`agilab first-proof --with-ui`. For the most representative full product run,
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
`.previous` directory is kept only for manual recovery. The public service-mode
path docs define the full update contract.

## Evidence And Scope

The PyPI README is only the install entry page. Detailed capability evidence,
compatibility status, and roadmap scope live in the public docs:

- Features: https://thalesgroup.github.io/agilab/features.html
- Compatibility matrix: https://thalesgroup.github.io/agilab/compatibility-matrix.html
- MLOps positioning: https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html
- Future work: https://thalesgroup.github.io/agilab/roadmap/agilab-future-work.html

## Evaluation Snapshot

Current public evaluation is `3.8 / 5`, from the four evidence-backed public
KPI scores: adoption `4.0 / 5`, research experimentation `4.0 / 5`,
engineering prototyping `4.0 / 5`, and production readiness `3.0 / 5`.
Strategic potential is tracked separately at `4.2 / 5`. These are AI/ML
experimentation-workbench scores, not production MLOps claims. Validation
includes local and external macOS checks, AI Lightning, Hugging Face, one
bare-metal cluster, and one VM-based cluster. Azure, AWS, and GCP deployments
remain validation gaps.

## Read Next

- Demo chooser: https://thalesgroup.github.io/agilab/demos.html
- Demo capture guide: https://thalesgroup.github.io/agilab/demo_capture_script.html
- Quick start: https://thalesgroup.github.io/agilab/quick-start.html
- Adoption guide: https://github.com/ThalesGroup/agilab/blob/main/ADOPTION.md
- Notebook quickstart: https://thalesgroup.github.io/agilab/notebook-quickstart.html
- Documentation: https://thalesgroup.github.io/agilab
- Flight project guide: https://thalesgroup.github.io/agilab/flight-project.html
- Source repository: https://github.com/ThalesGroup/agilab
- Issues: https://github.com/ThalesGroup/agilab/issues
