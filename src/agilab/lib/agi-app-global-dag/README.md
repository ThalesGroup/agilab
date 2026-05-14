# agi-app-global-dag

[![PyPI version](https://img.shields.io/pypi/v/agi-app-global-dag.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-global-dag/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-global-dag.svg)](https://pypi.org/project/agi-app-global-dag/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-global-dag)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-global-dag` publishes the `global_dag_project` AGILAB app project as a
self-contained payload. The distribution name is PyPI-facing; the installed
AGILAB project name remains `global_dag_project`.

The package advertises the project through the `agilab.apps` entry point group
so `AgiEnv(app="global_dag_project")` can resolve it without a monorepo
checkout.

## Install

```bash
pip install agi-app-global-dag
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
