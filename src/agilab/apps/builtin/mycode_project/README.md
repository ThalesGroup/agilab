# Mycode Project

`mycode_project` is the minimal built-in AGILAB app template.

It keeps the manager, worker, settings, and form structure small so a developer
can inspect the moving parts of an AGILAB app without reading a full demo
workflow first.

## What It Shows

- the smallest project layout expected by the installer
- an app-local `app_settings.toml` seed and editable argument form
- a concrete worker class that can be deployed by the AGILAB runtime
- the compatibility alias pattern used by older app names

## Typical Flow

1. Select `mycode_project` in `PROJECT`.
2. Run `INSTALL` from `ORCHESTRATE`.
3. Adapt the manager and worker code for a real project-specific workflow.

## Outputs

The default project prepares input and output directories but does not implement
a domain computation. It is meant to be copied or extended.

## Scope

Use this app as a compact reference for app structure. Use the flight,
meteo_forecast, or data_io_2026 demos when you need a complete user-facing
workflow.
