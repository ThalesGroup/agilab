# agi-app-execution-pandas-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-execution-pandas-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-execution-pandas-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-execution-pandas-project.svg)](https://pypi.org/project/agi-app-execution-pandas-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-execution-pandas-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-execution-pandas-project` publishes the `execution_pandas_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="execution_pandas_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-execution-pandas-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
