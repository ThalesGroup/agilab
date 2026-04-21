[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)

# AGILAB

AGILAB is an open-source platform for reproducible AI and ML workflows.

The core idea is simple: keep one app on one control path from setup to visible
evidence instead of splitting the workflow across ad hoc scripts,
environments, and analysis glue.

## Try It Before Installing

- Public demo entry points: https://thalesgroup.github.io/agilab/demos.html
- Quick start: https://thalesgroup.github.io/agilab/quick-start.html

If this is your first evaluation, the safest truthful first proof is still the
built-in `flight_project` local path documented in the quick start.

## Install The Published Package

```bash
pip install agilab
agilab
```

This is the thinnest packaged entry point. It is useful for public evaluation,
but it is less representative of the full source-checkout workflow than the
recommended newcomer first proof.

## Other Ways To Try AGILAB

- agi-core demo: https://thalesgroup.github.io/agilab/notebook-quickstart.html
- AGILAB demo: https://thalesgroup.github.io/agilab/quick-start.html#hosted-agilab-demo
- Source repository: https://github.com/ThalesGroup/agilab

For public viewers without accounts, self-host the AGILAB demo on your own VM.
Lightning is only one optional operator-side hosting background for the same
launcher. It is not required to install, run, or develop with AGILAB.

## Why Use It

- Run the same app through local execution, distributed workers, or service mode.
- Keep environments, logs, outputs, and analysis tied to the same app context.
- Make replayable workflow steps explicit instead of burying them in shell history.

## Read Next

- Documentation: https://thalesgroup.github.io/agilab
- Newcomer guide: https://thalesgroup.github.io/agilab/newcomer-guide.html
- Compatibility matrix: https://thalesgroup.github.io/agilab/compatibility-matrix.html
- Flight project guide: https://thalesgroup.github.io/agilab/flight-project.html
- Issues: https://github.com/ThalesGroup/agilab/issues
