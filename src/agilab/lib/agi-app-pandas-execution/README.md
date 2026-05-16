# agi-app-pandas-execution

[![PyPI version](https://img.shields.io/pypi/v/agi-app-pandas-execution.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-pandas-execution/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-pandas-execution.svg)](https://pypi.org/project/agi-app-pandas-execution/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-pandas-execution)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-pandas-execution` publishes the `execution_pandas_project` AGILAB app
as a self-contained PyPI payload. It is a small execution benchmark for the
Pandas worker path.

## Purpose

Use this package to validate AGILAB manager/worker distribution with a
deterministic tabular workload. It generates CSV partitions, processes them with
Pandas, and writes reducer evidence that can be compared across run modes.

## Installed Project

The distribution name is `agi-app-pandas-execution`; the AGILAB project name is
`execution_pandas_project`. The package exposes both `execution_pandas` and
`execution_pandas_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="execution_pandas_project")` works without a monorepo checkout.

## Install

```bash
pip install agi-app-pandas-execution
```

Most users get this package through `agi-apps`, `agilab[ui]`, or
`agilab[examples]`; direct installation is useful when validating one app
package in isolation.

## Run In AGILAB

Select `execution_pandas_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE`. Keep the default local settings for a first proof, then increase
partitions or worker count when you want a stronger distribution check.

## Expected Inputs

The default run creates its own deterministic CSV workload under shared storage.
No external dataset, cloud account, notebook, or API key is required.

## Expected Outputs

Workers write processed tabular outputs and the reducer writes a summary with
row counts, source files, engine labels, score metrics, and dtype/kernel
metadata.

## Change One Thing

Switch the workload kernel or partition count, then compare the reducer summary
from the previous run. The app should keep the same input contract while making
execution-mode differences visible.

## Scope

This is a synthetic execution-path example. It is useful for validating Pandas
worker behavior, not for demonstrating a domain analytics product.
