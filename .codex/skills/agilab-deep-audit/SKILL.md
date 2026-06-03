---
name: agilab-deep-audit
description: Produce deep AGILAB audit and code-review artifacts with evidence-backed findings, mandatory architecture-foundation readiness, blast-radius tracing, security/test posture, and prioritized recommendations. Use when the user says "review AGILAB", "audit AGILAB", "code review AGILAB", "deep review", "architecture review", "security review", asks for a review document, or asks for comparison-quality critique rather than a quick fix.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-29
---

# AGILAB Deep Audit Skill

Use this skill when the user asks for an AGILAB audit or a review artifact. Do
not treat an audit request as a maintenance/fix request unless the user
explicitly asks to patch findings.

## Operating mode

- Start in review mode, not implementation mode.
- Inspect current repository state before making claims; do not rely on memory
  for branch, version, workflow, or public-posture facts.
- Load `references/ARCHITECTURE_FOUNDATIONS.md` before a deep audit unless the
  user explicitly requests a narrow file-only review. If the session cannot
  explain the foundations in that reference from current repository evidence,
  pause the final audit and perform an architecture read pass first.
- State scope and limits explicitly. If the repo is too large for exhaustive
  reading, say which central modules were read and which periphery was sampled.
- Build a thesis, not a checklist. Identify the dominant root cause or design
  pressure when findings cluster.
- Findings come first for code reviews. For broader audits, put verdict and
  executive summary first, then detailed evidence.
- Do not overclaim. If a module or workflow was not inspected, label the point
  as an inference or residual risk.

## Architecture readiness gate

Before producing a final deep audit, confirm the session has current evidence
for AGILAB's founding principles:

- Trusted-operator reproducibility workbench, not a standalone production MLOps
  control plane.
- Three-plane model: control plane, payload plane, evidence plane.
- Lean base package plus optional extras and split packages for heavier
  capabilities.
- Built-in apps can own project-specific dependencies; generic apps-pages and
  the `agi-pages` umbrella must remain app-agnostic and avoid project-specific
  runtime dependencies.
- Linux, macOS, and Windows support is part of the public posture unless a
  feature states a narrower boundary.
- Generated code, notebooks, external apps, workers, page bundles, and cluster
  execution are executable-code trust boundaries.
- Docs, release proof, package split, and public claims must agree before a
  feature is described as shipped.

If any point is unclear, do not guess. Read the relevant package manifests,
provider registries, docs, release proof, tests, and workflow files first, then
state what remains unverified.

## Default AGILAB audit scope

For a deep AGILAB audit, cover these surfaces unless the user narrows scope:

- Package topology: root `pyproject.toml`, core package manifests, extras split,
  and stable handoff claims.
- Core runtime: `agi-env`, `agi-node`, `agi-cluster`, `agi-core`, especially
  singleton state, command execution, worker dispatch, local/remote deployment,
  path resolution, and service/evidence helpers.
- Execution engine: dispatcher/distributor scheduling, chunking, worker
  capacity, generated code paths, shell boundaries, and runtime dependency
  mutation.
- UI and public exposure: Streamlit entrypoints, public-bind guard, page state,
  session-state boundaries, and user-visible workflow paths.
- Security posture: credential redaction, subprocess/shell usage, pickle or
  executable payload boundaries, external apps policy, public UI controls,
  supply-chain/provenance, and MCP write/exec exposure.
- Cross-platform and tests: Windows/macOS/Linux claims, hermetic `HOME`
  behavior, singleton resets, path separators, process/signal assumptions, and
  CI workflow coverage.
- Packaging and docs: wheel surface, generated artifacts, docs/public mirror,
  release proof, and changelog/public claim alignment.
- Periphery sampling: representative built-in apps, page bundles, and examples
  only after the central architecture is understood.

## Evidence collection pattern

Plan the read pass before opening files. Prefer targeted reads over broad scans:

```bash
git status --short --branch --untracked-files=no
git log --oneline -5
sed -n '1,220p' pyproject.toml
find src/agilab/core -maxdepth 3 -name pyproject.toml -print
rg -n "class AgiEnv|__new__|__init__|shell=True|pickle\\.load|eval\\(|exec\\(|subprocess|create_subprocess|AGILAB_PUBLIC_BIND|MCP|FastMCP|security-check|Path\\.home|except Exception|bare except|uv add|command -v sshfs" src/agilab tools test
```

