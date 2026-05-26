# R Stage Smoke

`r_stage_smoke_project` proves the narrow AGILAB R integration contract:
AGILAB remains the Python orchestrator and worker runtime, while one worker
stage executes an external R payload through `Rscript`.

The boundary is intentionally simple:

```text
input.json
  -> Rscript scripts/summarize.R input.json output.json artifacts/
  -> output.json + artifacts + stdout/stderr logs
  -> AGILAB manifest and reduce evidence
```

This is not an R-native worker. It is a reproducible stage runtime adapter for
R code that already exists in a project.

## Requirements

- `Rscript` available on `PATH`
- R package `jsonlite`

Install `jsonlite` in R if needed:

```r
install.packages("jsonlite")
```

## Run

Select `r_stage_smoke_project`, open `ORCHESTRATE`, keep the defaults, then run.
The default payload is:

```json
{"x": [1, 2, 3, 4, 5]}
```

Expected R output:

```json
{
  "n": 5,
  "mean": 3,
  "sd": 1.5811
}
```

Artifacts are written under `r_stage_smoke/evidence` and mirrored to the normal
AGILAB analysis artifact path for the active app.
