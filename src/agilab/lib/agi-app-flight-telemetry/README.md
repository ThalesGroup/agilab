# agi-app-flight-telemetry

[![PyPI version](https://img.shields.io/pypi/v/agi-app-flight-telemetry.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-flight-telemetry/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-flight-telemetry.svg)](https://pypi.org/project/agi-app-flight-telemetry/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-flight-telemetry)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-flight-telemetry` publishes the `flight_telemetry_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="flight_telemetry_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-flight-telemetry
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
