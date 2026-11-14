# Audience bridges

Status reconciled on 2026-11-14 against source checkpoint
`f1710f981b57a079c48fdac6898e4c9dc8f9e505`. The published root release remains
[`2026.11.02`](https://github.com/ThalesGroup/agilab/releases/tag/v2026.11.02)
(PyPI `2026.11.2`). The bridge command MVPs exist, and actual local execution
is now qualified for the tool cohorts below. Source changes, package publication,
local execution and hosted deployment retain separate evidence boundaries.

| Bridge | Qualified local behavior | Remaining qualification |
| --- | --- | --- |
| R | Native R execution, repeat success, empty-input handling and finalized artifact digests; [source summary correction](https://github.com/ThalesGroup/agilab/pull/1233) | Additional platforms and workloads; the correction is not in November 2 packages |
| Quarto | Actual rendering of an AGILAB evidence report with the installed tool | More report formats, publishing targets and platforms |
| Read-only MCP | Actual stdio server/client evidence access | Hosted transports, authentication and other client environments |
| MLflow | Actual handoff/import against local SQLite-backed tracking | Prepared remote tracking services, identity/access policy and deployment operations |
| DuckDB | Actual DuckDB 2.0.0 engine execution and CLI handoffs | More data/SQL workloads and platform coverage; full dbt integration is separate |
| Airflow and Dagster | Actual local import and execution of generated handoffs | Hosted schedulers, production operations and additional versions/platforms |
| Hugging Face | Export contract and separately recorded public demo evidence | Each new exported project's deployment and health; see {doc}`../release-proof` |
| VS Code / devcontainer | Generated onboarding/task/debug configuration contract | Fresh container startup, editor attachment and additional host platforms |

These local results do not certify hosted services or all platforms and do not
establish scientific scores, throughput or optimization gains. The remaining
work deepens the qualified bridges; it does not reopen their local tool
execution as wholly untested.

Source tests also qualify local optional telemetry-dependency composition with
the normal OpenTelemetry SDK and schema-validation dependencies. External
collector deployment, remote runtime acceptance and correlation across UI and
workers remain open.

The current Linux SDK candidate separately passed normal clone, export and
reimport; its full scientific run awaits capacity and tracking-backend
prerequisites. The installed macOS candidate and published Linux results
retain their original scope.

## Executive recommendation

The highest-leverage audience bridge is not a pure R interface. It is a
Quarto / R / notebook bridge.

In one sentence:

> Qualify and extend `agilab export quarto` and `agilab run quarto` so researchers can turn
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

The app-local `r_runtime_bridge_project` exercises the external `Rscript` +
JSON + artifact contract. Actual native R positive, repeat and empty-input
cases passed in the declared local cohort. Optional-tool tests may still skip
when R is absent; that is a different environment from the qualified run.

## Bridge priority ranking

This ranking orders the next qualification and integration work. The command
MVPs above already exist; the ranking is not a list of missing exporters.

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

The app-local R runtime bridge project is the right baseline:

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
    agent_handoff
    agent_next_actions
    agent_context
    agent_lineage
    compare_agent_runs
    validate_agent_run

  dangerous tools, disabled by default:
    run_project
    install_app
    execute_stage
```

Quarto export stays on the explicit `agilab export quarto` CLI/export bridge,
not on the read-only MCP server, because it writes report files.

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
agilab agent-run compare ~/log/agents/codex/<failed-run> ~/log/agents/codex/<follow-up-run> --json
agilab agent-run validate ~/log/agents/codex/<run-id> --json
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

Use Docker Spaces to serve the native React host and its Python views.

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

## Remaining qualification order

1. Extend the qualified Quarto/R reporting route to more workloads and publishing
   targets while preserving the narrow external-stage artifact contract.
2. Qualify additional MCP clients/transports without granting execution
   authority to the read-only evidence server. Quarto export remains an
   explicit writing CLI action.
3. Validate each new Hugging Face export's actual deployment and health against
   its selected public inputs; an existing demo does not qualify every export.
4. Prepare remote MLflow and scheduler environments before testing service
   identity, network, quota and operations. Keep local SQLite/import/run results
   separate from those service claims.
5. Qualify fresh VS Code/devcontainer startup and additional platforms. Extend
   DuckDB workloads before treating a full dbt bridge as implemented.

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

Focused contract validation:

```bash
pytest -q test/test_audience_bridges.py
pytest -q test/test_r_runtime_bridge_project.py
```

The local cohorts above have actual R, Quarto, read-only MCP stdio, MLflow
SQLite, DuckDB and Airflow/Dagster execution evidence, separate from command
contract tests. Reuse a result only for its bound inputs, tool version and
configuration. A different optional-tool environment, exported Space deployment
or hosted scheduler needs its own prepared run; local success does not establish
production qualification.

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
