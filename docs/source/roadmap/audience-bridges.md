# Audience bridges

Status: dependency-light bridge MVPs are shipped for the commands listed below.
They are adoption and evidence handoff surfaces, not a production R-native worker
rewrite and not replacements for Quarto, MLflow, Hugging Face, DuckDB, Airflow,
Dagster, VS Code, or MCP-native tooling.

## Executive recommendation

The highest-leverage audience bridge is not a pure R interface. It is a
Quarto / R / notebook bridge.

In one sentence:

> Build `agilab export quarto` and `agilab run quarto` so researchers can turn
> an AGILAB run into a reproducible Quarto report, and Quarto/R users can run
> AGILAB stages without leaving their normal workflow.

This reaches more people than R worker support alone because Quarto sits across
R, Python, Jupyter, VS Code, RStudio, Positron, and publishing workflows.

AGILAB should position itself as:

```text
the reproducible execution and evidence engine
```

Bridge features then make that evidence useful to different communities:
Quarto, R, MCP, Hugging Face, MLflow, VS Code, DuckDB, dbt, Airflow, and
Dagster.

## Shipped MVP baseline

The current baseline implements the bridge command surface without adding heavy
runtime dependencies to the base install:

```bash
agilab export quarto --run run_manifest.json --output report.qmd
agilab run quarto --run run_manifest.json --output report.qmd
agilab mcp serve --read-only
agilab export hf-space --project my_project --output hf_space/ --force
agilab export mlflow --run run_manifest.json --output mlflow_handoff.json
agilab import mlflow --experiment demo --input mlflow_handoff.json --output import.json
agilab init vscode --root .
agilab run duckdb --query analysis.sql --output evidence/ --plan-only
agilab export airflow-dag --run run_manifest.json --output agilab_dag.py
agilab export dagster-job --run run_manifest.json --output agilab_job.py
```

The app-local `r_stage_smoke_project` remains the proof that AGILAB can execute
an external R payload through the `Rscript` + JSON + artifact contract. Live
Rscript tests are skipped when R is not installed.

## Bridge priority ranking

| Priority | Bridge | Audience gained | Why it fits AGILAB |
|---:|---|---|---|
| 1 | Quarto / R bridge | R users, academics, statisticians, pharma, reproducible-research users | Turns AGILAB evidence into publishable reports. |
| 2 | MCP and agent evidence bridge | AI-agent users, Claude, ChatGPT, VS Code, Cursor users | Lets agents inspect, summarize, continue, and link AGILAB evidence workflows without executing projects. |
| 3 | Hugging Face bridge | ML demo builders and the open-source ML community | Makes AGILAB apps easier to try publicly. |
| 4 | Deeper MLflow bridge | MLOps engineers | Positions AGILAB as reproducible execution around MLflow tracking. |
| 5 | VS Code / devcontainer bridge | Python developers, data scientists, students | Reduces install and first-run friction. |
| 6 | DuckDB / dbt / SQL bridge | Analytics engineers and data teams | Brings AGILAB to reproducible tabular analysis. |
| 7 | Airflow / Dagster exporter | Production workflow teams | Hands off validated pipelines without making AGILAB a production scheduler. |

## 1. Quarto / R bridge first

AGILAB already has the right identity:

```text
notebook/script
  -> executable app
  -> controlled run
  -> artifacts and evidence
```

Quarto is now the human-facing report layer for AGILAB manifests:

```bash
agilab export quarto \
  --run ~/log/execute/flight_telemetry/latest/run_manifest.json \
  --output report.qmd
```

Then:

```bash
quarto render report.qmd
```

The generated `.qmd` includes:

- run summary
- parameters
- stage order
- artifact table
- artifact hashes
- metrics
- plots
- stdout/stderr links
- environment summary
- MLflow handoff, when enabled

For R users, a later lightweight R client can wrap the same contract:

```r
library(agilab)

run <- agilab_run(
  project = "flight_telemetry_project",
  args = list(...)
)

agilab_quarto_report(run)
```

This is stronger than only adding Rscript support because it gives R users a
reason to care: AGILAB becomes a reproducible evidence engine feeding their
reports.

### Quarto MVP

Shipped files:

```text
tools/agilab_quarto_export.py
test/test_audience_bridges.py
docs/source/quarto-users.rst
```

Core behavior:

```text
read run_manifest.json
collect recorded artifacts and hashes
write report.qmd
optionally call quarto render if available
fail gracefully if quarto is missing
```

Generated output:

```text
agilab-run-report.qmd
agilab-run-report.html when Quarto is installed and rendering is requested
manifest.json
```

Message to users:

> Use AGILAB to execute the experiment. Use Quarto to publish the proof.

## 2. R users

R support should remain an external stage runtime, not an R-native worker.

The app-local R stage smoke project is the right baseline:

```text
input.json
   -> Rscript stage.R input.json output.json artifacts/
   -> output.json + artifacts + stdout/stderr
   -> AGILAB manifest/evidence
```

The adapter contract must stay narrow:

- call `Rscript` using argv lists
- never use `shell=True`
- validate script paths against the app root
- write `input.json`
- read `output.json`
- capture and redact stdout/stderr
- enforce a timeout
- store artifacts under the run directory
- skip live smoke tests when `Rscript` is unavailable

Shared core changes should wait until this payload-plane proof remains useful
across real examples.

## 3. MCP and agent evidence bridge, read-first

The second strongest audience bridge is MCP plus agent-run evidence because it
plugs AGILAB into the AI-agent ecosystem without weakening the execution
boundary.

