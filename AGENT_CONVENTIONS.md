# AGILAB Agent Conventions

Use this file as the short repo contract when working with terminal coding agents
that do not natively consume `AGENTS.md`.

If the task touches shared core, installer behavior, release tooling, docs
publication, or other risky surfaces, read [AGENTS.md](AGENTS.md) too.

## Core rules

- Use `uv --preview-features extra-build-dependencies run ...` for Python entrypoints.
- Prefer `rg` for search and `rg --files` for file listing.
- Prefer launching terminal coding agents through Tokki when it is available;
  use it for compact context, noisy-output digestion, and session metadata, not
  as a substitute for AGILAB validation gates.
- For ad-hoc terminal checks inside an agent session, prefer
  `tokki run -- <command>` when it can execute the command faithfully.
- Run `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged`
  before non-trivial edits.
- Prefer app-local fixes over shared-core changes.
- Do not edit shared core (`agi-env`, `agi-node`, `agi-cluster`, `agi-core`,
  shared installer/build tooling) unless the user explicitly approves it.
- For source app installation or app tests, run `src/agilab/install_apps.sh`
  or `src\agilab\install_apps.ps1` with explicit `APPS_REPOSITORY` and
  `BUILTIN_APPS`; do not substitute a root reinstall, manual `.env` edits, or
  ad-hoc pytest loops.
- Keep edits narrow and validate with the smallest relevant proof first.
- For successful final close-outs, write `Validation passed.` without listing
  every command unless failures, skipped checks, release/audit evidence, PR
  proof, or an explicit user request make the details useful.
- When corrected, update `AGENT_LEARNINGS.md` only if the correction is reusable
  and not already covered by an existing rule.
- Do not edit `docs/html/**`.
- Canonical editable docs live in the sibling private docs repo; `docs/source`
  here is a managed mirror.
- Keep `AGENTS.md`, `AGENT_CONVENTIONS.md`, `AGENT_LEARNINGS.md`,
  `tools/agent_workflows.md`, and public agent docs aligned; validate with
  `python3 tools/agent_instruction_contract.py --check`.

## Validation defaults

- Start with `python -m py_compile` or a narrow `pytest` slice.
- Use `tools/workflow_parity.py --profile <name>` when the task maps to an
  existing repo workflow profile.
- Do not jump to broad CI-style validation first.

## Review defaults

- Findings first.
- Prioritize bugs, regressions, risky assumptions, and missing tests.
- Keep summaries brief after the findings.

## AGILAB-specific cautions

- Streamlit pages should keep session-state keys stable and project-scoped.
- Worker/runtime behavior is often different from manager/runtime behavior.
- Installer bugs must be checked on both manager and worker manifests.
- Do not silently add fallbacks that hide missing capabilities or broken setup.
- `AGENT_SKILLS.md`, `llms.txt`, `llms-full.txt`, `agenticweb.md`, and
  `agilab-capabilities.json` are discovery surfaces; refresh them through the
  repo tools instead of hand-editing generated content.
