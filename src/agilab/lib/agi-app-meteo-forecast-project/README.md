# agi-app-meteo-forecast-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-meteo-forecast-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-meteo-forecast-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-meteo-forecast-project.svg)](https://pypi.org/project/agi-app-meteo-forecast-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-meteo-forecast-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-meteo-forecast-project` publishes the `meteo_forecast_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="meteo_forecast_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-meteo-forecast-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
