[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)

# AGILAB

AGILAB is an open-source platform for reproducible AI/ML workflows that takes you from
local experimentation to distributed execution and long-lived services.

It combines:

- app scaffolding
- environment isolation
- workflow orchestration
- service health gates
- local and remote worker execution

so teams can move from prototype to production-like operation without rebuilding
their tooling at every stage.

AGILAB is maintained by Thales Group and released under the
[BSD 3-Clause License](https://github.com/ThalesGroup/agilab/blob/main/LICENSE).

## Creator

AGILAB was created by **Jean-Pierre Morard**.

Jean-Pierre Morard builds engineering tooling for reproducible AI workflows,
distributed execution, and operational experimentation.

## What AGILAB gives you

- One control path from Streamlit or CLI entrypoints to isolated local and distributed workers.
- Reproducible execution through managed environments, explicit pipelines, and per-app settings.
- Persistent service mode through `AGI.serve` with health snapshots and restart policies.
- Production-style orchestration using `agi-node` and `agi-cluster` for packaging, dispatch, and remote execution.
- Agent-friendly developer workflow through [`AGENTS.md`](https://github.com/ThalesGroup/agilab/blob/main/AGENTS.md), `.codex/skills`, and Codex helpers.

## Quick links

- Documentation: https://thalesgroup.github.io/agilab
- Execution Playground guide: https://thalesgroup.github.io/agilab/execution-playground.html
- Service mode guide: https://thalesgroup.github.io/agilab/service-mode.html
- Flight project guide: https://thalesgroup.github.io/agilab/flight-project.html
- Source repository: https://github.com/ThalesGroup/agilab
- Discussions: https://github.com/ThalesGroup/agilab/discussions

## Overview

![AGILAB runtime stack](https://raw.githubusercontent.com/ThalesGroup/agilab/main/docs/source/Agilab-Overview.svg)

## Installation

```bash
pip install agilab
agilab --help
```

From source:

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps --test-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py
```

## Example

The built-in Execution Playground compares the same synthetic workload through two
worker paths:

- `execution_pandas_project`
- `execution_polars_project`

This makes it possible to compare execution models, not just dataframe libraries.

Guide:

- https://thalesgroup.github.io/agilab/execution-playground.html

## Learn more

- Full documentation: https://thalesgroup.github.io/agilab
- README on GitHub: https://github.com/ThalesGroup/agilab/blob/main/README.md
- Issues: https://github.com/ThalesGroup/agilab/issues
