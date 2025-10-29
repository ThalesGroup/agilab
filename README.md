[![PyPI version](https://img.shields.io/badge/PyPI-2025.10.29-informational?logo=pypi)](https://pypi.org/project/agilab)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![pypi_dl](https://img.shields.io/pypi/dm/agilab)]()
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)
[![coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ThalesGroup/agilab/badge-data/agilab.json)](https://raw.githubusercontent.com/ThalesGroup/agilab/badge-data/agilab.json)
[![GitHub stars](https://img.shields.io/github/stars/ThalesGroup/agilab.svg)](https://github.com/ThalesGroup/agilab)
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
streamlit run src/agilab/AGILAB.py
```

The installer uses [Astral’s uv](https://github.com/astral-sh/uv) to provision isolated Python interpreters, set up
required credentials, run tests with coverage, and link bundled applications into the local workspace.

See the [documentation](https://thalesgroup.github.io/agilab) for alternative installation modes (PyPI/TestPyPI) and end
user deployment instructions.

## Documentation & resources

- 📘 **Docs:** https://thalesgroup.github.io/agilab
- 📦 **PyPI:** https://pypi.org/project/agilab
- 🧪 **Test matrix:** refer to `.github/workflows/ci.yml`
- 🧾 **Runbook:** [RUNBOOK.md](RUNBOOK.md)
- 🛠️ **Developer tools:** scripts in `tools/` and application templates in `src/agilab/apps`

## Contributing

Contributions are encouraged! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on reporting issues,
submitting pull requests, and the review process. Security-related concerns should follow the instructions in
[SECURITY.md](SECURITY.md).

## License

Distributed under the BSD 3-Clause License. See [LICENSE](LICENSE) for full text.
