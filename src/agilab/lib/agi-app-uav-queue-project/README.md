# agi-app-uav-queue-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-uav-queue-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-uav-queue-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-uav-queue-project.svg)](https://pypi.org/project/agi-app-uav-queue-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-uav-queue-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-uav-queue-project` publishes the `uav_queue_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="uav_queue_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-uav-queue-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
