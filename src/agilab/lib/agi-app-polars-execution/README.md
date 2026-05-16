# agi-app-polars-execution

[![PyPI version](https://img.shields.io/pypi/v/agi-app-polars-execution.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-polars-execution/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-polars-execution.svg)](https://pypi.org/project/agi-app-polars-execution/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-polars-execution)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-polars-execution` publishes the `execution_polars_project` AGILAB app
as a self-contained PyPI payload. It mirrors the Pandas execution example with a
Polars worker path.

## Purpose

Use this package to compare AGILAB execution behavior on a deterministic
tabular workload while using Polars for the processing step. It is useful when
you want native dataframe performance without changing the surrounding AGILAB
manager/worker contract.

## Installed Project

The distribution name is `agi-app-polars-execution`; the AGILAB project name is
`execution_polars_project`. The package exposes both `execution_polars` and
`execution_polars_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="execution_polars_project")` works without a monorepo checkout.

## Install

```bash
pip install agi-app-polars-execution
```

Most users get this package through `agi-apps`, `agilab[ui]`, or
`agilab[examples]`; direct installation is useful when validating one app
package in isolation.

## Run In AGILAB

Select `execution_polars_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE`. Start locally, then compare the output with
`execution_pandas_project` if you want an engine-level contrast.

## Expected Inputs

The default run creates its own deterministic CSV workload under shared storage.
No external dataset, cloud account, notebook, or API key is required.

## Expected Outputs

Workers write processed CSV or Parquet outputs and the reducer writes a summary
with row counts, source files, engine labels, score metrics, and execution
metadata.

## Change One Thing

Change the partition count or output format, then compare the reducer summary
against a Pandas run. The point is to change the engine while keeping the
workflow contract stable.

## Scope

This is a synthetic execution-path example. It is useful for validating Polars
worker behavior, not for demonstrating a domain analytics product.
