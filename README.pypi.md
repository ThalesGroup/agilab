[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300)](https://pypi.org/project/agilab/)
[![Latest proven release](https://img.shields.io/badge/release%20proof-latest%20proven%20release-0F766E)](https://thalesgroup.github.io/agilab/release-proof.html)
[![Supply chain: SBOM, audit, provenance](https://img.shields.io/badge/supply%20chain-SBOM%20%2B%20audit%20%2B%20provenance-0F766E)](https://thalesgroup.github.io/agilab/release-proof.html)
[![First proof: passing](https://img.shields.io/badge/first%20proof-passing-0F766E)](https://thalesgroup.github.io/agilab/release-proof.html)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![GitHub AI scraper: discoverable](https://img.shields.io/badge/github--ai--scraper-discoverable-0F766E)](https://pypi.org/project/github-ai-scraper/)
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)
[![Skills](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/skills.svg)](https://github.com/ThalesGroup/agilab/blob/main/AGENT_SKILLS.md)
[![Standard: Agent Skills](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/agent-standard.svg)](https://agentskills.io/)
[![Works with](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/agent-works-with.svg)](https://github.com/ThalesGroup/agilab/blob/main/tools/agent_workflows.md)
[![Agent API: CLI Python](https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/agent-api.svg)](https://github.com/ThalesGroup/agilab/blob/main/tools/agent_workflows.md)
[![Style guard: Ruff changed-files](https://img.shields.io/badge/style%20guard-Ruff%20changed--files-0F766E)](https://docs.astral.sh/ruff/)

# AGILAB

AGILAB is an anti-lock-in reproducibility workbench for AI/ML engineering.
It turns notebooks and scripts into executable, portable, evidence-backed apps
while preserving a notebook export path.
That export is an `agi-core` runtime handoff: you can continue to run the saved
project and stage contract with only the stable, production-grade core
technology, without depending on the AGILAB UI or distributed worker layer.
The stable core runtime remains the smallest supported handoff surface.
That means you do not lose your work if the AGILAB UI or distributed runtime is
no longer the right interface. Those apps can run locally or on distributed
workers, and the workflow stays portable: export it back to an `agi-core`
notebook, inspect or adapt the Python stages, and hand off tracking evidence to
MLflow when that integration is enabled.

You do not need a cluster to get AGILAB's core value. The primary adoption path
is local: turn a notebook or script into a replayable app with evidence,
artifacts, analysis views, and a notebook or MLflow handoff. Cluster execution is
a scale-out option after that local proof works.

Use it to keep experimental AI work:

- **one-command setup**
- **controlled environments**
- **local or distributed execution**
- **reviewable run evidence**
- **runnable outside the AGILAB UI as `agi-core` notebooks**
- **optional MLflow integration**

AGILAB complements MLflow and production MLOps platforms. It owns the
reproducible execution and analysis layer around them.
In short: MLflow tracks experiments; AGILAB transforms notebooks and scripts
into executable, portable, evidence-backed AI applications.

## Core Flow

Notebook/script -> AGILAB app -> controlled execution -> artifacts + evidence ->
notebook / MLflow / UI handoff

The flow is reversible where it matters for long-term reuse: WORKFLOW can
export the saved pipeline as a runnable `agi-core` supervisor notebook, so the
code, stage order, runtime hints, and review context remain usable through the
stable, production-grade core technology if the AGILAB UI or distributed
runtime is no longer the right interface for that work.
Apps can also declare multiple UI surfaces, so the same runtime and evidence
contract can be exposed through Streamlit, hosted Hugging Face, or future
NiceGUI/Gradio/FastAPI adapters.

## Demo Routes

Start with the route that matches the proof you want to show:

| Goal | Demo route | What it proves |
|---|---|---|
| Try AGILAB in the browser | [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab) | Hosted `PROJECT` -> `ORCHESTRATE` -> `WORKFLOW` -> `ANALYSIS` path. |
| Choose by objective | [Demo chooser](https://thalesgroup.github.io/agilab/demos.html) | Public router for notebook, UI, proof-pack, and performance demos. |
| Stay notebook-first | [agi-core notebook demo](https://thalesgroup.github.io/agilab/notebook-quickstart.html) | Small `AgiEnv` / `AGI.run(...)` runtime path before the web UI. |
| Migrate a notebook into an app | [Weather notebook migration](https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html) | Notebook stages, `lab_stages.toml`, artifacts, and reusable analysis views. |
| Keep Excel as the front end | [Excel workbook proof](https://thalesgroup.github.io/agilab/excel-users.html) | Workbook inputs plus CSV and JSON evidence without an Office add-in. |
| Keep a notebook dashboard | [Voila notebook proof](https://thalesgroup.github.io/agilab/voila-users.html) | Hide-code notebook dashboard path plus widget-to-args and app-view evidence. |
| Prove database access locally | [SQLite connector proof](https://thalesgroup.github.io/agilab/data-connectors.html#sqlite-database-proof) | Local schema, parameterized SQL query, result CSV, and JSON evidence hashes. |
| Gate candidate data | [Data Quality Gate](https://github.com/ThalesGroup/agilab/tree/main/src/agilab/apps/builtin/data_quality_gate_project) | Contract, drift, leakage, and promotion decision evidence before training. |
| Show performance engineering | [Cython worker speedup demo](https://thalesgroup.github.io/agilab/execution-playground.html) | Worker execution model plus checksum-matched typed-kernel speedup evidence. |
| Show a native extension boundary | [Rust/PyO3 native worker preview](https://thalesgroup.github.io/agilab/execution-playground.html#optional-rust-pyo3-worker-preview) | Generated PyO3/maturin worker skeleton with explicit evidence handoff. |
| Explore an opt-in app | [PyTorch Playground](https://github.com/ThalesGroup/agilab/tree/main/src/agilab/apps/builtin/pytorch_playground_project) | Reproducible classifier playground with live play/pause training, multi-UI surface declarations, generic `agilab app surface ...` launch, and loss-landscape analysis. |
| Go deeper after first proof | [Advanced Proof Pack](https://thalesgroup.github.io/agilab/advanced-proof-pack.html) | Mission decision, execution playground, UAV queue, service, MLflow, and release-proof routes. |

Use the [local quick start](https://thalesgroup.github.io/agilab/quick-start.html)
when you want to run the product locally, the
[demo capture guide](https://thalesgroup.github.io/agilab/demo_capture_script.html)
when preparing screenshots or video, and the
[50-star promotion kit](https://github.com/ThalesGroup/agilab/blob/main/PROMOTE.md)
when sharing the project publicly.

If AGILAB helps you make AI/ML experiments reproducible, please star the
repository so other engineers can find it.

For spreadsheet-first users, the packaged `excel_workbook_proof` preview keeps
Excel as the familiar interface and writes a proof workbook, Power Query-friendly
CSV files, and JSON hash evidence without requiring an Office add-in.

For notebook-dashboard users, the packaged `voila_notebook_proof` preview keeps
the notebook dashboard flow and writes a hide-code manifest, widget-to-args
hints, an app-view plan, and JSON evidence without requiring Voila in the base
install.

## Featured Performance Demo

`execution_pandas_project` is the Cython worker speedup demo. It keeps Pandas
I/O and reducer evidence in Python, then isolates the hot scoring loop as a
typed contiguous `float64` kernel so AGILAB can compare Python and Cython
execution honestly.
The versioned local kernel proof reports `0.620s` Python vs `0.002s` Cython
on 100,000 rows x 32 passes, a checksum-matched `306x` speedup. That is a
focused hot-loop result, not an end-to-end runtime promise.

`flight_telemetry_project` is the real-world worker-only Cython example: the
Polars ingestion and artifact contract stay in Python, while the per-row
haversine distance kernel reports `speed_kernel_runtime`,
`speed_dtype_contract`, and checksum evidence in the reducer summary.

## Quick Start

[![AGILAB Space](https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge)](https://huggingface.co/spaces/jpmorard/agilab)
[![agi-core notebook](https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge)](https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb)

### Local PyPI Proof

```bash
uv --preview-features extra-build-dependencies tool install --upgrade "agilab[examples]"
agilab first-proof --json
agilab adoption-report
```

Use the UI profile only when you also want the local Streamlit pages:

```bash
uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"
agilab
```

For a zero-install browser preview, open the public
[AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab). It opens the
lightweight `flight_telemetry_project` path by default and exposes the
`weather_forecast_project` notebook-migration demo with forecast analysis views.
Advanced scenarios such as `mission_decision_project`,
the `execution_pandas_project` Cython worker speedup demo,
`execution_polars_project`, and `uav_relay_queue_project` are collected in the
[Advanced Proof Pack](https://thalesgroup.github.io/agilab/advanced-proof-pack.html).
For the full project/package/status matrix, see the
[Public App Catalog](https://thalesgroup.github.io/agilab/public-app-catalog.html).

If startup fails, run a progressive fallback:

```bash
agilab dry-run
agilab first-proof --json
agilab adoption-report
```

`agilab dry-run` is the fast alias for `agilab first-proof --dry-run`; it
checks only CLI/core readiness.
`agilab first-proof --json` runs the onboarding contract and writes
`run_manifest.json` without requiring Streamlit. Add `--with-ui` only when you
intentionally want the proof to boot the packaged Streamlit pages too.

### Maturity snapshot

| Capability | Status |
|---|---|
| Local run | Stable |
| Distributed (Dask) | Stable |
| UI Streamlit | Beta |
| MLflow | Beta |
| Production | Experimental |
| RL examples | Example available |

AGILAB is most mature in the bridge between notebook experimentation and
reproducible AI applications: local execution, environment control, and
analysis. Distributed execution is mature in the core runtime; remote cluster
mounts, credentials, and hardware stacks remain environment-dependent.
Production-grade MLOps features are delivered through integrations and are not
yet a packaged platform claim.

## Production Boundary

AGILAB should be adopted as an experimentation and validation workbench first.
Use this boundary before deploying it in sensitive environments:

| Boundary | Status | Required controls |
|---|---|---|
| Go for controlled local use | Local research sandboxes, internal demos, notebook-to-app migration, reproducible validation with non-sensitive data. | Normal repository hygiene and local proof evidence. |
| Go for hardened shared use | Shared team workspaces, SSH/Dask clusters, reviewed external apps, LLM connectors, local/offline LLMs, or sensitive internal datasets when the hardening gate passes. | Per-user isolation, strict `agilab security-check` gate, explicit secrets management, TLS/auth for exposed services, pinned/allowlisted external apps, SBOM plus vulnerability scan evidence for deployed install profiles, bounded resources, and a deployment threat model. |
| Not safe as-is | Sole production MLOps control plane, public Streamlit exposure, regulated production model serving, enterprise governance, online monitoring, drift detection, or audit-trail ownership. | Pair AGILAB with a hardened production stack such as MLflow/Kubeflow/SageMaker/Dagster/Airflow or an internal platform. |

For shared adoption, run `agilab security-check --profile shared --json` and
use `--strict` or `AGILAB_SECURITY_CHECK_STRICT=1` when missing controls should
block the gate. The stricter profiles check app-repository allowlists, public UI
bind controls, cluster-share isolation, generated-code execution boundaries,
plaintext local secrets, and profile-specific SBOM / `pip-audit` evidence.
Treat a clean strict report plus profile-specific SBOM / `pip-audit` evidence
as the documented go gate for hardened shared/team use. To persist the combined
decision, write the gate artifact:

```bash
uv --preview-features extra-build-dependencies run python tools/shared_go_gate.py \
  --security-check-json test-results/security-check.json \
  --supply-chain-dir test-results/supply-chain \
  --output test-results/shared_go_gate.json
```

## Security Reporting

Do not use public GitHub issues, discussions, pull requests, or comments for
suspected vulnerabilities. Use the private reporting path in
[SECURITY.md](https://github.com/ThalesGroup/agilab/blob/main/SECURITY.md);
if GitHub Private Vulnerability Reporting is not available to you, request a
private AGILAB security intake through a maintainer contact or another private
channel listed by the project. The public issue tracker is only for
non-sensitive bugs, support questions, and post-fix follow-up.

For adoption boundaries and the shared-use hardening checklist, see
[Security and adoption](https://thalesgroup.github.io/agilab/security-adoption.html).

## Dependency And Supply-Chain Boundaries

The public package is intentionally profile-based so operators can install only
what they need:

| Profile | Dependency scope | Use when |
|---|---|---|
| Base package | Lightweight `agilab` command shell plus Python 3.13 stdlib shims. It does not install the core runtime, UI, apps, pages, notebooks, or model stacks by default. | Version/help checks, package/app management commands, and metadata/reporting helpers that do not execute AGILAB runtime code. |
| `core` extra | `agi-core`, which wires `agi-env`, `agi-node`, and `agi-cluster` for compact local/distributed runtime smoke checks. | CLI proof, source-checkout validation, notebook/API runtime, and worker-runtime development without the UI or packaged examples. |
| `ui` extra | Streamlit UI, page helpers, portable `agi-web` UI-island contracts, pandas/network graph utilities, `agi-apps`, and the `agi-pages` provider. Promoted app and page payload packages are on PyPI; unpromoted app payloads remain release artifacts until publication is enabled. | Running the local product UI with the packaged runtime and optional public demo assets. |
| `examples` extra | `agi-apps` app catalog/examples plus notebook/demo helper dependencies such as JupyterLab and optional plotting packages. | Running packaged notebooks, demos, learning examples, and package first-proof routes. |
| `pages` extra | `agi-pages` page-provider helpers without the full UI profile. | Installing or validating sidecar page-bundle discovery separately from built-in app projects. |
| `proof` extra | Optional `cryptography` dependency for detached Ed25519 proof-capsule signatures. | Signing `.agipack` archives and verifying them against local trust policies. |
| `agents` extra | API client dependency boundary for packaged agent workflow helpers. | Reproducible coding-agent and assistant-backed workflows. |
| `mlflow` extra | MLflow tracking integration. | Recording runs, metrics, artifacts, or model registry handoff evidence. |
| `ai` and `viz` extras | API LLM clients and optional plotting packages. | Assistant-backed workflows or richer visual analysis. |
| `local-llm` / `offline` extras | Local/offline model stacks such as Torch, Transformers, GPT-OSS, and MLX where supported. | Isolated local-model experiments; expect a larger supply-chain and hardware footprint. |
| `dev` extra | Contributor test/build/audit tooling only. | Validating a source checkout or release candidate; avoid it for runtime installs. |

Agent workflows can now produce AGILAB evidence directly. Use
`agilab agent-run --agent codex --permission-level standard --label "Review current diff" --tag review --metadata branch=main -- codex review`
to execute a local coding-agent command and write a redacted
`agilab.agent_run.v1` manifest plus local stdout/stderr artifacts under
`~/log/agents/`. Each run also writes an append-only
`agilab.agent_trace.v1` stream in `agent_events.ndjson`, with typed events for
session, command/tool, permission, compaction, rewind, and completion evidence.
Command arguments are redacted by default and represented by an argv hash; pass
`--include-command-args` only when the prompt/arguments are safe to store.
Output artifact files redact obvious secret assignments, supported secret refs,
and common standalone API-token patterns by default; pass `--include-raw-output`
only for safe local diagnostics. Destructive executable names and obvious
destructive shell, Python, Git, Docker, Kubernetes, or package-manager command
content are operator-gated, but this permission layer is an evidence guard, not
a process sandbox. Add
`--protocol-adapter mcp` or `--capability app-as-tool` as metadata-only labels
when experimenting with agent protocol bridges; the base package records those
labels and lifecycle events without depending on the protocol stacks. Use
`agilab agent-run list --agent codex --json` or the Python helpers
`agilab.agent_run.trace_agent_run()` and
`agilab.agent_run.list_agent_runs()` to create or consume run evidence from
automation. Provider/model capability context can be stamped with
`--provider`, `--model`, project-local `.agilab/agents.json`, or global
`~/.agilab/agents/agents.json`.

Cluster/Dask support is intentionally part of the base runtime through
`agi-core`. AGILAB keeps local, pool, and distributed back planes behind the
same reproducible execution contract; moving `agi-cluster` behind an extra would
be only an install-footprint optimization if measured adoption data ever
justifies the added conditional paths.

Release and adoption supply-chain evidence is explicit: Dependabot watches
Python and GitHub Actions manifests, release workflows publish per-profile
`pip-audit` JSON and CycloneDX SBOM artifacts, and
`tools/profile_supply_chain_scan.py` can regenerate the same profile evidence
locally. PyPI publication uses Trusted Publishing/OIDC and the release workflow
runs `tools/pypi_provenance_check.py` after upload so missing PyPI attestations
fail before GitHub release assets are published.

## Evidence Taxonomy

AGILAB separates public claims by evidence type:

| Evidence type | What it proves | What it does not prove |
|---|---|---|
| Automated proof | Commands such as `agilab first-proof --json`, workflow parity checks, coverage, release proof, and UI robot evidence ran successfully. | Independent certification or coverage of every deployment topology. |
| Integration tests | A specific source path, package route, app, or workflow contract is exercised by tests. | Production SLA, security certification, or external operator acceptance. |
| Benchmarks | Timings for declared hardware, datasets, modes, and benchmark scripts. | General performance across arbitrary hardware, networks, or datasets. |
| Self-assessment | KPI scores such as production readiness and strategic potential are maintained from repository evidence. | External validation or third-party certification. |
| External validation | Only claimed when a named external artifact, reviewer, CI provider, or hosted demo proof is linked. | Implied endorsement beyond the linked evidence. |

## Proof Capsule Direction

The north-star product primitive is an AGILAB proof capsule: one portable,
reviewable bundle for a run or app promotion decision. It should collect the
run manifest, app/stage metadata, exported notebook handoff, MLflow handoff
metadata when enabled, UI robot screenshots/traces/HAR/video when captured,
artifact hashes, dependency locks, SBOM, `pip-audit`, wheel hashes, provenance,
and a short human/machine summary.

AGILAB already ships many of those pieces separately through first-proof
manifests, notebook export, release proof, supply-chain scans, robot artifacts,
and adoption reports. The first public proof-pack layer now adds
`agilab prove`, `agilab verify`, `agilab replay`, `agilab export-lineage`,
`agilab export-traces`, `agilab policy-check`, `agilab cards`, and
`agilab metadata-store` for `run_manifest.json` evidence, plus a
hash-verifiable `.agipack` archive. The `proof` extra adds detached Ed25519
signing with `agilab sign proof.agipack --key signer.pem --signature
proof.agipack.sig.json` and trust-policy verification with `agilab verify
proof.agipack --signature proof.agipack.sig.json --trust-policy policy.toml`.
External Sigstore/SLSA attestation binding, native lineage or observability
transport, durable ML metadata, rich app-authored cards, and enterprise
governance integrations remain roadmap work. See the
[proof capsule](https://thalesgroup.github.io/agilab/proof-capsule.html)
contract for the intended boundary.

## Repository Map And Stability Boundaries

The source repository intentionally keeps runtime packages, UI, built-in apps,
examples, release tooling, agent workflows, and docs together so release proof
can validate one coherent tree. Their stability differs:

Use three planes to read that tree:

| Plane | Owns | Main roots |
|---|---|---|
| Control plane | Product entry points, runtime APIs, environment resolution, worker packaging, and local/distributed execution. | `src/agilab/core/*`, `src/agilab/lib/agi-gui`, `src/agilab/lib/agi-web`, `src/agilab/pages` |
| Payload plane | Apps, page bundles, templates, notebooks, examples, and PyPI payload umbrellas. | `src/agilab/apps/builtin`, `src/agilab/apps-pages`, `src/agilab/lib/agi-apps`, `src/agilab/lib/agi-pages`, `src/agilab/examples` |
| Evidence plane | Proof, audits, release contracts, supply-chain evidence, UI robot outputs, docs mirror, and agent/runbook automation. | `tools`, `.github`, `docs/source`, `.codex`, `.claude`, `badges` |

| Area | Role | Stability contract |
|---|---|---|
| `src/agilab/core/*` | Runtime packages and compact API. | Stable where documented. |
| `src/agilab/lib/agi-gui`, `src/agilab/lib/agi-web`, `src/agilab/pages` | Main web UI, Streamlit page helpers, portable UI-island contracts, and app-surface launch adapters. | Beta product surface; app runtime contracts should not depend on one UI backend. |
| `src/agilab/lib/agi-apps` | PyPI umbrella carrying app catalog/example assets and exact-pinning the app payload packages already promoted to PyPI. Deferred app payloads remain release artifacts until publication is enabled. | Packaged asset surface for the `ui` and `examples` extras. |
| `src/agilab/lib/agi-pages` | PyPI provider package for public analysis page discovery. Published `agi-page-*` payload packages are distributed independently; `agi-pages` supplies the discovery/provider surface. | Packaged page-provider surface for the `ui` and `pages` extras. |
| `src/agilab/apps/builtin` | First-proof and demo apps. | Packaged examples, not deployment templates. |
| `src/agilab/examples` | Learning scripts and notebooks. | Educational examples with optional dependencies. |
| `tools`, `.github`, IDE and agent folders | Contributor/release automation. | Maintainer tooling, not runtime API. |

Local source checkouts can grow after runs because app `.venv` directories,
build outputs, caches, logs, and datasets are created locally. Those artifacts
are not the package contract. Public wheels exclude virtual environments,
tests, `docs/html`, build directories, generated C files, `__pycache__`, `.pyc`,
and `.egg-info` artifacts.

## Choose Your Path

1. Preview the product quickly: [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab)
2. Understand notebook-to-app migration: [Notebook Migration Demo](https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html)
3. Prove the full source-checkout flow: [Source Checkout](#source-checkout)
4. Verify a CLI-only package install: [Published Package](#published-package)
5. Audit external apps and evidence: [App Repository Updates](#app-repository-updates) and [Release Proof](https://thalesgroup.github.io/agilab/release-proof.html)

For a single-page adoption checklist, use
[ADOPTION.md](https://github.com/ThalesGroup/agilab/blob/main/ADOPTION.md).

## Source Version vs Package Version

AGILAB publishes from the GitHub repository, but each public surface has a
distinct role:

| Surface | Meaning | Source of truth |
|---|---|---|
| `main` branch and root `pyproject.toml` | Active source checkout and next release candidate. It can move after a package has already been published. | GitHub source tree |
| Release tag | Immutable source snapshot used for a public release. Use this for reproducible source installs. | GitHub tag and GitHub Release |
| PyPI package | Latest installable public wheel/sdist for `agilab` and the `agi-*` packages. | PyPI project and PyPI version badge |
| Release proof | Public evidence tying the release tag, PyPI package version, docs, CI, coverage, and demo proof together. | [Release Proof](https://thalesgroup.github.io/agilab/release-proof.html) |

For development, use `main`. For reproducible release validation, use the
release tag or the PyPI package version recorded in the release proof.

AGILAB uses date-based public versions. The dense `.postN` history in
April-May 2026 records public-beta packaging hardening, provenance refreshes,
and dependency-pin alignment across the split package set. It is kept visible
for auditability, but it is not the target steady-state release rhythm; normal
feature or behavior changes should advance to a deliberate new date-based
release. The `pypi-publish` workflow now rejects committed public `.postN`
versions unless a maintainer explicitly marks the dispatch as a critical hotfix
and records the reason; release candidates or TestPyPI should be used before a
final public release.

## Source Checkout

Run the installable product path with the built-in `flight_telemetry_project`:

```bash
CHECKOUT="${AGILAB_CHECKOUT:-$HOME/agilab-src}"
git clone https://github.com/ThalesGroup/agilab.git "$CHECKOUT"
cd "$CHECKOUT"
./install.sh --install-apps
uv --preview-features extra-build-dependencies run --extra ui streamlit run src/agilab/main_page.py
```

On native Windows, prefer the published package route below. The source checkout
installer uses POSIX shell scripts, so run that path from WSL2 until native
installer parity is published.

Follow the in-app pages from `PROJECT` to `ORCHESTRATE`, `WORKFLOW`, and
`ANALYSIS`. To collect the same check as JSON:

```bash
uv --preview-features extra-build-dependencies run agilab first-proof --json
```

The JSON proof writes `run_manifest.json` under `~/log/execute/flight_telemetry/`. For
installer flags, IDE run configs, and troubleshooting, use the Quick Start docs.

## Published Package

For a CLI-only package smoke without Streamlit:

```bash
uv --preview-features extra-build-dependencies tool install --upgrade "agilab[examples]"
agilab first-proof --json --max-seconds 60
```

## App Repository Updates

When `APPS_REPOSITORY` points at an external apps repository, rerun the
installer after app changes:

```bash
./install.sh --non-interactive --apps-repository /path/to/apps-repository --install-apps all
```

During an update, the apps repository is treated as the source of truth. If the
target app/page already exists as a real directory instead of a symlink, AGILAB
backs it up as `<name>.previous.<timestamp>`, then links the repository copy in
its place. After the update, AGILAB runs the repository version; the
`.previous` directory is kept only for manual recovery. See
[Service mode and paths](https://thalesgroup.github.io/agilab/service_mode_and_paths.html)
for the full path contract.

## Evidence And Scope

The PyPI README is only the install entry page. Detailed capability evidence,
compatibility status, and roadmap scope live in:

- [Features](https://thalesgroup.github.io/agilab/features.html)
- [Capability map](https://thalesgroup.github.io/agilab/capability-map.html)
- [Release proof](https://thalesgroup.github.io/agilab/release-proof.html)
- [Compatibility matrix](https://thalesgroup.github.io/agilab/compatibility-matrix.html)
- [MLOps positioning](https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html)
- [Package publishing policy](https://thalesgroup.github.io/agilab/package-publishing-policy.html)
- [Future work](https://thalesgroup.github.io/agilab/roadmap/agilab-future-work.html)
- [Audience bridges](https://thalesgroup.github.io/agilab/roadmap/audience-bridges.html)

## Evaluation Snapshot

Current public evaluation summary, refreshed from the public KPI bundle:

- `4.0 / 5` for ease of adoption, research experimentation, and engineering prototyping.
- `3.0 / 5` for production readiness.
- `4.2 / 5` for strategic potential.
- Overall public evaluation, rounded category average: `3.8 / 5`.

These are AI/ML workbench scores, not production MLOps claims.
They cover project setup, environment management, execution, and result analysis.
The overall score is the rounded category average, not a strategic score.

## Read Next

- [Demo chooser](https://thalesgroup.github.io/agilab/demos.html)
- [Demo capture guide](https://thalesgroup.github.io/agilab/demo_capture_script.html)
- [Quick start](https://thalesgroup.github.io/agilab/quick-start.html)
- [Adoption guide](https://github.com/ThalesGroup/agilab/blob/main/ADOPTION.md)
- [Notebook quickstart](https://thalesgroup.github.io/agilab/notebook-quickstart.html)
- [Documentation](https://thalesgroup.github.io/agilab)
- [Flight-telemetry project guide](https://thalesgroup.github.io/agilab/flight-telemetry-project.html)
- [Source repository](https://github.com/ThalesGroup/agilab)
- [Issues](https://github.com/ThalesGroup/agilab/issues)
