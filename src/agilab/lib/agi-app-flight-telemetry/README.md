# agi-app-flight-telemetry

[![PyPI version](https://img.shields.io/pypi/v/agi-app-flight-telemetry.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-flight-telemetry/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-flight-telemetry.svg)](https://pypi.org/project/agi-app-flight-telemetry/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-flight-telemetry)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-flight-telemetry` publishes the `flight_telemetry_project` AGILAB app
as a self-contained PyPI payload. It is the first app to try when you want to
prove the AGILAB flow with a concrete dataset and visible analysis output.

## Purpose

Use this package to run a compact flight-data ingestion demo: raw public sample
files are converted into a reusable dataframe dataset, then inspected through
AGILAB analysis pages such as maps and network-style trajectory views.

## Installed Project

The distribution name is `agi-app-flight-telemetry`; the AGILAB project name is
`flight_telemetry_project`. The package exposes both `flight_telemetry` and
`flight_telemetry_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="flight_telemetry_project")` works without a monorepo checkout.

## Install

```bash
pip install agi-app-flight-telemetry
```

Most users get this package through `agi-apps`, `agilab[ui]`, or
`agilab[examples]`; direct installation is useful when validating one app
package in isolation.

## Run In AGILAB

From the UI, select `flight_telemetry_project`, open `ORCHESTRATE`, then run
`INSTALL` and `EXECUTE`. From Python, create an AGILAB environment with
`AgiEnv(app="flight_telemetry_project")` and run the project through the normal
`AGI.run(..., request=RunRequest(...))` path.

## Expected Inputs

The packaged project seeds a small flight dataset under shared storage on first
run. No cloud account, private repository, external database, or API key is
required for the default proof.

## Expected Outputs

The run writes the processed flight dataframe, reducer summaries, and
analysis-ready artifacts under the project output paths. Open `ANALYSIS` with
`view_maps` or `view_maps_network` to inspect the generated evidence.

## Change One Thing

Limit the number of input files or switch the output format, then rerun the app.
The reducer summary should still show which files were read, how many rows were
produced, and which output artifacts were written.

## Scope

This is a public reproducibility demo. It does not claim live aircraft
telemetry, production search ingestion, or a full domain-specific flight-study
platform.