Do not start with "agents can execute everything." Start with a safe read-first
server:

```text
agilab-mcp
  tools:
    list_projects
    list_runs
    list_agent_runs
    read_manifest
    read_agent_run
    list_artifacts
    summarize_run
    summarize_agent_run
    compare_runs
    export_quarto_report
    agent_handoff
    agent_next_actions
    agent_context
    agent_lineage

  dangerous tools, disabled by default:
    run_project
    install_app
    execute_stage
```

Default policy:

```text
read-only by default
local files only
no project execution
no install commands
no shell commands
no secret-bearing artifact output
```

The shipped agent-run read side adds the operational layer agents need to work
across sessions:

```bash
agilab agent-run list --tag review --metadata branch=main --json
agilab agent-run handoff ~/log/agents/codex/<run-id>
agilab agent-run next ~/log/agents/codex/<run-id> --json
agilab agent-run context --tag review --limit 5 --json
agilab agent-run lineage <run-id> --json
```

The value proposition is simple: ask an AI assistant why an experiment or agent
task failed, let it inspect AGILAB evidence, hand it a safe continuation card,
and preserve the follow-up chain without granting execution authority.

## 4. Hugging Face bridge

The public demo route is now available as a systematic export command:

```bash
agilab export hf-space \
  --project my_project \
  --sdk docker \
  --output hf_space/
```

Prefer Docker Spaces over a Streamlit SDK-only path.

Generated structure:

```text
hf_space/
  README.md
  Dockerfile
  app.py
  requirements.txt
  agilab_project/
  evidence/
```

The export fails clearly when text project inputs contain secret-like assignments
or secret URI references. It should not require private credentials for the
generated demo.

## 5. MLflow bridge

AGILAB should not compete with MLflow.

Positioning:

> MLflow tracks experiments. AGILAB makes the execution reproducible and
> evidence-backed.

Support is available through JSON handoff files:

```bash
agilab export mlflow --run run_manifest.json
agilab import mlflow --experiment my_experiment
```

Suggested mapping:

| AGILAB evidence | MLflow concept |
|---|---|
| run parameters | params |
| metrics | metrics |
| artifact hashes | artifacts / tags |
| manifest path | artifact |
| environment summary | tags / artifact |
| stage outputs | artifacts |
| run status | status / tags |

MLflow owns tracking. AGILAB owns the reproducible execution context.

## 6. VS Code and devcontainers

This bridge is adoption infrastructure:

```bash
agilab init vscode
```

Generated files:

```text
.devcontainer/devcontainer.json
.vscode/tasks.json
.vscode/launch.json
AGILAB_QUICKSTART.md
```

Suggested tasks:

- Run first proof
- Run selected app
- Open manifest
- Export Quarto report
- Start local UI
- Run security check
- Run targeted tests

## 7. DuckDB / dbt / SQL bridge

The shipped SQL bridge starts with DuckDB, not full dbt:

```bash
agilab run duckdb \
  --query analysis.sql \
  --input data.parquet \
  --params params.json \
  --output run/
```

Contract:

```text
input database or parquet/csv
SQL file
parameters JSON
result table
result hash
query hash
manifest
optional Quarto report
```

This pairs well with the Quarto bridge and brings AGILAB to analysts, not only
AI/ML engineers.

## 8. Airflow / Dagster exporter

This remains a handoff exporter, not a scheduler implementation.

Do not make AGILAB an Airflow or Dagster competitor. Use AGILAB as the proof and
validation layer:

```bash
agilab export airflow-dag --project my_project
agilab export dagster-job --project my_project
```

The generated DAG or job should be a handoff artifact:

```text
AGILAB validates and proves the workflow.
Airflow or Dagster schedules it in production.
```

## Recommended implementation order

Phase 1: reproducible reporting audience

1. `agilab export quarto`
2. Quarto smoke report from an existing run manifest
3. `docs/source/quarto-users.rst`

Phase 2: R users

4. Keep `r_stage_smoke_project` as the app-local proof
5. Reuse the Rscript JSON/artifact adapter contract
6. Add an optional small R client only after the app-local proof is useful

Phase 3: AI-agent audience

7. Read-only `agilab-mcp`
8. Manifest and artifact summary tools
9. Compare-runs
10. Export-Quarto-report tool

Phase 4: public demo audience

11. Hugging Face Docker Space exporter
12. Sample evidence bundle
13. Public demo docs

Phase 5: MLOps and analytics audiences

14. MLflow export/import
15. DuckDB SQL run bridge
16. Airflow/Dagster export only after the above are stable

## Implementation baseline

The first implementation baseline is:

```text
agilab export quarto plus the read-first and handoff bridge commands
```

not:

```text
R-native worker
```

Implemented scope:

```text
src/agilab/bridge_cli.py
src/agilab_mcp/
tools/agilab_quarto_export.py
tools/agilab_hf_space_export.py
test/test_audience_bridges.py
docs/source/quarto-users.rst
```

Validation:

```bash
pytest -q test/test_audience_bridges.py
pytest -q test/test_r_stage_smoke_project.py
```

## Product story

The bridge strategy gives AGILAB a broader adoption story:

```text
Python users run AGILAB.
R users run AGILAB stages.
Quarto users publish AGILAB evidence.
AI agents inspect AGILAB evidence.
Hugging Face users try AGILAB live.
MLflow users keep their tracking stack.
SQL users get reproducible tabular analysis.
Production teams export validated workflows.
```

That is stronger than "AGILAB has an R interface."

Best framing:

> AGILAB is the evidence engine for reproducible computational work.

The bridges are how each community consumes that evidence.
