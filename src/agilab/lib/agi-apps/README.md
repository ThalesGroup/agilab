# AGI Apps

[![PyPI version](https://img.shields.io/pypi/v/agi-apps.svg?cacheSeconds=300)](https://pypi.org/project/agi-apps/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-apps.svg)](https://pypi.org/project/agi-apps/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-apps)](https://opensource.org/licenses/BSD-3-Clause)

`agi-apps` is the umbrella package for public AGILAB app project
distributions. Promoted app payloads now live in focused PyPI packages such as
`agi-app-mission-decision`, `agi-app-flight-telemetry`,
`agi-app-weather-forecast`, and `agi-app-uav-relay-queue`.

The umbrella keeps the lightweight `agilab.apps.install` helper and
`agilab.examples` learning assets. It also bundles `mycode_project` as the
single minimal built-in starter template. Real demos stay in focused
`agi-app-*` payload packages; remaining app project packages stay as release
artifacts until they are explicitly promoted.

## Quick Install

```bash
pip install agi-apps
```

Most users should install it through AGILAB profiles:

```bash
pip install "agilab[examples]"
pip install "agilab[ui]"
```

## Contents

- `agi_apps`: catalog of public app project distributions.
- `agilab.apps.install`: installer helper used by first-proof and UI workflows.
- `agilab.apps.builtin.mycode_project`: compact starter template for new app
  projects.
- `agilab.examples`: runnable scripts, previews, and notebook examples.
- `agi-app-*`: self-contained app payloads that expose app project roots
  through the `agilab.apps` entry point group when installed.

The package contains public examples and the app catalog, not private enterprise
app templates or a production MLOps platform.
