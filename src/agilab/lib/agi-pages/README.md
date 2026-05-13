# AGI Pages

[![PyPI version](https://img.shields.io/pypi/v/agi-pages.svg?cacheSeconds=300)](https://pypi.org/project/agi-pages/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-pages.svg)](https://pypi.org/project/agi-pages/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-pages)](https://opensource.org/licenses/BSD-3-Clause)

`agi-pages` is the umbrella/provider package for AGILAB public analysis views.
It exposes a small discovery API so the AGILAB ANALYSIS page and exported
notebooks can resolve installed view bundles without embedding the page source
in the root `agilab` wheel.

## Quick Install

```bash
pip install agi-pages
```

Most users should install it through the AGILAB UI profile:

```bash
pip install "agilab[ui]"
```

## Runtime Contract

The package exposes a small provider API:

```python
import agi_pages

print(agi_pages.bundles_root())
```

`agi-env` uses this provider only when `agi-pages` is installed. A base
`agilab` install remains CLI/core-only and does not require this package.

The default umbrella covers the shared AGILAB UI runtime. Specialized views
with narrower runtime constraints are built as release artifacts and can be
installed independently once their PyPI publishers are configured.
