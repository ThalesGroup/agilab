# AGI Apps

[![PyPI version](https://img.shields.io/pypi/v/agi-apps.svg?cacheSeconds=300)](https://pypi.org/project/agi-apps/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-apps.svg)](https://pypi.org/project/agi-apps/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-apps)](https://opensource.org/licenses/BSD-3-Clause)

`agi-apps` is the umbrella package for public AGILAB app project
distributions. The app code now lives in focused packages such as
`agi-app-flight-project`, `agi-app-mycode-project`, and
`agi-app-meteo-forecast-project`.

The umbrella keeps the lightweight `agilab.apps.install` helper and
`agilab.examples` learning assets. Per-app project packages are built as
release artifacts and can be installed independently once their PyPI publishers
are configured.

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
- `agilab.examples`: runnable scripts, previews, and notebook examples.
- `agi-app-*-project`: self-contained release artifacts that expose app project
  roots through the `agilab.apps` entry point group when installed.

The package contains public examples and the app catalog, not private enterprise
app templates or a production MLOps platform.
