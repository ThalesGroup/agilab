---
name: agilab-evidence-contracts
description: Maintain AGILAB evidence, proof, replay, and verification contracts. Use when code, docs, tests, or workflows touch run manifests, artifact hashes, first-proof or release-proof evidence, proof capsules, notebook exports, agent-run traces, MLflow handoff, replay commands, or claims about reproducibility and attestation.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-30
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
  version alignment, and trusted-publisher outputs.
- **UI robot evidence**: screenshots, robot JSON, route coverage, widget actions,
  and public demo proof artifacts.

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

## Review Workflow

1. Inspect the current evidence producer before changing docs or claims.
2. Identify the consumer: human review, replay command, release gate, robot,
   notebook export, MLflow handoff, or downstream app.
3. Keep the manifest additive when possible; if removing or renaming fields,
   update readers, tests, docs, and migration notes in the same change.
4. Prefer a small verifier over manual inspection for critical evidence.
5. For docs, state the exact command and path that produce the evidence.
6. For release work, compare `CHANGELOG.md`, release proof, workflow output,
   PyPI/GitHub release state, docs, and Hugging Face sync before claiming done.

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
