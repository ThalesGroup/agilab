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
with narrower runtime constraints are published independently as `agi-page-*`
wheel/sdist payload packages. Install the page package you need alongside
`agi-pages` when a notebook or app depends on that view.

## Portable Chart Specs

`agi-pages` also exposes a lightweight chart contract for page bundles that need
the same dataframe-driven visualization to work in Streamlit, exported
notebooks, and static proof artifacts.

```python
import agi_pages

spec = agi_pages.build_chart_spec(
    [{"step": "train", "accuracy": 0.84}, {"step": "test", "accuracy": 0.82}],
    chart_type="line",
    title="Model metrics",
    x="step",
    y="accuracy",
)

agi_pages.render_streamlit(spec)
```

The spec stores an ECharts-compatible `option`, normalized table records, and a
small evidence block with deterministic hashes for the data, chart option, and
combined chart contract. Page bundles can write `spec.as_dict()` into a proof
artifact, render `agi_pages.render_notebook(spec)` from an exported notebook, or
embed `agi_pages.chart_spec_to_static_html(spec)` in a standalone HTML report.
