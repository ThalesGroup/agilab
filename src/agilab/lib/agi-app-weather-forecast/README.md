# agi-app-weather-forecast

[![PyPI version](https://img.shields.io/pypi/v/agi-app-weather-forecast.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-weather-forecast/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-weather-forecast.svg)](https://pypi.org/project/agi-app-weather-forecast/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-weather-forecast)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-weather-forecast` publishes the `weather_forecast_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="weather_forecast_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-weather-forecast
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
