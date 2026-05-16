# agi-app-tescia-diagnostic-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-tescia-diagnostic-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-tescia-diagnostic-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-tescia-diagnostic-project.svg)](https://pypi.org/project/agi-app-tescia-diagnostic-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-tescia-diagnostic-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-tescia-diagnostic-project` packages the `tescia_diagnostic_project`
AGILAB app. It is a diagnostic-method example that turns weak assumptions,
evidence, candidate fixes, and regression plans into structured artifacts.

## Purpose

Use this package to test a TeSciA-style engineering diagnostic workflow. The
default path scores bundled cases deterministically; optional local AI engines
can draft new cases, but validated scoring remains explicit and reproducible.

## Installed Project

The distribution name is `agi-app-tescia-diagnostic-project`; the AGILAB
project name is `tescia_diagnostic_project`. The package exposes both
`tescia_diagnostic` and `tescia_diagnostic_project` through the `agilab.apps`
entry point group, so `AgiEnv(app="tescia_diagnostic_project")` resolves the
project without a monorepo checkout.

## Install

```bash
pip install agi-app-tescia-diagnostic-project
```

This package is not pulled by the `agi-apps` umbrella until it is promoted for a
release. Install it directly when validating the diagnostic app package from an
index or a locally built wheel.

## Run In AGILAB

Select `tescia_diagnostic_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE` with bundled cases. Inspect the exported reports under `ANALYSIS` or
the project output directory.

## Expected Inputs

The default input is a bundled JSON case file. Optional local-AI generation
requires a configured local endpoint and fails closed if the generated JSON does
not match the expected schema.

## Expected Outputs

The app writes diagnostic reports, summary CSV files, reducer summaries, and a
`student_score` field that records whether the diagnosis, better fix, and
regression plan are supported by evidence.

## Change One Thing

Add one diagnostic case with a deliberately weak proposed fix and two candidate
regression tests. The app should keep the stronger fix only when the evidence
and tests support it.

## Scope

This is a repeatable diagnostic example. It does not execute remediation
commands, replace incident management, or silently trust model-generated
content.