Then read the specific files implicated by the hits. For full audits, useful
anchors are usually:

- `src/agilab/core/agi-env/src/agi_env/agi_env.py`
- `src/agilab/core/agi-env/src/agi_env/execution_support.py`
- `src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker.py`
- `src/agilab/core/agi-node/src/agi_node/agi_dispatcher/work_dispatcher.py`
- `src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py`
- `src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/agi_distributor.py`
- `src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/deployment_local_support.py`
- `src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/deployment_remote_support.py`
- `src/agilab/lab_run.py`
- `src/agilab/ui_public_bind_guard.py`
- `src/agilab/mcp/server.py` when MCP exists
- `test/conftest.py`, root tests, and `src/agilab/core/test`
- `README.md`, `SECURITY.md`, `CHANGELOG.md`, and `docs/source/release-proof.rst`

When reading line-sensitive code, use `nl -ba <file> | sed -n 'start,endp'`
or an equivalent command so the final review can cite stable line references.

## Review quality bar

Each important finding should include:

- Severity: `CRITICAL`, `HIGH`, `MED-HIGH`, `MED`, `LOW`
- Evidence: file and line references, concrete call-sites, commands, or test
  failures
- Mechanism: what the code actually does
- Impact: what can break, leak, become nondeterministic, or mislead users
- Blast radius: which pages/apps/workflows/tests are affected
- Recommendation: the smallest good fix plus any stronger architectural fix
- Regression plan: targeted tests or workflow profiles that would prove the fix

Prefer one strong root-cause section over many shallow bullets when the same
design issue appears in several places.

## Output template

For a review document, use
`templates/CODE_REVIEW_TEMPLATE.md` as the canonical file structure. If the
template file is unavailable, write this structure:

```markdown
# AGILAB — Detailed Code Review

> Reviewer: Codex · Date: YYYY-MM-DD · Branch: `<branch>`
>
> **Scope.** <what was read fully, what was sampled, and what was out of scope>

## Executive summary

<verdict, dominant thesis, strongest positives, and top risks>

## 1. Architecture & module topology

<package graph, stable handoff assessment, module decomposition, drift/debt>

## 2. High-severity finding title · **HIGH**

<mechanism, evidence, call-sites, blast radius, recommendation>

## 3. Execution engine

<scheduler/dispatcher/build/runtime mutation findings>

## 4. Security posture

<public bind, shell, secrets, pickle, MCP, external apps, supply chain>

## 5. Testing & cross-platform

<test breadth, hermeticity, Windows/macOS/Linux claims, CI coverage>

## 6. Packaging & repo hygiene

<wheel surface, generated artifacts, docs/release/public claim alignment>

## 7. Prioritized recommendations

| # | Severity | Issue | Action |
|---|---|---|---|
| 1 | **HIGH** | <issue> | <action> |

## Bottom line

<short, honest final judgement>
```

For a shorter audit response, keep the same logic but compress it:
verdict, scope, top strengths, top findings, prioritized actions, bottom line.

## Quality gate

When the audit is written to a Markdown file, run the deterministic quality
evaluator before handoff unless the user explicitly asks not to validate:

```bash
uv --preview-features extra-build-dependencies run python tools/audit_quality_evaluator.py <audit.md> --min-score 80
```

Use `./dev audit-preflight` before writing a long audit when the architecture
context is not fresh. Use `./dev audit-quality <audit.md>` as the short local
gate after writing the audit.

Use `--json --output <report.json>` when the score should become evidence. A
score below 80 means the artifact is not yet comparison-quality; improve the
missing rubric areas before presenting it as a final audit.

## Validation and follow-up

- Do not patch during the audit unless the user asks.
- If the user later says `fix it`, convert the prioritized findings into a
  narrow implementation plan and use `agilab-testing` to select regressions.
- If the audit is written to a file, mention the exact path and whether it is
  committed, uncommitted, or only a local artifact.
