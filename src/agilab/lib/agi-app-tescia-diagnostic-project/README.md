# agi-app-tescia-diagnostic-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-tescia-diagnostic-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-tescia-diagnostic-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-tescia-diagnostic-project.svg)](https://pypi.org/project/agi-app-tescia-diagnostic-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-tescia-diagnostic-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-tescia-diagnostic-project` publishes the `tescia_diagnostic_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="tescia_diagnostic_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-tescia-diagnostic-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
