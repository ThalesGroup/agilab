# AGI-ENV

[![PyPI version](https://img.shields.io/pypi/v/agi-env.svg?cacheSeconds=300)](https://pypi.org/project/agi-env/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-env.svg)](https://pypi.org/project/agi-env/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-env)](https://opensource.org/licenses/BSD-3-Clause)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-env.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-env)
[![API docs](https://img.shields.io/badge/docs-agi--env-brightgreen.svg)](https://thalesgroup.github.io/agilab/agi-env.html)

`agi-env` provides headless environment bootstrap and runtime helpers: paths, credentials, virtual environments,
and launch context.

## Quick install

```bash
pip install agi-env
```

For Streamlit pages and local UI sessions, install the separate UI package:

```bash
pip install agi-gui
```

## Typical usage

- Create or update environment context for runtime sessions.
- Resolve workspace paths consistently across local and shared installs.
- Centralize small utilities used by managers and worker packaging.

## Repository

- Source: https://github.com/ThalesGroup/agilab/tree/main/src/agilab/core/agi-env
- UI package: https://github.com/ThalesGroup/agilab/tree/main/src/agilab/lib/agi-gui
- Docs: https://thalesgroup.github.io/agilab/agi-env.html
- Issues: https://github.com/ThalesGroup/agilab/issues
