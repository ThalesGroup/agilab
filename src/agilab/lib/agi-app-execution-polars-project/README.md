# agi-app-execution-polars-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-execution-polars-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-execution-polars-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-execution-polars-project.svg)](https://pypi.org/project/agi-app-execution-polars-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-execution-polars-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-execution-polars-project` publishes the `execution_polars_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="execution_polars_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-execution-polars-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
