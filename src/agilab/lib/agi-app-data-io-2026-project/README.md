# agi-app-data-io-2026-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-data-io-2026-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-data-io-2026-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-data-io-2026-project.svg)](https://pypi.org/project/agi-app-data-io-2026-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-data-io-2026-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-data-io-2026-project` publishes the `data_io_2026_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="data_io_2026_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-data-io-2026-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
