# agi-app-global-dag-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-global-dag-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-global-dag-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-global-dag-project.svg)](https://pypi.org/project/agi-app-global-dag-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-global-dag-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-global-dag-project` publishes the `global_dag_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="global_dag_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-global-dag-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
