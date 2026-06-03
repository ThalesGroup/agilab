# AGILAB Architecture Foundations

Use this reference before producing a deep AGILAB audit. If the current session
cannot explain these foundations with evidence from the live repository, it must
perform an architecture read pass first and mark any remaining uncertainty as a
scope limit.

## Product boundary

- AGILAB is a trusted-operator reproducibility workbench for turning AI/ML
  experiments, notebooks, apps, and agent runs into replayable evidence.
- It is not a standalone production MLOps control plane, multi-tenant platform,
  enterprise governance layer, drift-monitoring system, or regulated serving
  system as-is.
- Audit language must keep local research, controlled lab, shared cluster, and
  production boundaries separate.

## Architectural planes

- Control plane: UI, orchestration, project selection, command planning, service
  health, and operator-facing workflow state.
- Payload plane: app code, notebooks, generated snippets, worker payloads,
  external stages, page bundles, and executable dependencies.
- Evidence plane: manifests, hashes, release proof, notebook export manifests,
  SBOM/pip-audit/provenance artifacts, UI robot evidence, logs, and replay or
  verifier contracts.
- A finding is weak if it confuses these planes. UI convenience must not be
  treated as runtime isolation, and release evidence must not be treated as
  production monitoring.

## Package and dependency principles

- Base AGILAB stays lean. Optional extras and split packages carry heavier UI,
  MLflow, notebook, OpenAI, local-LLM, app, or page-bundle dependencies.
- Built-in app projects may declare project-specific manager and worker
  dependencies in their own manifests.
- Apps-pages are page bundles. The `agi-pages` umbrella/provider must stay
  lightweight and app-agnostic; do not add project-specific runtime
  dependencies to `agi-pages` or generic page bundles just to satisfy one app.
- If a page bundle needs heavy or domain-specific dependencies, it should remain
  a standalone `agi-page-*` distribution or source-checkout opt-in rather than
  polluting the umbrella dependency graph.
- Package-contract, provider registry, docs catalog, and pyproject metadata must
  agree before a page/app can be described as shipped.

## Cross-platform contract

- AGILAB supports Linux, macOS, and Windows paths in public workflows unless a
  feature explicitly states a narrower platform boundary.
- Audits must check path separators, shell quoting, subprocess invocation,
  environment handling, `HOME` assumptions, symlink behavior, service/process
  management, and generated file paths with cross-platform behavior in mind.
- Windows network-share, SSH, shell, and path behavior should be treated as
  first-class risk surfaces, not afterthoughts.

## Execution and isolation principles

- Apps, notebooks, generated snippets, worker code, external app repositories,
  and page bundles are executable code trust boundaries.
- Raw/generated Python execution is not an OS sandbox. Shared or sensitive use
  requires process/container/VM isolation, filesystem and network limits,
  timeouts, and explicit secret handling.
- Remote worker IPs, shares, and cluster state are discovery-time facts. Do not
  reuse remembered IPs or silently degrade requested cluster execution to local
  execution.
- Shell command construction must be centralized, quoted, redacted, and tested
  with spaces and metacharacters.

## Documentation and release truth

- Canonical docs are authored in the sibling `thales_agilab/docs/source` tree
  and mirrored into `agilab/docs/source` with a stamp.
- Public claims must match current release proof, package split, changelog,
  PyPI/GitHub release evidence, and Hugging Face/docs publication state.
- Do not present roadmap items as shipped capabilities.

## Mandatory audit stance

Before writing a final audit, the session must be able to state:

- Which architecture planes are involved.
- Which package boundary is being evaluated.
- Whether the finding affects local, shared/cluster, public UI, release, or
  production adoption.
- Which Linux/macOS/Windows assumptions were checked or remain unverified.
- Whether any recommended dependency change violates the app/page/core package
  boundary.
