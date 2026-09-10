---
name: agilab-evidence-contracts
description: Maintain AGILAB evidence, proof, replay, and verification contracts. Use when code, docs, tests, or workflows touch run manifests, artifact hashes, first-proof or release-proof evidence, proof capsules, notebook exports, agent-run traces, MLflow handoff, replay commands, or claims about reproducibility and attestation.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-09-10
---

# AGILAB Evidence Contracts

Use this skill when a change affects AGILAB's evidence-first value: proving that
an experiment, app run, notebook migration, agent action, or release can be
reviewed and replayed. The default stance is simple: a feature is not validated
unless it leaves evidence with a schema, path contract, artifact hashes when
possible, and a verification or replay command.

## Evidence Surfaces

Classify the touched surface before editing:

- **Run evidence**: `run_manifest.json`, app/stage metadata, produced artifacts,
  timing, environment context, status, and error summaries.
- **Proof evidence**: `agilab first-proof`, release proof, proof capsules,
  signatures, replay/verify commands, and adoption reports.
- **Notebook handoff**: imported notebooks, exported notebooks, stage manifests,
  `lab_stages.toml`, generated analysis views, and exit-path artifacts.
- **Agent evidence**: `agilab.agent_run.v1` manifests, event streams,
  stdout/stderr artifacts, lineage, handoff, and redaction behavior.
- **Supply-chain evidence**: SBOM, `pip-audit`, PyPI provenance, release assets,
  dataset release manifests, version alignment, and trusted-publisher outputs.
- **UI robot evidence**: screenshots, robot JSON, route coverage, widget actions,
  and public demo proof artifacts.
- **Workflow dry-run evidence**: static validation reports for `lab_stages.toml`,
  notebook-import previews, capability manifests, and other contract checks
  that prove readiness without executing user code.

## Contract Checklist

For every new or changed evidence output, verify:

- It has a stable `schema` or explicit version field.
- It records producer, command, timestamp or run id, version, and target context.
- It records artifact paths relative to a declared root, not machine-specific
  private absolute paths unless explicitly marked local-only.
- It includes file size and `sha256` for persisted artifacts when feasible.
- It distinguishes missing, skipped, failed, and passed states.
- It redacts secrets and stores command/env values safely.
- It has a documented verification, replay, or inspection command.
- It has at least one regression test that catches schema or path drift.
- Public docs describe what the evidence proves and what it does not prove.

For agent workflow completion claims, bind the successful tool/run terminal result
to the exact executed inputs or source snapshot, using a recorded revision or
artifact digest. A final assistant message, a generated plan, and the absence of
errors do not establish that binding. A digest alone establishes identity, not
execution. If completion or source binding is missing, report what remains
unverified; do not pair an older successful run with newer unexecuted source.
Keep shared evidence limited to redacted identifiers and artifact metadata;
retain raw provider transcripts and sensitive execution inputs in their existing
local evidence store.

For GitHub dataset release evidence, also verify that the manifest records every
tracked dataset path, size, `sha256`, LFS-tracking status, and whether the file
is packaged into PyPI artifacts. The release archive must contain materialized
dataset contents, not Git LFS pointer files, and it must remain separate from
the normal source/code GitHub Release assets.

## Anti-Patterns

- Claiming "validated", "certified", "reproducible", or "release-ready" without
  a linked command or artifact.
- Writing evidence under a hidden or unstable location without documenting the
  path contract.
- Storing only screenshots or prose when a machine-readable manifest is needed.
- Hashing transient paths but not the artifacts users actually inspect.
- Treating UI success as run success without backend evidence.
- Mixing local developer state into public release proof.
- Updating docs, badges, or scorecards without checking the current evidence.

## Skill Receipts and Graph Explanations

Use `agilab.skill_evaluation_plan.v1` to freeze skill inputs and the case cohort,
then `agilab.skill_evaluation_receipt.v1` to retain observations from a linked
`agilab.agent_run.v1` manifest. Follow the
[evaluation receipt workflow](../agilab-prompt-eval-regression/references/evaluation-receipts.md).
Receipt references remain relative to the declared root when the complete bundle
moves; native manifests retain their original local metadata and bytes. Keep
verification status separate from evaluation status: failed evaluations can have
valid, verifiable receipts. Evaluator versions are declared configuration, and
plan metadata establishes association rather than execution of the frozen source.

Workflow evidence graphs attach JSON source pointers and `declared` or `derived`
bases to relationships. The source digest hashes the canonical JSON manifest,
not its on-disk formatting. Inspect a bounded neighborhood with:

```bash
uv --preview-features extra-build-dependencies run python -m agilab.evidence.evidence_graph --manifest path/to/workflow_run_manifest.json
uv --preview-features extra-build-dependencies run python -m agilab.evidence.evidence_graph --manifest path/to/workflow_run_manifest.json --node stage:prepare --direction incoming --max-depth 3 --max-nodes 50 --max-edges 100
```

Use a node id from the first command. `incoming` follows supporting relationships;
`outgoing` follows dependents. Check `truncated` before treating a neighborhood as
complete. The API accepts older graphs, but `source_verified` is true only when
the original manifest is supplied and reconstructs the same graph. Relationship
evidence explains manifest declarations and derived structure; it does not prove
causation, artifact content, execution, or successful validation.

## External Inspiration Gate

When a user points to an external product, framework, repository, or docs URL as
inspiration, do not convert the idea directly into roadmap prose. First extract
the transferable pattern, reject parts that do not fit AGILAB's evidence-first
positioning, then implement the smallest AGILAB-native evidence primitive when
the idea is worth adopting.

A valid adopted pattern should normally include:

- a stable schema such as `agilab.<feature>.v1`;
- a producer command, report, manifest, validator, or dry-run checker;
- a reader or UI inspection surface when humans need to review the evidence;
- tests that fail on schema, path, or stale-output drift;
- public docs stating what the evidence proves and what it does not prove.

Examples: a declarative workflow idea should become a `lab_stages.toml`
validator or graph contract, not a new unbounded DSL; an agent-platform catalog
idea should become a machine-readable AGILAB capability index, not marketing
copy.

## Review Workflow

1. Inspect the current evidence producer before changing docs or claims.
2. Identify the consumer: human review, replay command, release gate, robot,
   notebook export, MLflow handoff, or downstream app.
3. Keep the manifest additive when possible; if removing or renaming fields,
   update readers, tests, docs, and migration notes in the same change.
4. Prefer a small verifier over manual inspection for critical evidence.
5. For docs, state the exact command and path that produce the evidence.
6. For release work, compare `CHANGELOG.md`, release proof, workflow output,
   PyPI/GitHub code release state, GitHub dataset release state, docs, and
   Hugging Face sync before claiming done.
7. For external inspiration, record the AGILAB-native evidence primitive that
   was shipped, or state explicitly why no implementation was adopted.

## Validation Commands

Start with impact triage:

```bash
uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged
```

Use the narrow evidence checks that match the change:

```bash
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_evidence_contract.py
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_agent_trace.py test/test_agent_run.py
uv --preview-features extra-build-dependencies run python tools/release_proof_check.py
uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile skills
```

When touching proof capsules or release publication, inspect the current release
plan instead of relying on memory:

```bash
./dev --print-only release
uv --preview-features extra-build-dependencies run python tools/pypi_project_preflight.py
```

Report residual risk when evidence depends on external services, hosted demos,
clusters, GPU hardware, cloud credentials, or a workflow that was not rerun.
