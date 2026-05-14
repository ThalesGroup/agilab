# agi-app-pandas-execution

[![PyPI version](https://img.shields.io/pypi/v/agi-app-pandas-execution.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-pandas-execution/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-pandas-execution.svg)](https://pypi.org/project/agi-app-pandas-execution/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-pandas-execution)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-pandas-execution` publishes the `execution_pandas_project` AGILAB app
project as a self-contained payload. The distribution name is PyPI-facing; the
installed AGILAB project name remains `execution_pandas_project`.

The package advertises the project through the `agilab.apps` entry point group
so `AgiEnv(app="execution_pandas_project")` can resolve it without a monorepo
checkout.

## Install

```bash
pip install agi-app-pandas-execution
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
