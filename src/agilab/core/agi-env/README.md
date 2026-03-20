# AGI-ENV

[![PyPI version](https://img.shields.io/pypi/v/agi-env.svg?cacheSeconds=300)](https://pypi.org/project/agi-env/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-env.svg)](https://pypi.org/project/agi-env/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-env)](https://opensource.org/licenses/BSD-3-Clause)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-env.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-env)
[![docs](https://img.shields.io/badge/docs-agilab-brightgreen.svg)](https://thalesgroup.github.io/agilab)

`agi-env` provides environment bootstrap and runtime helpers used across the AGILAB stack (paths, credentials, virtualenvs,
and application launch context).

## Quick install

```bash
pip install agi-env
```

## Typical usage

- Create or update environment context for AGILAB sessions.
- Resolve workspace paths consistently across local and shared installs.
- Centralize small utilities used by managers and worker packaging.

## Repository

- Source: https://github.com/ThalesGroup/agilab/tree/main/src/agilab/core/agi-env
- Docs: https://thalesgroup.github.io/agilab
- Issues: https://github.com/ThalesGroup/agilab/issues
