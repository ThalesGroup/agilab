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

The public AGILAB Space is the fastest browser preview. It opens the lightweight
`flight_project` path by default; advanced scenarios such as
`uav_relay_queue_project` are documented in the demo guide.

## Choose Your Path

| If you want to... | Start here | Stop when... |
|---|---|---|
| Preview before installing | AGILAB Space | The hosted UI opens the `flight_project` path. |
| Prove the local product flow | Source-checkout first run | `tools/newcomer_first_proof.py --json` returns `PASS`. |
| Check the package entry point | Published package install | `agilab` starts from a clean package install. |
| Update external apps | App repository installer path | Installed apps resolve to the repository copy. |
| Contribute changes | `CONTRIBUTING.md` in the source repository | A focused local check passes before PR. |

For the complete adoption checklist, see:
https://github.com/ThalesGroup/agilab/blob/main/ADOPTION.md

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

## Install The Published Package

```bash
pip install agilab
agilab
```

This is the thinnest public entry point. Use it for a quick package-level check.
For the most representative first proof, prefer the source-checkout
`flight_project` path above because it exercises the same app installation,
execution, and analysis flow documented in the web UI.

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

Current public evaluation is `3.8 / 5`, from the four public KPI scores:
adoption `4.0 / 5`, research experimentation `4.0 / 5`, engineering
prototyping `4.0 / 5`, and production readiness `3.0 / 5`. This is an AI/ML
experimentation-workbench score, not a production MLOps claim. Validation
includes local and external macOS checks, AI Lightning, Hugging Face, one
bare-metal cluster, and one VM-based cluster. Azure, AWS, and GCP deployments
remain validation gaps.

## Read Next

- Demo chooser: https://thalesgroup.github.io/agilab/demos.html
- Quick start: https://thalesgroup.github.io/agilab/quick-start.html
- Adoption guide: https://github.com/ThalesGroup/agilab/blob/main/ADOPTION.md
- Notebook quickstart: https://thalesgroup.github.io/agilab/notebook-quickstart.html
- Documentation: https://thalesgroup.github.io/agilab
- Flight project guide: https://thalesgroup.github.io/agilab/flight-project.html
- Source repository: https://github.com/ThalesGroup/agilab
- Issues: https://github.com/ThalesGroup/agilab/issues
