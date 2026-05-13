# agi-app-flight-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-flight-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-flight-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-flight-project.svg)](https://pypi.org/project/agi-app-flight-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-flight-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-flight-project` publishes the `flight_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="flight_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-flight-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
