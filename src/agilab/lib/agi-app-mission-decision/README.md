# agi-app-mission-decision

[![PyPI version](https://img.shields.io/pypi/v/agi-app-mission-decision.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-mission-decision/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-mission-decision.svg)](https://pypi.org/project/agi-app-mission-decision/)
[![License: BSD 3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-mission-decision` publishes the `mission_decision_project` AGILAB app
project as a self-contained package payload. The package advertises the project
through the `agilab.apps` entry point group so
`AgiEnv(app="mission_decision_project")` can resolve it without a monorepo
checkout.

## Install

```bash
pip install agi-app-mission-decision
```

Most users install these app packages through the umbrella `agi-apps` package or
through `agilab[ui]` / `agilab[examples]`.
