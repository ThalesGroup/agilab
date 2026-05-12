# AGI Pages

[![PyPI version](https://img.shields.io/pypi/v/agi-pages.svg?cacheSeconds=300)](https://pypi.org/project/agi-pages/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-pages.svg)](https://pypi.org/project/agi-pages/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-pages)](https://opensource.org/licenses/BSD-3-Clause)

`agi-pages` packages optional public analysis view modules for AGILAB. When the
package is installed, the AGILAB ANALYSIS page can discover reusable views for
maps and topology, training reports, release decisions, queue/resilience
analysis, and related run-result inspections.

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
