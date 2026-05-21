# agi-app-mission-decision

[![PyPI version](https://img.shields.io/pypi/v/agi-app-mission-decision.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-mission-decision/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-mission-decision.svg)](https://pypi.org/project/agi-app-mission-decision/)
[![License: BSD 3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-mission-decision` publishes the `mission_decision_project` AGILAB app
as a self-contained PyPI payload. It demonstrates deterministic mission
decision evidence rather than a storyboard or slide-only demo.

## Purpose

Use this package to run a repeatable decision loop: load a compact mission
scenario, score candidate routes, inject an event, re-plan, and export evidence
that can be inspected by AGILAB analysis pages.

## Installed Project

The distribution name is `agi-app-mission-decision`; the AGILAB project name is
`mission_decision_project`. The package exposes both `mission_decision` and
`mission_decision_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="mission_decision_project")` works without a monorepo checkout.

## Install

```bash
pip install agi-app-mission-decision
```

Most users get this package through `agi-apps`, `agilab[ui]`, or
`agilab[examples]`; direct installation is useful when validating one app
package in isolation.

## Run In AGILAB

From the UI, select `mission_decision_project`, open `ORCHESTRATE`, then run
`INSTALL` and `EXECUTE`. Open `ANALYSIS` with the decision-evidence page to
inspect strategy deltas and the adaptation timeline.

## Expected Inputs

The packaged project includes a deterministic sample scenario. It also includes
offline public macro-context fixtures so the default proof does not need a live
FRED call, API key, private dataset, or network access.

## Expected Outputs

The run writes scenario metrics, generated pipeline evidence, sensor streams,
candidate route tables, decision timelines, and reducer summaries under the
mission-decision output paths.

## Change One Thing

Change a scenario constraint or event severity, then rerun the app. The final
decision artifact should show whether the selected strategy and latency/cost
deltas changed.

## Scope

This is a deterministic R&D app for mission-decision reproducibility. It does
not claim live command-and-control integration, production autonomy, or
enterprise governance.
