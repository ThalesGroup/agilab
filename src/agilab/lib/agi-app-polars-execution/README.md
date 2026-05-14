# agi-app-polars-execution

[![PyPI version](https://img.shields.io/pypi/v/agi-app-polars-execution.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-polars-execution/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-polars-execution.svg)](https://pypi.org/project/agi-app-polars-execution/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-polars-execution)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-polars-execution` publishes the `execution_polars_project` AGILAB app
project as a self-contained payload. The distribution name is PyPI-facing; the
installed AGILAB project name remains `execution_polars_project`.

The package advertises the project through the `agilab.apps` entry point group
so `AgiEnv(app="execution_polars_project")` can resolve it without a monorepo
checkout.

## Install

```bash
pip install agi-app-polars-execution
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
