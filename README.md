[![PyPI version](https://img.shields.io/badge/PyPI-2025.12.19.post1-informational?logo=pypi)](https://pypi.org/project/agilab)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![pypi_dl](https://img.shields.io/pypi/dm/agilab)]()
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml) [![Coverage](https://codecov.io/gh/ThalesGroup/agilab/branch/main/graph/badge.svg?token=Cynz0It5VV)](https://codecov.io/gh/ThalesGroup/agilab)
[![GitHub stars](https://img.shields.io/github/stars/ThalesGroup/agilab.svg)](https://github.com/ThalesGroup/agilab) [![Commit activity](https://img.shields.io/github/commit-activity/m/ThalesGroup/agilab.svg)](https://github.com/ThalesGroup/agilab/pulse) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ThalesGroup/agilab/pulls) [![Open issues](https://img.shields.io/github/issues/ThalesGroup/agilab)](https://github.com/ThalesGroup/agilab/issues) [![PyPI - Format](https://img.shields.io/pypi/format/agilab)](https://pypi.org/project/agilab/) [![Repo size](https://img.shields.io/github/repo-size/ThalesGroup/agilab)](https://github.com/ThalesGroup/agilab)
[![black](https://img.shields.io/badge/code%20style-black-000000.svg)]()
[![docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![ORCID](https://img.shields.io/badge/ORCID-0009--0003--5375--368X-A6CE39?logo=orcid)](https://orcid.org/0009-0003-5375-368X)


# AGILAB Open Source Project

AGILAB is an integrated experimentation platform that helps data scientists and applied researchers prototype, validate,
and deliver AI/ML applications quickly. The project bundles a curated suite of “agi-*” components (environment, node,
cluster, core libraries, and reference applications) that work together to provide:

- **Reproducible experimentation** with managed virtual environments, dependency tracking, and application templates.
- **Scalable execution** through local and distributed worker orchestration (agi-node / agi-cluster) that mirrors
  production-like topologies.
- **Rich tooling** including Streamlit-powered apps, notebooks, workflow automation, and coverage-guided CI pipelines.
- **Turn‑key examples** covering classical analytics and more advanced domains such as flight simulation, network traffic,
  industrial IoT, and optimization workloads.

The project is licensed under the [BSD 3-Clause License](https://github.com/ThalesGroup/agilab/blob/main/LICENSE) and is
maintained by the Thales Group with community contributions welcomed.

## Repository layout

The monorepo hosts several tightly-coupled packages:

| Package | Location | Purpose |
| --- | --- | --- |
| `agilab` | `src/agilab` | Top-level Streamlit experience, tooling, and reference applications |
| `agi-env` | `src/agilab/core/agi-env` | Environment bootstrap, configuration helpers, and pagelib utilities |
| `agi-node` | `src/agilab/core/agi-node` | Local/remote worker orchestration and task dispatch |
| `agi-cluster` | `src/agilab/core/agi-cluster` | Multi-node coordination, distribution, and deployment helpers |
| `agi-core` | `src/agilab/core/agi-core` | Meta-package bundling the environment/node/cluster components |

Each package can be installed independently via `pip install <package-name>`, but the recommended path for development is
to clone this repository and use the provided scripts.

## Quick start (developer mode)

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps --test-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/AGILAB.py
```

The installer uses [Astral’s uv](https://github.com/astral-sh/uv) to provision isolated Python interpreters, set up
required credentials, run tests with coverage, and link bundled applications into the local workspace.

See the [documentation](https://thalesgroup.github.io/agilab) for alternative installation modes (PyPI/TestPyPI) and end
user deployment instructions.

## Framework execution flow

- **Entrypoints**: Streamlit (`src/agilab/AGILAB.py`) and CLI mirrors call `AGI.run`/`AGI.install`, which hydrate an `AgiEnv` and load app manifests via `agi_core.apps`.
- **Environment bootstrap**: `agi_env` resolves paths (`agi_share_path`, `wenv`), credentials, and uv-managed interpreters before any worker code runs; config precedence is env vars → `~/.agilab/.env` → app settings.
- **Planning**: `agi_core` builds a WorkDispatcher plan (datasets, workers, telemetry) and emits structured status to Streamlit widgets/CLI for live progress.
- **Dispatch**: `agi_cluster` schedules tasks locally or over SSH; `agi_node` packages workers, validates dependencies, and executes workloads in isolated envs.
- **Telemetry & artifacts**: run history and logs are written under `~/log/execute/<app>/`, while app-specific outputs land relative to `agi_share_path` (see app docs for locations).

## Documentation & resources

- 📘 **Docs:** https://thalesgroup.github.io/agilab
- 📦 **PyPI:** https://pypi.org/project/agilab
- 🧪 **Test matrix:** refer to `.github/workflows/ci.yml`
- ✅ **Coverage snapshot:** see badge above (auto-updated after CI)
- 🧾 **Runbook:** [AGENTS.md](AGENTS.md)
- 🛠️ **Developer tools:** scripts in `tools/` and application templates in `src/agilab/apps`

## Contributing

Contributions are encouraged! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on reporting issues,
submitting pull requests, and the review process. Security-related concerns should follow the instructions in
[SECURITY.md](SECURITY.md).

## License

Distributed under the BSD 3-Clause License. See [LICENSE](LICENSE) for full text.
