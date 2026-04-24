# AGILAB Agent Conventions

Use this file as the short repo contract when working with terminal coding agents
that do not natively consume `AGENTS.md`.

If the task touches shared core, installer behavior, release tooling, docs
publication, or other risky surfaces, read [AGENTS.md](AGENTS.md) too.

## Core rules

- Use `uv --preview-features extra-build-dependencies run ...` for Python entrypoints.
- Prefer `rg` for search and `rg --files` for file listing.
- Run `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged`
  before non-trivial edits.
- Prefer app-local fixes over shared-core changes.
- Do not edit shared core (`agi-env`, `agi-node`, `agi-cluster`, `agi-core`,
  shared installer/build tooling) unless the user explicitly approves it.
- Keep edits narrow and validate with the smallest relevant proof first.
- Do not edit `docs/html/**`.
- Canonical editable docs live in the sibling private docs repo; `docs/source`
  here is a managed mirror.

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
- For Streamlit 1.56+ UI work, prefer native `st.iframe`, use `filter_mode="contains"`
  only on long searchable selectors, and use `st.menu_button` for compact action menus
  without replacing useful visible shortcuts.
- Worker/runtime behavior is often different from manager/runtime behavior.
- Installer bugs must be checked on both manager and worker manifests.
- Do not silently add fallbacks that hide missing capabilities or broken setup.
