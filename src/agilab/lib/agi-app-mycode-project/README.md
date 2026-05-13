# agi-app-mycode-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-mycode-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-mycode-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-mycode-project.svg)](https://pypi.org/project/agi-app-mycode-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-mycode-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-mycode-project` publishes the `mycode_project` AGILAB app project as a self-contained
package payload. The package advertises the project through the `agilab.apps`
entry point group so `AgiEnv(app="mycode_project")` can resolve it without a
monorepo checkout.

## Install

```bash
pip install agi-app-mycode-project
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
