# R Runtime Bridge

`r_runtime_bridge_project` proves the narrow AGILAB contract for executing an
external R payload through `Rscript`.

## Purpose

Use this project when existing R code should remain an app-owned stage while
AGILAB still owns orchestration, artifacts, manifests, and reducer evidence.

## What You Learn

- How Python manager/worker code can call `Rscript` without shell execution.
- How input JSON, output JSON, artifact files, stdout, and stderr become
  evidence.
- How the adapter keeps R scripts inside the active app root.
- How to document external runtime requirements without making the whole worker
  R-native.

## Run In AGILAB

1. Install `Rscript` and the R package `jsonlite`.
2. Select `r_runtime_bridge_project` in `PROJECT`.
3. Open `ORCHESTRATE`.
4. Keep the default payload and run `INSTALL`, then `EXECUTE`.

## Expected Inputs

The default payload is `{"x": [1, 2, 3, 4, 5]}` and the default script is
`scripts/summarize.R`.

## Expected Outputs

The R script writes output JSON with `n`, `mean`, and `sd`, plus logs and
artifact metadata under `r_runtime_bridge/evidence`.

## Change One Thing

After the default run works, change only the numeric vector in the input JSON.
The output mean and standard deviation should change while the manifest schema
stays stable.

## Troubleshooting

If the run reports missing `Rscript`, install R or put `Rscript` on `PATH`. If
`jsonlite` is missing, run `install.packages("jsonlite")` in R. If a custom
script is rejected, keep it under the active app root.

## Scope

This is a reproducible adapter for R stages. It is not an R-native worker
runtime and does not execute arbitrary scripts outside the app boundary.
