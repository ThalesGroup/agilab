# agi-app-uav-relay-queue

[![PyPI version](https://img.shields.io/pypi/v/agi-app-uav-relay-queue.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-uav-relay-queue/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-uav-relay-queue.svg)](https://pypi.org/project/agi-app-uav-relay-queue/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-uav-relay-queue)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-uav-relay-queue` publishes the `uav_relay_queue_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="uav_relay_queue_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-uav-relay-queue
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
