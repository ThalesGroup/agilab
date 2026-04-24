# AGI-CORE

[![PyPI version](https://img.shields.io/pypi/v/agi-core.svg?cacheSeconds=300)](https://pypi.org/project/agi-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-core.svg)](https://pypi.org/project/agi-core/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-core)](https://opensource.org/licenses/BSD-3-Clause)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-core.svg)](https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-core)
[![docs](https://img.shields.io/badge/docs-agilab-brightgreen.svg)](https://thalesgroup.github.io/agilab)

`agi-core` is the AGILAB meta-package that wires `agi-env`, `agi-node`, and `agi-cluster` for one-step installation.

## Quick install

```bash
pip install agi-core
```

## agi-core demo

<p>
  <a href="https://huggingface.co/spaces/jpmorard/agilab"><img src="https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge" alt="AGILAB Space" /></a>
  <a href="https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb"><img src="https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge" alt="agi-core notebook" /></a>
</p>

Use the public AGILAB Space for the UI-oriented demo path, or the notebook
badge for the package-oriented `agi-core` first-run path. The Kaggle notebook
prepares an isolated runtime venv under `/kaggle/working`, instead of mutating
the base notebook kernel packages. For the full notebook matrix, including
Colab and source-checkout variants, see the
AGILAB agi-core demo page:
https://thalesgroup.github.io/agilab/notebook-quickstart.html

Kaggle note: enable Internet in the notebook settings for the first install.

## Why install this package

- Get the three AGILAB core libraries as a single dependency set.
- Use it as a stable base when building AGILAB-based tools.
- Keep versions aligned across the AGILAB ecosystem.

## Repository

- Source: https://github.com/ThalesGroup/agilab/tree/main/src/agilab/core/agi-core
- Docs: https://thalesgroup.github.io/agilab
- Issues: https://github.com/ThalesGroup/agilab/issues
