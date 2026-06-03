# AGILAB - Detailed Code Review

> Scope: fully inspected `tools/audit_quality_evaluator.py`, `src/agilab/main_page.py`, and sampled docs.
> Limits: worker internals were sampled, not exhaustively inspected.

## Executive summary

Verdict: conditional go. The dominant thesis is that execution boundaries are
good for local research but need stronger guardrails for shared cluster use.

## Scope and method

- Fully inspected: tools/audit_quality_evaluator.py, src/agilab/main_page.py:42,
  src/agilab/ui_public_bind_guard.py:17, docs/source/apps-pages.rst:148
- Sampled: src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker.py:88
- Commands/evidence used: uv --preview-features extra-build-dependencies run pytest -q,
  python tools/workflow_parity.py --profile skills, git status --short

## Architecture and module topology

The package topology separates control plane, payload plane, and evidence plane.
The handoff runtime boundary is clear, but workflow ownership crosses modules.
AGILAB is a trusted-operator reproducibility workbench, not a standalone
production MLOps control plane. The `agi-pages` umbrella and apps-pages stay
app-agnostic, so project-specific dependencies belong in app/page packages
instead of generic providers. Linux, macOS, and Windows assumptions are part of
the audit boundary. Release proof, package split, docs mirror, and public claims
must agree before a feature is described as shipped.

## Findings

### Finding 1 - generated-code sandbox is policy based - **HIGH**

- Evidence: src/agilab/lab_run.py:120 and tools/audit_quality_evaluator.py:10.
- Mechanism: generated code can enter an execution path after an environment gate.
- Impact: shared workspaces can run untrusted payloads.
- Blast radius: UI, worker execution, cluster workflows, and tests.
- Recommendation: require container or VM isolation for shared profiles.
- Regression plan: add pytest coverage and workflow_parity.py shared profile checks.

## Security posture

Security review covered shell, subprocess, secrets, credentials, pickle, MCP,
public bind, SBOM, provenance, and PyPI release evidence.

## Testing and cross-platform posture

Validation uses pytest and uv --preview-features extra-build-dependencies run
commands. Missing test gap: Windows path quoting remains unverified.

## Packaging, docs, and release posture

Packaging and release posture cover wheel surface, docs mirror, changelog,
PyPI provenance, GitHub release proof, and public documentation claims.

## Prioritized recommendations

| # | Severity | Issue | Action | Validation |
|---|---|---|---|---|
| 1 | **HIGH** | sandbox boundary | Add isolation gate | pytest and workflow profile |
| 2 | **MED** | docs drift | Centralize mirror checks | ./dev docs |

## Residual risks

Some cluster behavior is unverified without a live remote worker.

## Bottom line

Bottom line: go for local research, conditional go for shared clusters, no-go
for production multi-tenant serving without additional controls.
