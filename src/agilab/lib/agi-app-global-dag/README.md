# agi-app-global-dag

[![PyPI version](https://img.shields.io/pypi/v/agi-app-global-dag.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-global-dag/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-global-dag.svg)](https://pypi.org/project/agi-app-global-dag/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-global-dag)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-global-dag` publishes the `global_dag_project` AGILAB app as a
self-contained PyPI payload. It is a read-only workflow-contract example rather
than a domain worker benchmark.

## Purpose

Use this package to understand how AGILAB can connect several app projects with
explicit artifact handoffs. The bundled DAG shows a flight stage producing a
summary artifact that a weather stage can consume.

## Installed Project

The distribution name is `agi-app-global-dag`; the AGILAB project name is
`global_dag_project`. The package exposes both `global_dag` and
`global_dag_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="global_dag_project")` resolves the project without a monorepo
checkout.

## Install

```bash
pip install agi-app-global-dag
```

Most users get this package through `agi-apps`, `agilab[ui]`, or
`agilab[examples]`; direct installation is useful when validating one app
package in isolation.

## Run In AGILAB

Select `global_dag_project`, open `WORKFLOW`, choose the multi-app DAG template,
and inspect the runner-state preview. This package is primarily for workflow
review; use `flight_telemetry_project` or `weather_forecast_project` when you
want to execute concrete worker code.

## Expected Inputs

The package ships a DAG template that names the producer and consumer projects.
No private data, cluster, service mode, or live external service is required for
the default preview.

## Expected Outputs

The preview writes a runner-state JSON file under the AGILAB execution logs and
renders the runnable versus blocked stages. It does not create a domain reducer
artifact because it demonstrates cross-app orchestration, not a worker merge.

## Change One Thing

Edit a handoff name in a copied DAG template and reload the preview. The blocked
stage should make the missing artifact contract obvious before any downstream
execution is attempted.

## Scope

This package teaches global DAG contracts. It is not a scheduler replacement,
an Airflow/Kubeflow clone, or a production workflow governance layer.
