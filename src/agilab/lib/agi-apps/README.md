# AGI Apps

[![PyPI version](https://img.shields.io/pypi/v/agi-apps.svg?cacheSeconds=300)](https://pypi.org/project/agi-apps/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-apps.svg)](https://pypi.org/project/agi-apps/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-apps)](https://opensource.org/licenses/BSD-3-Clause)

`agi-apps` packages the public AGILAB built-in app projects and learning
examples. It owns the `agilab.apps` and `agilab.examples` payload that the
`agilab[ui]` and `agilab[examples]` profiles use for first-proof runs,
newcomer demos, and workflow examples.

## Quick Install

```bash
pip install agi-apps
```

Most users should install it through AGILAB profiles:

```bash
pip install "agilab[examples]"
pip install "agilab[ui]"
```

`agilab[examples]` adds notebook/demo helper dependencies. `agilab[ui]` adds
the Streamlit UI stack and includes `agi-apps` so the UI opens with the public
built-in projects available.

## Contents

- `agilab.apps.install`: app installer entry point used by first-proof and UI
  workflows.
- `agilab.apps.builtin`: public built-in app projects such as `flight_project`,
  `global_dag_project`, and UAV queue examples.
- `agilab.examples`: runnable scripts, previews, and notebook examples.

The package contains public examples, not private enterprise app templates or a
production MLOps platform.

`agi-apps` is published as a wheel-only package. The payload is assembled from
the AGILAB monorepo during wheel build, so source distributions are deliberately
disabled to avoid incomplete public app archives.
